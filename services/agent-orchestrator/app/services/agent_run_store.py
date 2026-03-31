from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.schemas.workflow import (
    AgentApprovalRequest,
    AgentMemorySnapshot,
    AgentPlanItem,
    AgentRunRecord,
    AgentRunRequestSnapshot,
    AgentStep,
    HealthDataCapsule,
    HealthGraphSnapshot,
    HybridCareStage,
    ReasoningCard,
    SpecialistDigitalTwin,
    AgentToolExecution,
    WorkflowOutput,
    WorkflowRequest,
    WorkflowType,
)


class AgentRunStore:
    def __init__(self, fp: Path | None = None) -> None:
        self._lst: list[AgentRunRecord] = []
        self._cache: dict[str, WorkflowRequest] = {}
        p = fp or (Path(__file__).resolve().parents[2] / "data" / "agent_runs.json")
        self._fp = p
        self._load()

    def start(
        self,
        req: WorkflowRequest,
        *,
        workflow_type: WorkflowType,
        runtime_engine: str,
        agent_goal: str | None,
        agent_mode: str,
        plan: list[AgentPlanItem],
        memory: AgentMemorySnapshot | None,
    ) -> AgentRunRecord:
        ts = datetime.now(timezone.utc)
        rid = str(uuid.uuid4())
        rec = AgentRunRecord(
            id=rid,
            status="running",
            workflow_type=workflow_type,
            runtime_engine=runtime_engine,
            request=self._snapshot_request(req, workflow_type),
            patient_id=req.patient_id,
            bed_no=req.bed_no,
            conversation_id=req.conversation_id,
            agent_goal=agent_goal,
            agent_mode=agent_mode,
            plan=plan,
            memory=memory,
            retry_available=True,
            created_at=ts,
            updated_at=ts,
        )
        self._lst.append(rec)
        self._cache[rid] = req.model_copy(deep=True)
        self._save()
        return rec

    def get(self, rid: str) -> AgentRunRecord | None:
        for x in self._lst:
            if x.id == rid:
                return x
        return None

    def list(
        self,
        *,
        patient_id: str | None = None,
        conversation_id: str | None = None,
        status: str | None = None,
        workflow_type: WorkflowType | None = None,
        limit: int = 50,
    ) -> list[AgentRunRecord]:
        arr = list(reversed(self._lst))
        if patient_id:
            arr = [x for x in arr if x.patient_id == patient_id]
        if conversation_id:
            arr = [x for x in arr if x.conversation_id == conversation_id]
        if status:
            arr = [x for x in arr if x.status == status]
        if workflow_type:
            arr = [x for x in arr if x.workflow_type == workflow_type]
        return arr[:limit]

    def update(
        self,
        rid: str,
        *,
        status: str | None = None,
        runtime_engine: str | None = None,
        patient_id: str | None = None,
        patient_name: str | None = None,
        bed_no: str | None = None,
        summary: str | None = None,
        agent_goal: str | None = None,
        agent_mode: str | None = None,
        plan: list[AgentPlanItem] | None = None,
        memory: AgentMemorySnapshot | None = None,
        artifacts: list | None = None,
        specialist_profiles: list[SpecialistDigitalTwin] | None = None,
        hybrid_care_path: list[HybridCareStage] | None = None,
        data_capsule: HealthDataCapsule | None = None,
        health_graph: HealthGraphSnapshot | None = None,
        reasoning_cards: list[ReasoningCard] | None = None,
        next_actions: list[str] | None = None,
        steps: list[AgentStep] | None = None,
        tool_executions: list[AgentToolExecution] | None = None,
        pending_approvals: list[AgentApprovalRequest] | None = None,
        retry_available: bool | None = None,
        error: str | None = None,
    ) -> AgentRunRecord | None:
        idx = self._index(rid)
        if idx is None:
            return None

        cur = self._lst[idx]
        ts = datetime.now(timezone.utc)
        upd: dict[str, object] = {"updated_at": ts}
        if status is not None:
            upd["status"] = status
            if status in {"completed", "failed"}:
                upd["completed_at"] = ts
        if runtime_engine is not None:
            upd["runtime_engine"] = runtime_engine
        if patient_id is not None:
            upd["patient_id"] = patient_id
        if patient_name is not None:
            upd["patient_name"] = patient_name
        if bed_no is not None:
            upd["bed_no"] = bed_no
        if summary is not None:
            upd["summary"] = summary
        if agent_goal is not None:
            upd["agent_goal"] = agent_goal
        if agent_mode is not None:
            upd["agent_mode"] = agent_mode
        if plan is not None:
            upd["plan"] = plan
        if memory is not None:
            upd["memory"] = memory
        if artifacts is not None:
            upd["artifacts"] = artifacts
        if specialist_profiles is not None:
            upd["specialist_profiles"] = specialist_profiles
        if hybrid_care_path is not None:
            upd["hybrid_care_path"] = hybrid_care_path
        if data_capsule is not None:
            upd["data_capsule"] = data_capsule
        if health_graph is not None:
            upd["health_graph"] = health_graph
        if reasoning_cards is not None:
            upd["reasoning_cards"] = reasoning_cards
        if next_actions is not None:
            upd["next_actions"] = next_actions
        if steps is not None:
            upd["steps"] = steps
        if tool_executions is not None:
            upd["tool_executions"] = tool_executions
        if pending_approvals is not None:
            upd["pending_approvals"] = pending_approvals
        if retry_available is not None:
            upd["retry_available"] = retry_available
        if error is not None:
            upd["error"] = error

        rec = cur.model_copy(update=upd)
        self._lst[idx] = rec
        self._save()
        return rec

    def complete(
        self,
        rid: str,
        out: WorkflowOutput,
        *,
        tool_executions: list[AgentToolExecution],
        pending_approvals: list[AgentApprovalRequest] | None = None,
    ) -> AgentRunRecord | None:
        pa = pending_approvals if pending_approvals is not None else out.pending_approvals
        return self.update(
            rid,
            status="completed",
            runtime_engine=out.runtime_engine,
            patient_id=out.patient_id,
            patient_name=out.patient_name,
            bed_no=out.bed_no,
            summary=out.summary,
            agent_goal=out.agent_goal,
            agent_mode=out.agent_mode,
            plan=out.plan,
            memory=out.memory,
            artifacts=out.artifacts,
            specialist_profiles=out.specialist_profiles,
            hybrid_care_path=out.hybrid_care_path,
            data_capsule=out.data_capsule,
            health_graph=out.health_graph,
            reasoning_cards=out.reasoning_cards,
            next_actions=out.next_actions,
            steps=out.steps,
            tool_executions=tool_executions,
            pending_approvals=pa,
            retry_available=rid in self._cache,
            error=None,
        )

    def wait_for_approval(
        self,
        rid: str,
        out: WorkflowOutput,
        *,
        tool_executions: list[AgentToolExecution],
    ) -> AgentRunRecord | None:
        return self.update(
            rid,
            status="waiting_approval",
            runtime_engine=out.runtime_engine,
            patient_id=out.patient_id,
            patient_name=out.patient_name,
            bed_no=out.bed_no,
            summary=out.summary,
            agent_goal=out.agent_goal,
            agent_mode=out.agent_mode,
            plan=out.plan,
            memory=out.memory,
            artifacts=out.artifacts,
            specialist_profiles=out.specialist_profiles,
            hybrid_care_path=out.hybrid_care_path,
            data_capsule=out.data_capsule,
            health_graph=out.health_graph,
            reasoning_cards=out.reasoning_cards,
            next_actions=out.next_actions,
            steps=out.steps,
            tool_executions=tool_executions,
            pending_approvals=out.pending_approvals,
            retry_available=rid in self._cache,
            error=None,
        )

    def fail(
        self,
        rid: str,
        *,
        error: str,
        runtime_engine: str | None = None,
        steps: list[AgentStep] | None = None,
        plan: list[AgentPlanItem] | None = None,
        tool_executions: list[AgentToolExecution] | None = None,
    ) -> AgentRunRecord | None:
        return self.update(
            rid,
            status="failed",
            runtime_engine=runtime_engine,
            steps=steps,
            plan=plan,
            tool_executions=tool_executions,
            retry_available=rid in self._cache,
            error=error,
        )

    def retry_request(self, rid: str) -> WorkflowRequest | None:
        req = self._cache.get(rid)
        if req is None:
            return None
        return req.model_copy(deep=True)

    def has_retry_request(self, rid: str) -> bool:
        return rid in self._cache

    def _index(self, rid: str) -> int | None:
        i = 0
        while i < len(self._lst):
            if self._lst[i].id == rid:
                return i
            i += 1
        return None

    @staticmethod
    def _snapshot_request(req: WorkflowRequest, wt: WorkflowType) -> AgentRunRequestSnapshot:
        return AgentRunRequestSnapshot(
            workflow_type=wt,
            patient_id=req.patient_id,
            conversation_id=req.conversation_id,
            department_id=req.department_id,
            bed_no=req.bed_no,
            user_input=req.user_input,
            mission_title=req.mission_title,
            success_criteria=list(req.success_criteria),
            operator_notes=req.operator_notes,
            requested_by=req.requested_by,
            agent_mode=req.agent_mode,
            execution_profile=req.execution_profile,
            attachments_count=len(req.attachments),
            approved_actions=list(req.approved_actions),
            rejected_actions=list(req.rejected_actions),
        )

    def _load(self) -> None:
        if not self._fp.exists():
            return
        try:
            body = json.loads(self._fp.read_text(encoding="utf-8"))
            raw = body.get("items", [])
            self._lst = []
            for it in raw:
                if isinstance(it, dict):
                    self._lst.append(AgentRunRecord.model_validate({**it, "retry_available": False}))
        except Exception:
            self._lst = []

    def _save(self) -> None:
        self._fp.parent.mkdir(parents=True, exist_ok=True)
        payload = {"items": [x.model_dump(mode="json") for x in self._lst[-500:]]}
        self._fp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


agent_run_store = AgentRunStore()
