from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.schemas.workflow import AgentMemorySnapshot, WorkflowOutput, WorkflowRequest
from app.services.history_store import workflow_history_store


class AgentMemoryStore:
    def __init__(self) -> None:
        self._fp = Path(__file__).resolve().parents[2] / "data" / "agent_memory.json"
        self._st: dict[str, dict[str, dict[str, Any]]] = {
            "patients": {},
            "conversations": {},
            "users": {},
        }
        self._load()

    def snapshot(
        self,
        *,
        patient_id: str | None = None,
        conversation_id: str | None = None,
        requested_by: str | None = None,
        user_input: str | None = None,
    ) -> AgentMemorySnapshot:
        pk = str(patient_id or "").strip()
        ck = str(conversation_id or "").strip()
        uk = str(requested_by or "").strip()

        p_ent = {}
        if pk:
            p_ent = self._st["patients"].get(pk, {})
        c_ent = {}
        if ck:
            c_ent = self._st["conversations"].get(ck, {})
        u_ent = {}
        if uk:
            u_ent = self._st["users"].get(uk, {})

        lim = settings.agent_memory_recall_limit
        if lim < 4:
            lim = 4
        hist = workflow_history_store.list(
            patient_id=pk or None,
            conversation_id=ck or None,
            requested_by=uk or None,
            limit=lim,
        )

        sum_parts: list[str] = []
        stored = c_ent.get("conversation_summary")
        ss = str(stored or "").strip()
        if ss:
            sum_parts.append(ss)
        rev = list(reversed(hist))
        for h in rev:
            s = str(h.summary or "").strip()
            if s:
                sum_parts.append(s)

        facts_raw: list[Any] = []
        facts_raw.append(p_ent.get("patient_facts"))
        facts_raw.append(c_ent.get("patient_facts"))
        for h in hist:
            arr = h.findings[:3]
            for f in arr:
                facts_raw.append(f)
        p_facts = self._rank(user_input, self._merge(*facts_raw), lim=8)

        task_raw: list[Any] = []
        task_raw.append(p_ent.get("unresolved_tasks"))
        task_raw.append(c_ent.get("unresolved_tasks"))
        for h in hist:
            recs = h.recommendations[:3]
            for rc in recs:
                if isinstance(rc, dict):
                    t = rc.get("title")
                    task_raw.append(str(t or "").strip())
        tasks = self._rank(user_input, self._merge(*task_raw), lim=8)

        act_raw: list[Any] = []
        act_raw.append(c_ent.get("last_actions"))
        act_raw.append(p_ent.get("last_actions"))
        for h in hist:
            arts = h.artifacts[:3]
            for a in arts:
                ttl = getattr(a, "title", "")
                if ttl and ttl.strip():
                    act_raw.append(ttl)
        acts = self._rank(user_input, self._merge(*act_raw), lim=6)

        prefs = self._merge(u_ent.get("preferences"), c_ent.get("user_preferences"))
        prefs = prefs[:6]

        flt = [x for x in sum_parts if x]
        flt = flt[:3]
        summ = "；".join(flt)
        summ = summ[:360]
        return AgentMemorySnapshot(
            conversation_summary=summ,
            patient_facts=p_facts,
            unresolved_tasks=tasks,
            last_actions=acts,
            user_preferences=prefs,
        )

    def remember(self, req: WorkflowRequest, out: WorkflowOutput) -> AgentMemorySnapshot:
        pid = out.patient_id
        if not pid:
            pid = req.patient_id
        snap = self.snapshot(
            patient_id=pid,
            conversation_id=req.conversation_id,
            requested_by=req.requested_by,
            user_input=req.user_input,
        )

        pk = out.patient_id
        if not pk:
            pk = req.patient_id
        pk = str(pk or "").strip()
        ck = str(req.conversation_id or "").strip()
        uk = str(req.requested_by or "").strip()

        if pk:
            rec_titles: list[str] = []
            for r in out.recommendations:
                if isinstance(r, dict):
                    t = r.get("title")
                    rec_titles.append(str(t or "").strip())
            art_titles: list[str] = []
            for a in out.artifacts:
                if a.title.strip():
                    art_titles.append(a.title)
            self._st["patients"][pk] = {
                "patient_facts": self._merge(
                    snap.patient_facts,
                    out.findings,
                    self._get_facts(out),
                )[:12],
                "unresolved_tasks": self._merge(
                    snap.unresolved_tasks,
                    rec_titles,
                    out.next_actions,
                )[:12],
                "last_actions": self._merge(snap.last_actions, art_titles)[:8],
            }

        if ck:
            rec_titles2: list[str] = []
            for r in out.recommendations:
                if isinstance(r, dict):
                    t = r.get("title")
                    rec_titles2.append(str(t or "").strip())
            art_titles2: list[str] = []
            for a in out.artifacts:
                if a.title.strip():
                    art_titles2.append(a.title)
            self._st["conversations"][ck] = {
                "conversation_summary": out.summary[:300],
                "patient_facts": self._merge(snap.patient_facts, out.findings)[:12],
                "unresolved_tasks": self._merge(
                    snap.unresolved_tasks,
                    rec_titles2,
                    out.next_actions,
                )[:12],
                "last_actions": self._merge(snap.last_actions, art_titles2)[:8],
                "user_preferences": self._get_prefs(req),
            }

        if uk:
            old = self._st["users"].get(uk, {})
            old_prefs = old.get("preferences")
            self._st["users"][uk] = {
                "preferences": self._merge(
                    old_prefs,
                    snap.user_preferences,
                    self._get_prefs(req),
                )[:8]
            }

        self._save()
        return self.snapshot(
            patient_id=pid,
            conversation_id=req.conversation_id,
            requested_by=req.requested_by,
            user_input=req.user_input,
        )

    @staticmethod
    def _merge(*args: Any) -> list[str]:
        out: list[str] = []
        dup: set[str] = set()
        for g in args:
            if not g:
                continue
            lst = g
            if not isinstance(g, list):
                lst = [g]
            for x in lst:
                s = str(x or "").strip()
                if s == "":
                    continue
                if s in dup:
                    continue
                dup.add(s)
                out.append(s)
        return out

    @classmethod
    def _kw(cls, txt: str | None) -> list[str]:
        s = str(txt or "").strip().lower()
        if s == "":
            return []

        out: list[str] = []
        dup: set[str] = set()
        pat = r"[a-z0-9_-]+|[\u4e00-\u9fff]+"
        toks = re.findall(pat, s)
        for tk in toks:
            n = len(tk)
            has_digit = False
            for c in tk:
                if c.isdigit():
                    has_digit = True
                    break
            if n <= 1 and not has_digit:
                continue
            frags = [tk]
            is_cn = re.search(r"[\u4e00-\u9fff]", tk)
            if n > 4 and is_cn:
                frags = []
                i = 0
                while i < n - 1:
                    frags.append(tk[i : i + 2])
                    i += 1
            for fr in frags:
                p = fr.strip()
                has_d = False
                for c in p:
                    if c.isdigit():
                        has_d = True
                        break
                if len(p) <= 1 and not has_d:
                    continue
                if p in dup:
                    continue
                dup.add(p)
                out.append(p)
        return out

    @classmethod
    def _rank(cls, q: str | None, arr: list[str], *, lim: int) -> list[str]:
        if len(arr) == 0:
            return []

        kws = cls._kw(q)
        if len(kws) == 0:
            return arr[:lim]

        scored: list[tuple[int, int, str]] = []
        idx = 0
        while idx < len(arr):
            x = arr[idx]
            hay = str(x or "").strip().lower()
            sc = 0
            for kw in kws:
                if kw in hay:
                    has_d = False
                    for c in kw:
                        if c.isdigit():
                            has_d = True
                            break
                    if has_d:
                        sc += 3
                    else:
                        sc += 1
            scored.append((sc, -idx, x))
            idx += 1

        scored.sort(reverse=True)
        ret = []
        for _, _, v in scored:
            ret.append(v)
        return ret[:lim]

    @staticmethod
    def _get_prefs(req: WorkflowRequest) -> list[str]:
        q = str(req.user_input or "").strip()
        lst: list[str] = []
        has_auto = "自动" in q
        has_loop = "闭环" in q
        if has_auto or has_loop:
            lst.append("偏好自动闭环处理")
        has_doc = "文书" in q
        has_rec = "记录" in q
        if has_doc or has_rec:
            lst.append("偏好自动生成文书草稿")
        if "交班" in q:
            lst.append("偏好交班联动")
        has_notify = "通知" in q
        has_collab = "协作" in q
        if has_notify or has_collab:
            lst.append("偏好主动协作提醒")
        return lst

    @staticmethod
    def _get_facts(out: WorkflowOutput) -> list[str]:
        lst: list[str] = []
        nm = out.patient_name
        bed = out.bed_no
        if nm and bed:
            lst.append(f"{bed}床 {nm}")
        arr = out.findings[:6]
        for f in arr:
            s = str(f or "").strip()
            if s:
                lst.append(s)
        return lst

    def _load(self) -> None:
        exist = self._fp.exists()
        if not exist:
            return
        try:
            txt = self._fp.read_text(encoding="utf-8")
            obj = json.loads(txt)
            ok = isinstance(obj, dict)
            if ok:
                for k in self._st:
                    v = obj.get(k)
                    if isinstance(v, dict):
                        self._st[k] = v
        except Exception:
            self._st = {"patients": {}, "conversations": {}, "users": {}}

    def _save(self) -> None:
        self._fp.parent.mkdir(parents=True, exist_ok=True)
        s = json.dumps(self._st, ensure_ascii=False, indent=2)
        self._fp.write_text(s, encoding="utf-8")


agent_memory_store = AgentMemoryStore()
