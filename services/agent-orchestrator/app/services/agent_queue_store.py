from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.schemas.workflow import AgentApprovalRequest, AgentQueueTask, WorkflowOutput, WorkflowRequest


class AgentQueueStore:
    def __init__(self, data_file: Path | None = None) -> None:
        self._lst: list[AgentQueueTask] = []
        self._lk = threading.RLock()
        p = data_file or (Path(__file__).resolve().parents[2] / "data" / "agent_queue.json")
        self._fp = p
        self._load()

    def enqueue(
        self,
        payload: WorkflowRequest,
        *,
        requested_engine: str | None = None,
        priority: int = 100,
    ) -> AgentQueueTask:
        ts = datetime.now(timezone.utc)
        tid = str(uuid.uuid4())
        eng = (requested_engine or "").strip().lower()
        if eng == "":
            eng = None
        t = AgentQueueTask(
            id=tid,
            status="queued",
            payload=payload.model_copy(deep=True),
            workflow_type=payload.workflow_type,
            requested_engine=eng,
            priority=priority,
            created_at=ts,
            updated_at=ts,
        )
        with self._lk:
            self._lst.append(t)
            self._save_locked()
        return t.model_copy(deep=True)

    def get(self, task_id: str) -> AgentQueueTask | None:
        with self._lk:
            for x in self._lst:
                if x.id == task_id:
                    return x.model_copy(deep=True)
        return None

    def list(
        self,
        *,
        patient_id: str | None = None,
        conversation_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[AgentQueueTask]:
        with self._lk:
            arr = list(reversed(self._lst))
            if patient_id:
                arr = [x for x in arr if x.payload.patient_id == patient_id]
            if conversation_id:
                arr = [x for x in arr if x.payload.conversation_id == conversation_id]
            if status:
                arr = [x for x in arr if x.status == status]
            return [x.model_copy(deep=True) for x in arr[:limit]]

    def stats(self) -> dict[str, int]:
        cnt: dict[str, int] = {
            "queued": 0,
            "running": 0,
            "waiting_approval": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
        }
        with self._lk:
            for x in self._lst:
                s = x.status
                cnt[s] = cnt.get(s, 0) + 1
        tot = 0
        for v in cnt.values():
            tot += v
        cnt["total"] = tot
        return cnt

    def claim_next(self) -> AgentQueueTask | None:
        with self._lk:
            cands: list[tuple[int, AgentQueueTask]] = []
            i = 0
            while i < len(self._lst):
                x = self._lst[i]
                if x.status == "queued":
                    cands.append((i, x))
                i += 1
            if len(cands) == 0:
                return None

            best_idx = cands[0][0]
            best = cands[0][1]
            j = 1
            while j < len(cands):
                idx, cur = cands[j]
                if (cur.priority, cur.created_at, idx) < (best.priority, best.created_at, best_idx):
                    best_idx = idx
                    best = cur
                j += 1

            ts = datetime.now(timezone.utc)
            upd = best.model_copy(
                update={
                    "status": "running",
                    "updated_at": ts,
                    "started_at": ts,
                    "completed_at": None,
                    "attempt_count": best.attempt_count + 1,
                    "error": None,
                }
            )
            self._lst[best_idx] = upd
            self._save_locked()
            return upd.model_copy(deep=True)

    def complete(self, task_id: str, output: WorkflowOutput) -> AgentQueueTask | None:
        with self._lk:
            idx = self._index_locked(task_id)
            if idx is None:
                return None
            cur = self._lst[idx]
            ts = datetime.now(timezone.utc)
            upd = cur.model_copy(
                update={
                    "status": "completed",
                    "updated_at": ts,
                    "completed_at": ts,
                    "run_id": output.run_id,
                    "runtime_engine": output.runtime_engine,
                    "summary": output.summary,
                    "last_output": output,
                    "approvals": list(cur.approvals),
                    "error": None,
                }
            )
            self._lst[idx] = upd
            self._save_locked()
            return upd.model_copy(deep=True)

    def wait_for_approval(self, task_id: str, output: WorkflowOutput) -> AgentQueueTask | None:
        with self._lk:
            idx = self._index_locked(task_id)
            if idx is None:
                return None
            cur = self._lst[idx]
            ts = datetime.now(timezone.utc)
            apps = self._merge_approvals_locked(cur.approvals, output.pending_approvals)
            upd = cur.model_copy(
                update={
                    "status": "waiting_approval",
                    "updated_at": ts,
                    "run_id": output.run_id,
                    "runtime_engine": output.runtime_engine,
                    "summary": output.summary,
                    "last_output": output,
                    "approvals": apps,
                    "error": None,
                }
            )
            self._lst[idx] = upd
            self._save_locked()
            return upd.model_copy(deep=True)

    def fail(self, task_id: str, *, error: str, output: WorkflowOutput | None = None) -> AgentQueueTask | None:
        with self._lk:
            idx = self._index_locked(task_id)
            if idx is None:
                return None
            cur = self._lst[idx]
            ts = datetime.now(timezone.utc)
            rid = output.run_id if output else cur.run_id
            eng = output.runtime_engine if output else cur.runtime_engine
            summ = output.summary if output else cur.summary
            last_out = output or cur.last_output
            upd = cur.model_copy(
                update={
                    "status": "failed",
                    "updated_at": ts,
                    "completed_at": ts,
                    "run_id": rid,
                    "runtime_engine": eng,
                    "summary": summ,
                    "last_output": last_out,
                    "error": error,
                }
            )
            self._lst[idx] = upd
            self._save_locked()
            return upd.model_copy(deep=True)

    def approve(
        self,
        task_id: str,
        *,
        approval_ids: list[str],
        decided_by: str | None = None,
        comment: str | None = None,
    ) -> AgentQueueTask | None:
        return self._decide(
            task_id,
            approval_ids=approval_ids,
            decision="approved",
            decided_by=decided_by,
            comment=comment,
        )

    def reject(
        self,
        task_id: str,
        *,
        approval_ids: list[str],
        decided_by: str | None = None,
        comment: str | None = None,
    ) -> AgentQueueTask | None:
        return self._decide(
            task_id,
            approval_ids=approval_ids,
            decision="rejected",
            decided_by=decided_by,
            comment=comment,
        )

    def recover_incomplete_tasks(self) -> int:
        n = 0
        with self._lk:
            ts = datetime.now(timezone.utc)
            new_lst: list[AgentQueueTask] = []
            for x in self._lst:
                if x.status == "running":
                    new_lst.append(
                        x.model_copy(
                            update={
                                "status": "queued",
                                "updated_at": ts,
                                "error": x.error or "recovered_after_restart",
                            }
                        )
                    )
                    n += 1
                    continue
                new_lst.append(x)
            self._lst = new_lst
            if n > 0:
                self._save_locked()
        return n

    def _decide(
        self,
        task_id: str,
        *,
        approval_ids: list[str],
        decision: str,
        decided_by: str | None,
        comment: str | None,
    ) -> AgentQueueTask | None:
        with self._lk:
            idx = self._index_locked(task_id)
            if idx is None:
                return None
            cur = self._lst[idx]
            if cur.status != "waiting_approval":
                return None

            pend_ids: set[str] = set()
            for ap in cur.approvals:
                if ap.status == "pending":
                    pend_ids.add(ap.id)
            if approval_ids:
                s = set(approval_ids)
                pend_ids = pend_ids & s
            if len(pend_ids) == 0:
                return cur.model_copy(deep=True)

            ts = datetime.now(timezone.utc)
            item_ids: list[str] = []
            apps: list[AgentApprovalRequest] = []
            for ap in cur.approvals:
                if ap.id in pend_ids and ap.status == "pending":
                    item_ids.append(ap.item_id)
                    apps.append(
                        ap.model_copy(
                            update={
                                "status": decision,
                                "decided_at": ts,
                                "decided_by": decided_by,
                                "comment": comment,
                            }
                        )
                    )
                    continue
                apps.append(ap)

            payload = cur.payload.model_copy(deep=True)
            if decision == "approved":
                payload.approved_actions = self._dedupe_actions(payload.approved_actions + item_ids)
                payload.rejected_actions = [x for x in payload.rejected_actions if x not in item_ids]
            else:
                payload.rejected_actions = self._dedupe_actions(payload.rejected_actions + item_ids)
                payload.approved_actions = [x for x in payload.approved_actions if x not in item_ids]

            has_pending = False
            for ap in apps:
                if ap.status == "pending":
                    has_pending = True
                    break
            new_st = "waiting_approval" if has_pending else "queued"
            rc = cur.resume_count
            if not has_pending:
                rc += 1
            upd = cur.model_copy(
                update={
                    "status": new_st,
                    "updated_at": ts,
                    "completed_at": None,
                    "payload": payload,
                    "approvals": apps,
                    "resume_count": rc,
                    "error": None,
                }
            )
            self._lst[idx] = upd
            self._save_locked()
            return upd.model_copy(deep=True)

    def _index_locked(self, task_id: str) -> int | None:
        i = 0
        while i < len(self._lst):
            if self._lst[i].id == task_id:
                return i
            i += 1
        return None

    @staticmethod
    def _dedupe_actions(arr: list[str]) -> list[str]:
        res: list[str] = []
        seen: set[str] = set()
        for s in arr:
            v = str(s or "").strip()
            if v == "" or v in seen:
                continue
            seen.add(v)
            res.append(v)
        return res

    @staticmethod
    def _merge_approvals_locked(
        existing: list[AgentApprovalRequest],
        incoming: list[AgentApprovalRequest],
    ) -> list[AgentApprovalRequest]:
        merged: dict[str, AgentApprovalRequest] = {}
        for ap in existing:
            merged[ap.id] = ap
        for ap in incoming:
            merged[ap.id] = ap
        return list(merged.values())

    def _load(self) -> None:
        if not self._fp.exists():
            return
        try:
            body = json.loads(self._fp.read_text(encoding="utf-8"))
            raw = body.get("items", [])
            self._lst = []
            for it in raw:
                if isinstance(it, dict):
                    self._lst.append(AgentQueueTask.model_validate(it))
        except Exception:
            self._lst = []

    def _save_locked(self) -> None:
        self._fp.parent.mkdir(parents=True, exist_ok=True)
        payload = {"items": [x.model_dump(mode="json") for x in self._lst[-500:]]}
        self._fp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


agent_queue_store = AgentQueueStore()
