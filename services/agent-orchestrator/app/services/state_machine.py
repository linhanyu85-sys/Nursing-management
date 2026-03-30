from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import settings
from app.schemas.workflow import AgentStep, WorkflowOutput, WorkflowRequest, WorkflowType
from app.services.agentic_orchestrator import agentic_orchestrator, is_autonomous_request
from app.services.history_store import workflow_history_store
from app.services.llm_client import bailian_refine


class AgentStateMachine:
    HANDOVER_TOKENS = ("交班", "交接班", "handover", "shift")
    DOCUMENT_TOKENS = ("文书", "草稿", "护理记录", "病程记录", "document", "draft")
    RECOMMEND_TOKENS = ("建议", "优先级", "风险", "上报", "升级", "recommend", "escalate", "triage")
    WARD_TOKENS = ("病区", "全病区", "全部患者", "所有患者", "整体", "排序", "排优先级")
    GLOBAL_SCOPE_TOKENS = ("整个数据库", "全库", "所有床位", "全部床位", "全体患者", "数据库里所有患者", "全院")
    COLLAB_TOKENS = (
        "发给",
        "发送给",
        "通知",
        "联系",
        "协作",
        "转告",
        "值班医生",
        "责任医生",
        "护士长",
        "住院医",
        "send",
        "notify",
        "doctor on duty",
    )
    CN_DIGIT_MAP: dict[str, int] = {
        "零": 0,
        "〇": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    CN_UNIT_MAP: dict[str, int] = {
        "十": 10,
        "百": 100,
    }
    MOJIBAKE_MARKERS: tuple[str, ...] = ("鍖", "鐥", "鎶", "璇", "闂", "锟", "Ã", "�", "?")

    @staticmethod
    def _ensure_question(summary: str, question: str | None) -> str:
        s = (summary or "").strip()
        q = (question or "").strip()
        if s:
            return s
        return q

    @staticmethod
    def _llm_unavailable(text: str | None) -> bool:
        t = (text or "").strip()
        if not t:
            return True
        markers = (
            "本地模型当前不可用",
            "请先启动本地中文模型服务",
            "当前模型调用失败",
            "禁止云端回退",
        )
        return any(m in t for m in markers)

    @staticmethod
    def _normalize_user_id(value: str | None) -> str:
        raw = (value or "").strip()
        if not raw:
            return "u_linmeili"
        if raw.startswith("u_"):
            return raw
        return f"u_{raw}"

    @classmethod
    def _parse_cn_number(cls, token: str) -> int | None:
        raw = (token or "").strip()
        if not raw:
            return None
        raw = raw.removeprefix("第")
        if not raw:
            return None
        if raw.isdigit():
            value = int(raw)
            return value if 1 <= value <= 199 else None
        if any(ch not in cls.CN_DIGIT_MAP and ch not in cls.CN_UNIT_MAP for ch in raw):
            return None
        if not any(ch in cls.CN_UNIT_MAP for ch in raw):
            digits: list[str] = []
            for ch in raw:
                if ch not in cls.CN_DIGIT_MAP:
                    return None
                digits.append(str(cls.CN_DIGIT_MAP[ch]))
            if not digits:
                return None
            value = int("".join(digits))
            return value if 1 <= value <= 199 else None

        total = 0
        current = 0
        for ch in raw:
            if ch in cls.CN_DIGIT_MAP:
                current = cls.CN_DIGIT_MAP[ch]
                continue
            unit = cls.CN_UNIT_MAP.get(ch)
            if unit is None:
                return None
            if current == 0:
                current = 1
            total += current * unit
            current = 0
        total += current
        return total if 1 <= total <= 199 else None

    @staticmethod
    def _parse_bed_no(raw: str) -> str | None:
        value = AgentStateMachine._parse_cn_number(raw)
        if value is None:
            return None
        return str(value)

    @classmethod
    def _bed_sort_key(cls, bed_no: str) -> tuple[int, int, str]:
        value = cls._parse_cn_number(str(bed_no or "").strip())
        if value is None:
            return (1, 9999, str(bed_no or ""))
        return (0, value, str(bed_no or ""))

    @classmethod
    def _extract_bed_nos_from_rows(cls, rows: Any) -> list[str]:
        if not isinstance(rows, list):
            return []
        out: list[str] = []
        seen: set[str] = set()
        for item in rows:
            if not isinstance(item, dict):
                continue
            raw = str(item.get("bed_no") or "").strip()
            if not raw:
                continue
            bed = cls._parse_bed_no(raw) or raw
            if bed and bed not in seen:
                seen.add(bed)
                out.append(bed)
        out.sort(key=cls._bed_sort_key)
        return out

    @classmethod
    def _resolve_nearest_bed(
        cls,
        requested_bed: str,
        available_beds: list[str],
        *,
        max_distance: int = 2,
    ) -> str | None:
        requested = cls._parse_cn_number(str(requested_bed or "").strip())
        if requested is None:
            return None
        if not available_beds:
            return None

        best: tuple[int, int, str] | None = None
        for bed in available_beds:
            normalized = str(bed or "").strip()
            parsed = cls._parse_cn_number(normalized)
            if parsed is None:
                continue
            diff = abs(parsed - requested)
            candidate = (diff, parsed, normalized)
            if best is None or candidate < best:
                best = candidate
                if diff == 0:
                    break
        if best is None:
            return None
        if best[0] > max_distance:
            return None
        return best[2]

    @staticmethod
    def _extract_beds(text: str | None) -> list[str]:
        q = (text or "").strip()
        if not q:
            return []
        out: list[str] = []
        seen: set[str] = set()

        def add(raw: str) -> None:
            bed = AgentStateMachine._parse_bed_no(raw)
            if not bed:
                return
            if bed not in seen:
                seen.add(bed)
                out.append(bed)

        patterns = (
            r"(?<!\d)(\d{1,3})\s*(?:床|号床|床位)",
            r"(?:第)?([零〇一二两三四五六七八九十百]{1,5})\s*(?:床|号床|床位)",
            r"\bbed\s*(\d{1,3})\b",
            r"\b(\d{1,3})\s*bed\b",
        )
        for pattern in patterns:
            for match in re.finditer(pattern, q, flags=re.IGNORECASE):
                add(match.group(1))
        if out:
            return out

        has_patient_signal = any(
            token in q.lower()
            for token in (
                "bed",
                "patient",
                "ward",
                "nurse",
                "doctor",
                "患者",
                "病人",
                "床",
                "病区",
                "护理",
                "交班",
                "文书",
                "记录",
                "建议",
                "情况",
            )
        )
        if has_patient_signal:
            for match in re.finditer(r"(?<!\d)(\d{1,3})(?!\d)", q):
                add(match.group(1))
        if out:
            return out

        # Fallback for garbled speech text where Chinese tokens are lost
        # but bed numbers survive (e.g. "????12????").
        mojibake_score = sum(q.count(marker) for marker in AgentStateMachine.MOJIBAKE_MARKERS)
        if mojibake_score >= 2:
            numeric_tokens: list[str] = []
            seen_num: set[str] = set()
            for match in re.finditer(r"(?<!\d)(\d{1,3})(?!\d)", q):
                token = match.group(1)
                if token in seen_num:
                    continue
                seen_num.add(token)
                numeric_tokens.append(token)
            if len(numeric_tokens) == 1:
                add(numeric_tokens[0])
        return out

    @classmethod
    def _is_ward_scope(cls, question: str | None, beds: list[str] | None = None) -> bool:
        q = (question or "").strip()
        low = q.lower()
        if cls._is_global_scope(q):
            return True
        if beds and len(beds) >= 2:
            return True
        # When user already specified one bed, keep single-patient scope unless
        # there is an explicit ward/global phrase.
        if beds and len(beds) == 1:
            if any(token in low for token in ("all beds", "all patients", "ward")):
                return True
            return any(token in q for token in cls.WARD_TOKENS)
        if any(token in low for token in ("all beds", "all patients", "ward", "priority", "triage")):
            return True
        return any(token in q for token in cls.WARD_TOKENS)

    @classmethod
    def _is_global_scope(cls, question: str | None) -> bool:
        q = (question or "").strip()
        if not q:
            return False
        low = q.lower()
        if any(token in low for token in ("entire database", "whole database", "all database", "all beds", "all patients")):
            return True
        return any(token in q for token in cls.GLOBAL_SCOPE_TOKENS)

    @staticmethod
    def _risk_score(context: dict[str, Any]) -> int:
        risk_tags = context.get("risk_tags") if isinstance(context.get("risk_tags"), list) else []
        pending_tasks = context.get("pending_tasks") if isinstance(context.get("pending_tasks"), list) else []
        observations = context.get("latest_observations") if isinstance(context.get("latest_observations"), list) else []

        abnormal = 0
        for obs in observations[:8]:
            if not isinstance(obs, dict):
                continue
            flag = str(obs.get("abnormal_flag") or "").lower()
            if flag and flag not in {"normal", "ok", "none"}:
                abnormal += 1
        return len(risk_tags) * 2 + len(pending_tasks) + abnormal

    @staticmethod
    def _normalize_recommendations(raw: Any, fallback: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        if isinstance(raw, list):
            for item in raw[:8]:
                if isinstance(item, dict):
                    title = str(item.get("title") or item.get("action") or "").strip()
                    if title:
                        output.append({"title": title, "priority": int(item.get("priority", 2) or 2)})
                else:
                    title = str(item).strip()
                    if title:
                        output.append({"title": title, "priority": 2})
        if output:
            return output
        return fallback or [{"title": "请先人工复核后执行。", "priority": 2}]

    async def _call_json(
        self,
        method: str,
        url: str,
        *,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout: float = 12.0,
    ) -> Any | None:
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                resp = await client.request(method=method, url=url, json=payload, params=params)
            if resp.status_code >= 400:
                return None
            return resp.json()
        except Exception:
            return None

    async def _list_available_beds(self, department_id: str | None = None) -> list[str]:
        dep = (department_id or "").strip() or settings.default_department_id
        rows = await self._call_json("GET", f"{settings.patient_context_service_url}/wards/{dep}/beds", timeout=10)
        beds = self._extract_bed_nos_from_rows(rows)
        if beds:
            return beds

        rows = await self._call_json("GET", f"{settings.patient_context_service_url}/wards/all-beds", timeout=10)
        beds = self._extract_bed_nos_from_rows(rows)
        if beds:
            return beds

        rows = await self._call_json("GET", f"{settings.patient_context_service_url}/wards/_all_beds", timeout=10)
        return self._extract_bed_nos_from_rows(rows)

    async def _write_audit(self, action: str, resource_id: str | None, detail: dict[str, Any], user_id: str | None) -> None:
        await self._call_json(
            "POST",
            f"{settings.audit_service_url}/audit/log",
            payload={
                "user_id": user_id,
                "action": action,
                "resource_type": "workflow",
                "resource_id": resource_id,
                "detail": detail,
            },
            timeout=6,
        )

    async def _fetch_contexts(self, payload: WorkflowRequest, beds: list[str], allow_ward_fallback: bool) -> list[dict[str, Any]]:
        contexts: list[dict[str, Any]] = []
        seen_patient_ids: set[str] = set()
        requested_by = self._normalize_user_id(payload.requested_by)
        available_bed_nos_cache: list[str] | None = None

        async with httpx.AsyncClient(timeout=httpx.Timeout(28, connect=6), trust_env=False) as client:
            async def ensure_available_beds() -> list[str]:
                nonlocal available_bed_nos_cache
                if available_bed_nos_cache is not None:
                    return available_bed_nos_cache

                dep = (payload.department_id or "").strip() or settings.default_department_id
                try:
                    ward_resp = await client.get(f"{settings.patient_context_service_url}/wards/{dep}/beds")
                    ward_rows = ward_resp.json() if ward_resp.status_code < 400 else []
                except Exception:
                    ward_rows = []

                available_bed_nos_cache = self._extract_bed_nos_from_rows(ward_rows)
                if available_bed_nos_cache:
                    return available_bed_nos_cache

                try:
                    all_resp = await client.get(f"{settings.patient_context_service_url}/wards/all-beds")
                    all_rows = all_resp.json() if all_resp.status_code < 400 else []
                except Exception:
                    all_rows = []
                available_bed_nos_cache = self._extract_bed_nos_from_rows(all_rows)
                if available_bed_nos_cache:
                    return available_bed_nos_cache

                try:
                    all_resp = await client.get(f"{settings.patient_context_service_url}/wards/_all_beds")
                    all_rows = all_resp.json() if all_resp.status_code < 400 else []
                except Exception:
                    all_rows = []
                available_bed_nos_cache = self._extract_bed_nos_from_rows(all_rows)
                return available_bed_nos_cache

            for bed in beds:
                requested_bed = str(bed or "").strip()
                resolved_bed = requested_bed
                corrected_bed = False
                params: dict[str, Any] = {}
                if payload.department_id:
                    params["department_id"] = payload.department_id
                params["requested_by"] = requested_by
                try:
                    resp = await client.get(f"{settings.patient_context_service_url}/beds/{resolved_bed}/context", params=params)
                    if resp.status_code >= 400 and payload.department_id:
                        resp = await client.get(
                            f"{settings.patient_context_service_url}/beds/{resolved_bed}/context",
                            params={"requested_by": requested_by},
                        )

                    if resp.status_code >= 400 and requested_bed:
                        available_beds = await ensure_available_beds()
                        nearest_bed = self._resolve_nearest_bed(requested_bed, available_beds)
                        if nearest_bed and nearest_bed != requested_bed:
                            resolved_bed = nearest_bed
                            corrected_bed = True
                            resp = await client.get(
                                f"{settings.patient_context_service_url}/beds/{resolved_bed}/context",
                                params=params,
                            )
                            if resp.status_code >= 400 and payload.department_id:
                                resp = await client.get(
                                    f"{settings.patient_context_service_url}/beds/{resolved_bed}/context",
                                    params={"requested_by": requested_by},
                                )
                    if resp.status_code >= 400:
                        continue
                    body = resp.json()
                except Exception:
                    continue

                if not isinstance(body, dict):
                    continue
                if requested_bed:
                    body["_requested_bed_no"] = requested_bed
                if resolved_bed:
                    body["_resolved_bed_no"] = resolved_bed
                if corrected_bed and requested_bed and resolved_bed:
                    body["_bed_no_corrected"] = True
                    body["_bed_no_correction_note"] = (
                        f"语音床号 {requested_bed} 未命中，已按最近床位 {resolved_bed} 处理。"
                    )
                pid = str(body.get("patient_id") or "").strip()
                if pid and pid in seen_patient_ids:
                    continue
                contexts.append(body)
                if pid:
                    seen_patient_ids.add(pid)

            if not contexts and payload.patient_id:
                try:
                    resp = await client.get(
                        f"{settings.patient_context_service_url}/patients/{payload.patient_id}/context",
                        params={"requested_by": requested_by},
                    )
                    if resp.status_code < 400:
                        body = resp.json()
                        if isinstance(body, dict):
                            contexts.append(body)
                            pid = str(body.get("patient_id") or "").strip()
                            if pid:
                                seen_patient_ids.add(pid)
                except Exception:
                    pass

            if not contexts and allow_ward_fallback and self._is_ward_scope(payload.user_input, beds):
                is_global_scope = self._is_global_scope(payload.user_input)
                dep = (payload.department_id or "").strip() or settings.default_department_id
                if is_global_scope and dep:
                    try:
                        resp = await client.get(f"{settings.patient_context_service_url}/wards/{dep}/beds")
                        ward_beds = resp.json() if resp.status_code < 400 else []
                    except Exception:
                        ward_beds = []
                elif is_global_scope:
                    try:
                        resp = await client.get(f"{settings.patient_context_service_url}/wards/all-beds")
                        if resp.status_code >= 400:
                            resp = await client.get(f"{settings.patient_context_service_url}/wards/_all_beds")
                        ward_beds = resp.json() if resp.status_code < 400 else []
                    except Exception:
                        ward_beds = []
                else:
                    try:
                        resp = await client.get(f"{settings.patient_context_service_url}/wards/{dep}/beds")
                        ward_beds = resp.json() if resp.status_code < 400 else []
                    except Exception:
                        ward_beds = []

                patient_ids: list[str] = []
                if isinstance(ward_beds, list):
                    for bed in ward_beds[:80]:
                        if not isinstance(bed, dict):
                            continue
                        pid = str(bed.get("current_patient_id") or "").strip()
                        if pid and pid not in seen_patient_ids:
                            patient_ids.append(pid)
                            seen_patient_ids.add(pid)

                sem = asyncio.Semaphore(6)

                async def fetch_one(pid: str) -> dict[str, Any] | None:
                    async with sem:
                        try:
                            r = await client.get(
                                f"{settings.patient_context_service_url}/patients/{pid}/context",
                                params={"requested_by": requested_by},
                            )
                            if r.status_code >= 400:
                                return None
                            b = r.json()
                            return b if isinstance(b, dict) else None
                        except Exception:
                            return None

                fetched = await asyncio.gather(*(fetch_one(pid) for pid in patient_ids), return_exceptions=True)
                for item in fetched:
                    if isinstance(item, dict):
                        contexts.append(item)

        return contexts

    async def route_intent(self, text: str) -> WorkflowType:
        q = text or ""
        low = q.lower()
        if is_autonomous_request(q):
            return WorkflowType.AUTONOMOUS_CARE
        if any(t in low for t in self.HANDOVER_TOKENS) or any(t in q for t in ("交班", "交接班")):
            return WorkflowType.HANDOVER
        if any(t in low for t in self.DOCUMENT_TOKENS) or any(t in q for t in ("文书", "草稿", "护理记录")):
            return WorkflowType.DOCUMENT
        if any(t in low for t in self.RECOMMEND_TOKENS) or any(t in q for t in ("建议", "优先级", "风险", "升级")):
            return WorkflowType.RECOMMENDATION
        return WorkflowType.VOICE_INQUIRY

    async def run(self, payload: WorkflowRequest) -> WorkflowOutput:
        payload.requested_by = self._normalize_user_id(payload.requested_by)
        if payload.workflow_type in {
            WorkflowType.AUTONOMOUS_CARE,
            WorkflowType.HANDOVER,
            WorkflowType.RECOMMENDATION,
            WorkflowType.DOCUMENT,
            WorkflowType.VOICE_INQUIRY,
        }:
            workflow_type = await agentic_orchestrator.route_workflow(payload, self.route_intent)
            payload = payload.model_copy(deep=True)
            payload.workflow_type = workflow_type
            memory = agentic_orchestrator.retrieve_memory(payload)
            plan = await agentic_orchestrator.build_plan(payload, workflow_type, memory)
            output = await agentic_orchestrator.run(
                payload,
                helper=self,
                workflow_type=workflow_type,
                memory=memory,
                plan=plan,
                runtime_engine="state_machine",
            )
            if workflow_type == WorkflowType.AUTONOMOUS_CARE:
                critique = agentic_orchestrator.reflect(payload, output)
                if critique.get("followup_actions"):
                    plan = await agentic_orchestrator.build_plan(
                        payload,
                        WorkflowType.AUTONOMOUS_CARE,
                        memory,
                        critique=critique,
                        existing_plan=output.plan,
                    )
                    output = await agentic_orchestrator.run(
                        payload,
                        helper=self,
                        workflow_type=WorkflowType.AUTONOMOUS_CARE,
                        memory=memory,
                        plan=plan,
                        prior_output=output,
                        runtime_engine="state_machine",
                    )
            output = agentic_orchestrator.finalize(payload, output)
            agentic_orchestrator.persist_finalized_run(output)
        else:
            output = await self._run_voice(payload)
        workflow_history_store.append(payload, output)
        return output

    def _build_context_findings(self, context: dict[str, Any]) -> list[str]:
        findings: list[str] = []
        for obs in context.get("latest_observations", [])[:5]:
            if not isinstance(obs, dict):
                continue
            name = str(obs.get("name") or "").strip()
            value = str(obs.get("value") or "").strip()
            if name and value:
                findings.append(f"{name}={value}")
        findings.extend([str(tag).strip() for tag in context.get("risk_tags", [])[:4] if str(tag).strip()])
        return findings

    @staticmethod
    def _llm_answer_likely_generic(text: str | None) -> bool:
        t = (text or "").strip()
        if len(t) < 8:
            return True
        markers = (
            "未命中具体患者上下文",
            "补充床号",
            "继续直接提问",
            "云模型未配置",
            "模型调用失败",
            "本地模型当前不可用",
            "请先启动本地中文模型服务",
        )
        return any(marker in t for marker in markers)

    @staticmethod
    def _build_single_patient_summary(context: dict[str, Any], bed_no: str | None = None) -> str:
        bed = str(bed_no or context.get("bed_no") or "").strip() or "当前"
        patient_name = str(context.get("patient_name") or context.get("full_name") or "").strip()

        segments: list[str] = [f"已定位到{bed}床"]
        if patient_name:
            segments[0] = f"{segments[0]}（{patient_name}）"
        segments[0] = f"{segments[0]}。"

        diagnoses = [str(item).strip() for item in context.get("diagnoses", []) if str(item).strip()]
        if diagnoses:
            segments.append(f"当前诊断：{'、'.join(diagnoses[:3])}。")

        observations: list[str] = []
        for obs in context.get("latest_observations", [])[:6]:
            if not isinstance(obs, dict):
                continue
            name = str(obs.get("name") or "").strip()
            value = str(obs.get("value") or "").strip()
            if not name or not value:
                continue
            abnormal = str(obs.get("abnormal_flag") or "").strip().lower()
            if abnormal and abnormal not in {"normal", "ok", "none"}:
                observations.insert(0, f"{name} {value}（{abnormal}）")
            else:
                observations.append(f"{name} {value}")
        if observations:
            segments.append(f"重点指标：{'；'.join(observations[:3])}。")

        risk_tags = [str(item).strip() for item in context.get("risk_tags", []) if str(item).strip()]
        if risk_tags:
            segments.append(f"风险标签：{'、'.join(risk_tags[:3])}。")

        tasks = [str(item).strip() for item in context.get("pending_tasks", []) if str(item).strip()]
        if tasks:
            segments.append(f"建议先执行：{'、'.join(tasks[:3])}，并人工复核。")
        else:
            segments.append("建议继续监测关键生命体征，按医嘱处理并人工复核。")
        return "".join(segments)

    async def _dispatch_collaboration(self, payload: WorkflowRequest, source_summary: str) -> str:
        sender = self._normalize_user_id(payload.requested_by)
        patient_id = (payload.patient_id or "").strip() or None

        accounts = await self._call_json(
            "GET",
            f"{settings.collaboration_service_url}/collab/accounts",
            params={"query": "doctor", "exclude_user_id": sender},
            timeout=8,
        )
        if (not isinstance(accounts, list)) or (not accounts):
            accounts = await self._call_json(
                "GET",
                f"{settings.collaboration_service_url}/collab/accounts",
                params={"query": "", "exclude_user_id": sender},
                timeout=8,
            )
            if (not isinstance(accounts, list)) or (not accounts):
                return ""

        target = accounts[0] if isinstance(accounts[0], dict) else {}
        target_user_id = str(target.get("user_id") or target.get("id") or "").strip()
        target_name = str(
            target.get("display_name")
            or target.get("full_name")
            or target.get("username")
            or target.get("account")
            or "值班医生"
        ).strip()
        if not target_user_id:
            return ""

        opened = await self._call_json(
            "POST",
            f"{settings.collaboration_service_url}/collab/direct/open",
            payload={"user_id": sender, "contact_user_id": target_user_id, "patient_id": patient_id},
            timeout=8,
        )
        if not isinstance(opened, dict):
            return ""
        session_id = str(opened.get("id") or opened.get("session_id") or "").strip()
        if not session_id:
            return ""

        sent = await self._call_json(
            "POST",
            f"{settings.collaboration_service_url}/collab/direct/message",
            payload={
                "session_id": session_id,
                "sender_id": sender,
                "content": source_summary[:220],
                "message_type": "text",
                "attachment_refs": [],
            },
            timeout=8,
        )
        if not isinstance(sent, dict):
            return ""
        return f"已发送协作消息给 {target_name}（会话 {session_id[:8]}...）。"

    async def _run_voice(self, payload: WorkflowRequest) -> WorkflowOutput:
        question = (payload.user_input or "").strip()
        beds = self._extract_beds(question)
        if payload.bed_no and payload.bed_no not in beds:
            beds.insert(0, payload.bed_no)

        ward_scope = self._is_ward_scope(question, beds)
        contexts = await self._fetch_contexts(payload, beds, allow_ward_fallback=True)

        summary = ""
        findings: list[str] = []
        recommendations: list[dict[str, Any]] = []
        confidence = 0.7

        if not contexts:
            if beds:
                nearest = self._resolve_nearest_bed(beds[0], await self._list_available_beds(payload.department_id))
                if nearest and nearest != beds[0]:
                    summary = self._ensure_question(
                        f"未找到 {beds[0]} 床患者上下文。你可能在问 {nearest} 床，我可以按 {nearest} 床继续处理。",
                        question,
                    )
                    recommendations = [
                        {"title": f"直接说“查看{nearest}床情况”继续", "priority": 1},
                        {"title": "也可以改为“查看病区高风险患者”", "priority": 2},
                    ]
                else:
                    summary = self._ensure_question(f"未找到 {beds[0]} 床患者上下文，请确认床号或科室后重试。", question)
                    recommendations = [
                        {"title": "确认床号后重试", "priority": 1},
                        {"title": "也可以直接说“查看病区高风险患者”", "priority": 2},
                    ]
                confidence = 0.42
            else:
                summary = self._ensure_question(
                    "我已收到你的问题，但还没有命中具体患者上下文。请补充床号，例如“帮我看12床情况”。",
                    question,
                )
                recommendations = [
                    {"title": "可继续直接提问，不需要固定格式。", "priority": 2},
                    {"title": "涉及具体患者时补充床号可提升准确率。", "priority": 2},
                ]
                confidence = 0.7
        elif ward_scope or len(contexts) > 1:
            ranked = sorted(
                [
                    {
                        "patient_id": str(ctx.get("patient_id") or ""),
                        "bed_no": str(ctx.get("bed_no") or "-"),
                        "risk_score": self._risk_score(ctx),
                        "risk_tags": len(ctx.get("risk_tags") or []),
                        "pending": len(ctx.get("pending_tasks") or []),
                    }
                    for ctx in contexts
                ],
                key=lambda item: item["risk_score"],
                reverse=True,
            )

            if settings.voice_llm_enabled:
                ranking_text = "\n".join(
                    [f"床位{row['bed_no']}: score={row['risk_score']} risk={row['risk_tags']} pending={row['pending']}" for row in ranked[:15]]
                )
                llm_answer = await bailian_refine(
                    "你是护理值班调度助手。请根据以下病区风险排序，输出："
                    "1) 总结 2) 前三优先动作 3) 上报条件。\n"
                    f"{ranking_text}\n用户问题：{question}"
                )
                if self._llm_unavailable(llm_answer):
                    top3 = "、".join([f"{row['bed_no']}床(分值{row['risk_score']})" for row in ranked[:3]])
                    llm_answer = f"已完成病区风险排序。当前建议优先处理：{top3}。"
                summary = self._ensure_question(llm_answer, question)
            else:
                top3 = "、".join([f"{row['bed_no']}床(分值{row['risk_score']})" for row in ranked[:3]])
                summary = self._ensure_question(f"已完成病区风险排序。当前建议优先处理：{top3}。", question)
            findings = [f"{row['bed_no']}床：风险分={row['risk_score']}（风险标签{row['risk_tags']}，待办{row['pending']}）" for row in ranked[:8]]
            recommendations = [{"title": f"优先处理 {row['bed_no']}床", "priority": 1} for row in ranked[:4]]
            confidence = 0.85
        else:
            context = contexts[0]
            payload.patient_id = str(context.get("patient_id") or payload.patient_id or "")
            payload.bed_no = str(context.get("bed_no") or payload.bed_no or "")
            deterministic_summary = self._build_single_patient_summary(context, payload.bed_no)
            summary = self._ensure_question(deterministic_summary, question)
            findings = self._build_context_findings(context)
            correction_note = str(context.get("_bed_no_correction_note") or "").strip()
            requested_bed = str(context.get("_requested_bed_no") or "").strip()
            resolved_bed = str(context.get("_resolved_bed_no") or payload.bed_no or "").strip()
            if not correction_note and requested_bed and resolved_bed and requested_bed != resolved_bed:
                correction_note = f"语音床号 {requested_bed} 已纠偏为 {resolved_bed}。"
            if correction_note:
                summary = f"{correction_note}{summary}"
                findings = [correction_note, *findings]
                confidence = 0.79
            recommendations = [
                {"title": f"优先处理：{str(task).strip()}", "priority": 1}
                for task in context.get("pending_tasks", [])[:4]
                if str(task).strip()
            ]
            if not recommendations:
                recommendations = [{"title": "继续监测关键指标并按医嘱复核。", "priority": 2}]
            confidence = max(confidence, 0.8)

        steps = [
            AgentStep(agent="Intent Router Agent", status="done"),
            AgentStep(agent="Patient Context Agent", status="done" if contexts else "skipped"),
        ]

        if any(token in question for token in self.COLLAB_TOKENS):
            note = await self._dispatch_collaboration(payload, summary)
            if note:
                recommendations.insert(0, {"title": note, "priority": 1})
                steps.append(AgentStep(agent="Collaboration Agent", status="done"))

        steps.extend(
            [
                AgentStep(agent="Reasoning Agent", status="done", output={"confidence": confidence}),
                AgentStep(agent="Audit Agent", status="done"),
            ]
        )

        await self._write_audit(
            action="workflow.voice_inquiry",
            resource_id=str(payload.patient_id or ""),
            detail={
                "question": question,
                "bed_no": payload.bed_no,
                "context_count": len(contexts),
                "ward_scope": ward_scope,
            },
            user_id=payload.requested_by,
        )

        resolved_patient_id = str(payload.patient_id or "").strip() or None
        resolved_bed_no = str(payload.bed_no or "").strip() or None
        resolved_patient_name: str | None = None
        if contexts and isinstance(contexts[0], dict):
            first_ctx = contexts[0]
            if not resolved_patient_id:
                resolved_patient_id = str(first_ctx.get("patient_id") or "").strip() or None
            if not resolved_bed_no:
                resolved_bed_no = str(first_ctx.get("bed_no") or "").strip() or None
            resolved_patient_name = str(first_ctx.get("patient_name") or "").strip() or None

        return WorkflowOutput(
            workflow_type=WorkflowType.VOICE_INQUIRY,
            summary=summary,
            findings=findings,
            recommendations=self._normalize_recommendations(recommendations),
            confidence=confidence,
            review_required=True,
            context_hit=bool(contexts),
            patient_id=resolved_patient_id,
            patient_name=resolved_patient_name,
            bed_no=resolved_bed_no,
            steps=steps,
            created_at=datetime.now(timezone.utc),
        )

    async def _run_handover(self, payload: WorkflowRequest) -> WorkflowOutput:
        question = (payload.user_input or "").strip()
        beds = self._extract_beds(question)
        if payload.bed_no and payload.bed_no not in beds:
            beds.insert(0, payload.bed_no)
        ward_scope = self._is_ward_scope(question, beds)
        contexts = await self._fetch_contexts(payload, beds, allow_ward_fallback=True)

        steps = [
            AgentStep(agent="Intent Router Agent", status="done"),
            AgentStep(agent="Patient Context Agent", status="done" if contexts else "skipped"),
            AgentStep(agent="Handover Agent", status="done"),
            AgentStep(agent="Audit Agent", status="done"),
        ]

        if not contexts:
            return WorkflowOutput(
                workflow_type=WorkflowType.HANDOVER,
                summary=self._ensure_question("未命中患者上下文。请补充床号，或直接说“生成全病区交班草稿”。", question),
                findings=[],
                recommendations=[{"title": "示例：请生成23床交班草稿。", "priority": 1}],
                confidence=0.3,
                review_required=True,
                steps=steps,
                created_at=datetime.now(timezone.utc),
            )

        if ward_scope or len(contexts) > 1:
            dep = payload.department_id or settings.default_department_id
            batch = await self._call_json(
                "POST",
                f"{settings.handover_service_url}/handover/batch-generate",
                payload={"department_id": dep, "generated_by": payload.requested_by},
                timeout=24,
            )
            if isinstance(batch, list) and batch:
                summary = self._ensure_question(f"已生成病区交班草稿，共 {len(batch)} 份，请在手机端审核后提交。", question)
                findings = [f"已生成患者：{str(item.get('patient_id', 'unknown'))}" for item in batch[:8] if isinstance(item, dict)]
                recommendations = [{"title": "先审核高风险患者交班草稿。", "priority": 1}]
                confidence = 0.82
            else:
                summary = self._ensure_question("批量交班服务暂不可用，请稍后重试。", question)
                findings = []
                recommendations = [{"title": "稍后重试“生成全病区交班草稿”。", "priority": 2}]
                confidence = 0.55
        else:
            context = contexts[0]
            patient_id = str(context.get("patient_id") or payload.patient_id or "").strip()
            record = await self._call_json(
                "POST",
                f"{settings.handover_service_url}/handover/generate",
                payload={"patient_id": patient_id, "generated_by": payload.requested_by},
                timeout=18,
            )
            if isinstance(record, dict):
                record_id = str(record.get("id") or "").strip()
                summary = str(record.get("summary") or "交班草稿已生成。").strip()
                if record_id:
                    summary = f"{summary}（交班ID: {record_id}）"
                summary = self._ensure_question(summary, question)
                findings = [str(item).strip() for item in record.get("worsening_points", [])[:5] if str(item).strip()]
                recommendations = [
                    {"title": f"下一班优先：{str(item).strip()}", "priority": 1}
                    for item in record.get("next_shift_priorities", [])[:4]
                    if str(item).strip()
                ]
                confidence = 0.84
            else:
                summary = self._ensure_question("交班服务暂不可用，请稍后重试。", question)
                findings = []
                recommendations = [{"title": "稍后重试交班生成。", "priority": 1}]
                confidence = 0.45

        await self._write_audit(
            action="workflow.handover",
            resource_id=str(payload.patient_id or ""),
            detail={"question": question, "bed_no": payload.bed_no},
            user_id=payload.requested_by,
        )
        resolved_patient_id = str(payload.patient_id or "").strip() or None
        resolved_bed_no = str(payload.bed_no or "").strip() or None
        resolved_patient_name: str | None = None
        if contexts and isinstance(contexts[0], dict):
            first_ctx = contexts[0]
            if not resolved_patient_id:
                resolved_patient_id = str(first_ctx.get("patient_id") or "").strip() or None
            if not resolved_bed_no:
                resolved_bed_no = str(first_ctx.get("bed_no") or "").strip() or None
            resolved_patient_name = str(first_ctx.get("patient_name") or "").strip() or None
        return WorkflowOutput(
            workflow_type=WorkflowType.HANDOVER,
            summary=summary,
            findings=findings,
            recommendations=self._normalize_recommendations(recommendations),
            confidence=confidence,
            review_required=True,
            context_hit=bool(contexts),
            patient_id=resolved_patient_id,
            patient_name=resolved_patient_name,
            bed_no=resolved_bed_no,
            steps=steps,
            created_at=datetime.now(timezone.utc),
        )

    async def _run_recommendation(self, payload: WorkflowRequest) -> WorkflowOutput:
        question = (payload.user_input or "").strip()
        beds = self._extract_beds(question)
        if payload.bed_no and payload.bed_no not in beds:
            beds.insert(0, payload.bed_no)
        ward_scope = self._is_ward_scope(question, beds)
        contexts = await self._fetch_contexts(payload, beds, allow_ward_fallback=True)

        steps = [
            AgentStep(agent="Intent Router Agent", status="done"),
            AgentStep(agent="Patient Context Agent", status="done" if contexts else "skipped"),
            AgentStep(agent="Recommendation Agent", status="done"),
            AgentStep(agent="Audit Agent", status="done"),
        ]

        if not contexts:
            return WorkflowOutput(
                workflow_type=WorkflowType.RECOMMENDATION,
                summary=self._ensure_question(
                    "未命中患者上下文。建议先补充床号；若是病区问题，可直接说“按病区排优先级”。",
                    question,
                ),
                findings=[],
                recommendations=[{"title": "补充床号后可输出更精准建议。", "priority": 1}],
                confidence=0.58,
                review_required=True,
                steps=steps,
                created_at=datetime.now(timezone.utc),
            )

        if ward_scope or len(contexts) > 1:
            ranked = sorted(
                [{"bed_no": str(ctx.get("bed_no") or "-"), "risk_score": self._risk_score(ctx)} for ctx in contexts],
                key=lambda x: x["risk_score"],
                reverse=True,
            )
            return WorkflowOutput(
                workflow_type=WorkflowType.RECOMMENDATION,
                summary=self._ensure_question("已完成病区风险排序，并给出优先处理顺序。", question),
                findings=[f"{row['bed_no']}床：风险分={row['risk_score']}" for row in ranked[:8]],
                recommendations=[{"title": f"优先处理 {row['bed_no']}床", "priority": 1} for row in ranked[:5]],
                confidence=0.84,
                review_required=True,
                steps=steps,
                created_at=datetime.now(timezone.utc),
            )

        context = contexts[0]
        patient_id = str(context.get("patient_id") or payload.patient_id or "").strip()
        bed_no = str(context.get("bed_no") or payload.bed_no or "")

        rec = await self._call_json(
            "POST",
            f"{settings.recommendation_service_url}/recommendation/run",
            payload={
                "patient_id": patient_id,
                "question": question or f"请给出 {bed_no} 床风险处理建议",
                "bed_no": bed_no or None,
                "department_id": payload.department_id,
                "attachments": payload.attachments,
                "requested_by": payload.requested_by,
                "fast_mode": True,
            },
            timeout=32,
        )

        if isinstance(rec, dict):
            summary = self._ensure_question(str(rec.get("summary") or ""), question)
            findings = [str(item).strip() for item in rec.get("findings", []) if str(item).strip()]
            recommendations = self._normalize_recommendations(rec.get("recommendations"))
            confidence = float(rec.get("confidence", 0.8) or 0.8)
        else:
            summary = self._ensure_question("推荐服务暂不可用，已回退为基础风险提示。", question)
            findings = []
            recommendations = [
                {"title": f"优先处理：{str(task).strip()}", "priority": 1}
                for task in context.get("pending_tasks", [])[:4]
                if str(task).strip()
            ] or [{"title": "先复核生命体征并通知医生。", "priority": 1}]
            confidence = 0.72

        await self._write_audit(
            action="workflow.recommendation",
            resource_id=patient_id,
            detail={"question": question, "bed_no": bed_no},
            user_id=payload.requested_by,
        )
        resolved_patient_name = str(context.get("patient_name") or "").strip() or None
        return WorkflowOutput(
            workflow_type=WorkflowType.RECOMMENDATION,
            summary=summary,
            findings=findings,
            recommendations=recommendations,
            confidence=confidence,
            review_required=True,
            context_hit=True,
            patient_id=patient_id or None,
            patient_name=resolved_patient_name,
            bed_no=bed_no or None,
            steps=steps,
            created_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _infer_document_type(text: str) -> str:
        q = (text or "").lower()
        if ("交班" in q) or ("handover" in q):
            return "handover_note"
        if ("病程" in q) or ("progress" in q):
            return "progress_note"
        return "nursing_note"

    async def _run_document(self, payload: WorkflowRequest) -> WorkflowOutput:
        question = (payload.user_input or "").strip()
        beds = self._extract_beds(question)
        if payload.bed_no and payload.bed_no not in beds:
            beds.insert(0, payload.bed_no)
        contexts = await self._fetch_contexts(payload, beds, allow_ward_fallback=False)

        steps = [
            AgentStep(agent="Intent Router Agent", status="done"),
            AgentStep(agent="Patient Context Agent", status="done" if contexts else "failed"),
            AgentStep(agent="Document Agent", status="done"),
            AgentStep(agent="Audit Agent", status="done"),
        ]

        if not contexts:
            return WorkflowOutput(
                workflow_type=WorkflowType.DOCUMENT,
                summary=self._ensure_question("文书草稿生成需要患者上下文，请补充床号后重试。", question),
                findings=[],
                recommendations=[{"title": "示例：请生成12床护理记录草稿。", "priority": 1}],
                confidence=0.2,
                review_required=True,
                steps=steps,
                created_at=datetime.now(timezone.utc),
            )

        context = contexts[0]
        patient_id = str(context.get("patient_id") or payload.patient_id or "").strip()
        if not patient_id:
            return WorkflowOutput(
                workflow_type=WorkflowType.DOCUMENT,
                summary="文书生成失败：未定位到患者ID。",
                findings=[],
                recommendations=[],
                confidence=0.2,
                review_required=True,
                steps=steps,
                created_at=datetime.now(timezone.utc),
            )

        doc_type = self._infer_document_type(question)
        draft = await self._call_json(
            "POST",
            f"{settings.document_service_url}/document/draft",
            payload={
                "patient_id": patient_id,
                "document_type": doc_type,
                "spoken_text": question,
                "requested_by": payload.requested_by,
            },
            timeout=18,
        )

        if not isinstance(draft, dict):
            summary = self._ensure_question("文书服务暂不可用，已记录请求，请稍后重试。", question)
            findings = ["未能获取文书草稿内容。"]
            recommendations = [{"title": "稍后重试文书生成。", "priority": 1}]
            confidence = 0.35
        else:
            draft_id = str(draft.get("id") or "").strip()
            draft_text = str(draft.get("draft_text") or "").strip()
            excerpt = draft_text[:90] + ("..." if len(draft_text) > 90 else "")
            summary = "文书草稿已生成，请在手机端审核后提交。"
            if draft_id:
                summary = f"{summary}（草稿ID: {draft_id}）"
            summary = self._ensure_question(summary, question)
            findings = [f"文书类型：{doc_type}"] + ([f"草稿摘要：{excerpt}"] if excerpt else [])
            recommendations = [
                {"title": "先人工审核草稿内容。", "priority": 1},
                {"title": "确认后在手机端提交。", "priority": 1},
            ]
            confidence = 0.84

        await self._write_audit(
            action="workflow.document",
            resource_id=patient_id,
            detail={"input": question, "document_type": doc_type, "bed_no": context.get("bed_no")},
            user_id=payload.requested_by,
        )
        resolved_bed_no = str(context.get("bed_no") or payload.bed_no or "").strip() or None
        resolved_patient_name = str(context.get("patient_name") or "").strip() or None
        return WorkflowOutput(
            workflow_type=WorkflowType.DOCUMENT,
            summary=summary,
            findings=findings,
            recommendations=recommendations,
            confidence=confidence,
            review_required=True,
            context_hit=True,
            patient_id=patient_id or None,
            patient_name=resolved_patient_name,
            bed_no=resolved_bed_no,
            steps=steps,
            created_at=datetime.now(timezone.utc),
        )


machine = AgentStateMachine()
