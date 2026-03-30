import re
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.config import settings
from app.schemas.workflow import (
    AIChatRequest,
    AIChatResponse,
    AIClusterProfile,
    AIModelOption,
    AIModelsResponse,
    AIModelTask,
    AgentQueueDecisionRequest,
    AgentQueueEnqueueRequest,
    AgentQueueTask,
    AgentRunRecord,
    AgentStep,
    AgentToolSpec,
    ChatMode,
    WorkflowHistoryItem,
    WorkflowOutput,
    WorkflowRequest,
    WorkflowType,
)
from app.services.agent_run_store import agent_run_store
from app.services.agent_queue_store import agent_queue_store
from app.services.agent_task_worker import agent_task_worker
from app.services.agentic_orchestrator import agentic_orchestrator
from app.services.history_store import workflow_history_store
from app.services.llm_client import bailian_refine, local_refine_with_model, probe_local_models
from app.services.agent_runtime import runtime

router = APIRouter()


class IntentReq(BaseModel):
    text: str


class IntentRsp(BaseModel):
    intent: WorkflowType


class RuntimeEngReq(BaseModel):
    engine: str


def _cloud_ok() -> bool:
    k = settings.bailian_api_key
    only_local = settings.local_only_mode
    return bool(k) and (not only_local)


def _local_aliases() -> dict[str, tuple[str, str]]:
    return {
        "minicpm3_4b_local": ("当前回复整理（本地）", settings.local_llm_model_primary),
        "qwen2_5_3b_local": ("轻量回答（本地）", settings.local_llm_model_fallback),
        "qwen3_8b_local": ("下一步安排（本地）", settings.local_llm_model_planner),
        "deepseek_r1_qwen_7b_local": ("重点再看一遍（本地）", settings.local_llm_model_reasoning),
        "custom_local": ("自定义本地回答", settings.local_llm_model_custom),
    }


def _resolve_local_mdl(sel: str) -> str:
    tup = _local_aliases().get(sel)
    if tup is None:
        return ""
    return tup[1]


def _resolve_selected_local_model(sel: str | None) -> str:
    return _resolve_local_mdl(str(sel or "").strip())


def _online_set(st: dict[str, Any]) -> set[str]:
    arr = st.get("models") or []
    out: set[str] = set()
    for x in arr:
        s = str(x).strip().lower()
        if s:
            out.add(s)
    return out


def _alias_on(a: str | None, onl: set[str]) -> bool:
    v = str(a or "").strip().lower()
    ok = bool(v) and v in onl
    return ok


def _local_desc(a: str | None, onl: set[str], use: str) -> str:
    if not a:
        return f"当前未配置，如需{use}请先在本地模型服务中完成配置。"
    on = _alias_on(a, onl)
    if on:
        return f"当前已启动，可用于{use}。"
    return f"当前未启动，如需{use}请先启动对应本地模型。"


def _norm_profile(ep: str | None) -> str | None:
    p = str(ep or "").strip().lower()
    if p:
        return p
    return None


def _coerce_wf(wf: WorkflowType, ep: str | None) -> WorkflowType:
    p = _norm_profile(ep)
    if p == "full_loop":
        return WorkflowType.AUTONOMOUS_CARE
    if p == "document":
        if wf == WorkflowType.VOICE_INQUIRY:
            return WorkflowType.DOCUMENT
    if p == "escalate":
        if wf == WorkflowType.VOICE_INQUIRY:
            return WorkflowType.RECOMMENDATION
    return wf


def _normalize_execution_profile(ep: str | None) -> str:
    p = _norm_profile(ep)
    if p in {"observe", "escalate", "document", "full_loop"}:
        return p
    return "observe"


def _coerce_chat_workflow(wf: WorkflowType, ep: str | None) -> WorkflowType:
    return _coerce_wf(wf, _normalize_execution_profile(ep))


def _cluster_tasks(attach: list[str], onl: set[str]) -> list[AIModelTask]:
    has_att = len(attach) > 0
    pri_ok = _alias_on(settings.local_llm_model_primary, onl)
    pln_ok = _alias_on(settings.local_llm_model_planner, onl)
    rsn_ok = _alias_on(settings.local_llm_model_reasoning, onl)
    mm_ok = _alias_on(settings.local_llm_model_multimodal, onl)
    lst: list[AIModelTask] = [
        AIModelTask(
            model_id="care-planner",
            model_name="处理步骤整理",
            role="顺序整理",
            task="把当前情况拆成先做、后做和谁来确认",
            enabled=True,
        ),
        AIModelTask(
            model_id="care-memory",
            model_name="历史回看",
            role="补充背景",
            task="回看历史会话、患者重点和未完成事项",
            enabled=True,
        ),
        AIModelTask(
            model_id="minicpm3-4b-local-main",
            model_name="当前回复整理",
            role="整理重点",
            task="理解提问、归纳重点并生成护士可读说明",
            enabled=pri_ok,
        ),
        AIModelTask(
            model_id="qwen3-8b-local-planner",
            model_name="下一步安排",
            role="梳理先后",
            task="补齐漏掉的步骤，告诉你先做什么后做什么",
            enabled=pln_ok,
        ),
        AIModelTask(
            model_id="deepseek-r1-local",
            model_name="重点再看一遍",
            role="再核对",
            task="对复杂情况再看一遍，避免遗漏",
            enabled=rsn_ok,
        ),
        AIModelTask(
            model_id="funasr-local",
            model_name="语音整理",
            role="语音转文字",
            task="把语音内容整理成文字",
            enabled=True,
        ),
        AIModelTask(
            model_id="minicpm3-4b-local",
            model_name="快速回答",
            role="快速说明",
            task="做床旁中文问答和术语解释",
            enabled=pri_ok,
        ),
        AIModelTask(
            model_id="medgemma-local",
            model_name="附件读取",
            role="补看附件",
            task="补看图片、PDF 和检查报告附件",
            enabled=has_att and mm_ok,
        ),
        AIModelTask(
            model_id="cosyvoice-local",
            model_name="语音播报",
            role="结果播报",
            task="把结果读出来",
            enabled=True,
        ),
        AIModelTask(
            model_id="care-critic",
            model_name="风险复看",
            role="补漏提醒",
            task="检查是否还需要沟通、交班或补充记录",
            enabled=True,
        ),
    ]
    cloud = _cloud_ok()
    if cloud:
        lst.insert(
            1,
            AIModelTask(
                model_id="bailian-qwen-main",
                model_name="云端补充复核",
                role="补充复看",
                task="在本地模型不足时补充复杂情况复核",
                enabled=True,
            ),
        )
    return lst


async def _models_catalog() -> AIModelsResponse:
    cloud_on = _cloud_ok()
    local_status = await probe_local_models()
    onl = _online_set(local_status)
    cluster = AIClusterProfile(
        id="nursing_default_cluster",
        name="系统协同",
        main_model="当前回复整理（本地）",
        description="系统会先整理当前重点，再帮你排处理顺序；遇到复杂情况时再多看一遍，有附件时再补看报告。",
        tasks=_cluster_tasks([], onl),
    )
    single_models = [
        AIModelOption(
            id="minicpm3_4b_local",
            name="当前回复整理（本地）",
            provider="local",
            description=_local_desc(settings.local_llm_model_primary, onl, "快速整理当前问题"),
        ),
        AIModelOption(
            id="qwen2_5_3b_local",
            name="轻量回答（本地）",
            provider="local",
            description=_local_desc(settings.local_llm_model_fallback, onl, "在低资源环境下快速回答"),
        ),
        AIModelOption(
            id="qwen3_8b_local",
            name="下一步安排（本地）",
            provider="local",
            description=_local_desc(settings.local_llm_model_planner, onl, "安排先做什么后做什么"),
        ),
        AIModelOption(
            id="deepseek_r1_qwen_7b_local",
            name="重点再看一遍（本地）",
            provider="local",
            description=_local_desc(settings.local_llm_model_reasoning, onl, "对复杂情况做进一步复核"),
        ),
        AIModelOption(
            id="medgemma_local",
            name="附件查看（本地）",
            provider="local",
            description=_local_desc(settings.local_llm_model_multimodal, onl, "查看报告、图片和附件"),
        ),
        AIModelOption(
            id="custom_local",
            name="自定义本地能力",
            provider="local",
            description=_local_desc(settings.local_llm_model_custom, onl, "接入自定义本地模型"),
        ),
    ]
    if cloud_on:
        single_models.extend(
            [
                AIModelOption(
                    id="bailian_main",
                    name="云端综合回答",
                    provider="bailian",
                    description="当本地模型不足时，可补充综合回答与复看。",
                ),
                AIModelOption(
                    id="qwen_light",
                    name="云端快速补答",
                    provider="bailian",
                    description="适合快速补充短回答。",
                ),
            ]
        )
    return AIModelsResponse(single_models=single_models, cluster_profiles=[cluster])


def _normalize_output_text(text: str) -> str:
    cleaned = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"^\s*#{1,6}\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"\*(.*?)\*", r"\1", cleaned)
    cleaned = re.sub(r"`([^`]*)`", r"\1", cleaned)
    cleaned = re.sub(r"^\s*[-*]\s+", "• ", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*\|[-:\s|]+\|\s*$", "", cleaned, flags=re.MULTILINE)

    def _table_row_to_text(match: re.Match[str]) -> str:
        parts = [cell.strip() for cell in match.group(1).split("|")]
        parts = [part for part in parts if part]
        return " / ".join(parts)

    cleaned = re.sub(r"^\s*\|(.+)\|\s*$", _table_row_to_text, cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _safe_with_question(summary: str, question: str) -> str:
    summary = _normalize_output_text(summary or "")
    q = _normalize_output_text(question or "").strip()
    if summary:
        return summary
    return q


async def _run_medgemma_single(payload: AIChatRequest) -> dict[str, Any]:
    body = {
        "patient_id": payload.patient_id or "unknown",
        "input_refs": payload.attachments,
        "question": payload.user_input,
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(40, connect=8), trust_env=False) as client:
            resp = await client.post(f"{settings.multimodal_service_url}/multimodal/analyze", json=body)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return {
            "summary": _safe_with_question(
                "本地多模态服务暂时不可用，已回退为安全提示：请先进行人工复核并补充关键生命体征。",
                payload.user_input,
            ),
            "findings": ["未获取到本地多模态服务结果"],
            "recommendations": [
                {"title": "先进行人工复核并补录关键信息", "priority": 1},
                {"title": "稍后重试本地多模态分析", "priority": 2},
            ],
            "confidence": 0.35,
            "review_required": True,
        }

    return {
        "summary": _safe_with_question(str(data.get("summary") or "已完成本地多模态分析"), payload.user_input),
        "findings": data.get("findings") if isinstance(data.get("findings"), list) else [],
        "recommendations": data.get("recommendations") if isinstance(data.get("recommendations"), list) else [],
        "confidence": float(data.get("confidence", 0.72) or 0.72),
        "review_required": bool(data.get("review_required", True)),
    }


async def _write_audit(
    *,
    action: str,
    resource_type: str,
    resource_id: str | None,
    detail: dict[str, Any],
    user_id: str | None,
) -> None:
    payload = {
        "user_id": user_id,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "detail": detail,
    }
    async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
        try:
            await client.post(f"{settings.audit_service_url}/audit/log", json=payload)
        except Exception:
            return


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": settings.service_name}


@router.get("/ready")
def ready() -> dict:
    return {"status": "ready", "service": settings.service_name}


@router.get("/version")
async def version() -> dict:
    runtime_status = runtime.status()
    local_status = await probe_local_models()
    return {
        "service": settings.service_name,
        "version": settings.app_version,
        "env": settings.app_env,
        "mock_mode": settings.mock_mode,
        "local_only_mode": settings.local_only_mode,
        "runtime_configured_engine": runtime_status["configured_engine"],
        "runtime_active_engine": runtime_status["active_engine"],
        "runtime_langgraph_available": runtime_status["langgraph_available"],
        "runtime_override_enabled": runtime_status["override_enabled"],
        "runtime_fallback_reason": runtime_status["fallback_reason"],
        "planner_llm_enabled": settings.agent_planner_llm_enabled,
        "local_model_service_reachable": local_status["reachable"],
        "registered_agent_tools": [tool.id for tool in agentic_orchestrator.tool_specs()],
        "approval_required_tools": agentic_orchestrator.approval_tool_ids(),
        "task_queue": agent_task_worker.status(),
        "local_model_aliases": {
            "primary": settings.local_llm_model_primary,
            "fallback": settings.local_llm_model_fallback,
            "planner": settings.local_llm_model_planner,
            "reasoning": settings.local_llm_model_reasoning,
            "custom": settings.local_llm_model_custom,
            "multimodal": settings.local_llm_model_multimodal,
        },
    }


@router.post("/intent/route", response_model=IntentRsp)
async def route_intent(req: IntentReq) -> IntentRsp:
    intent = await runtime.route_intent(req.text)
    return IntentRsp(intent=intent)


@router.get("/ai/runtime")
async def ai_runtime_status() -> dict[str, Any]:
    status = runtime.status()
    local_status = await probe_local_models()
    status["planner_llm_enabled"] = settings.agent_planner_llm_enabled
    status["planner_timeout_sec"] = settings.agent_planner_timeout_sec
    status["planner_max_steps"] = settings.agent_planner_max_steps
    status["local_model_service_reachable"] = local_status["reachable"]
    status["available_local_models"] = local_status["models"]
    status["registered_agent_tools"] = [tool.id for tool in agentic_orchestrator.tool_specs()]
    status["approval_required_tools"] = agentic_orchestrator.approval_tool_ids()
    status["task_queue"] = agent_task_worker.status()
    status["local_model_aliases"] = {
        "primary": settings.local_llm_model_primary,
        "fallback": settings.local_llm_model_fallback,
        "planner": settings.local_llm_model_planner,
        "reasoning": settings.local_llm_model_reasoning,
        "custom": settings.local_llm_model_custom,
        "multimodal": settings.local_llm_model_multimodal,
    }
    return status


@router.post("/ai/runtime")
async def ai_runtime_set(req: RuntimeEngReq) -> dict[str, Any]:
    r = (req.engine or "").strip().lower()
    if r not in {"state_machine", "langgraph", "graph"}:
        raise HTTPException(status_code=400, detail="invalid_engine")
    return runtime.set_engine(r)


@router.delete("/ai/runtime")
async def ai_runtime_clear() -> dict[str, Any]:
    return runtime.clear_override()


@router.post("/workflow/run", response_model=WorkflowOutput)
async def run_workflow(payload: WorkflowRequest) -> WorkflowOutput:
    return await runtime.run(payload)


@router.get("/ai/models", response_model=AIModelsResponse)
async def ai_models() -> AIModelsResponse:
    return await _models_catalog()


@router.get("/ai/tools", response_model=list[AgentToolSpec])
async def ai_tools() -> list[AgentToolSpec]:
    return agentic_orchestrator.tool_specs()


@router.get("/ai/runs", response_model=list[AgentRunRecord])
async def ai_runs(
    patient_id: str | None = Query(default=None),
    conversation_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    workflow_type: WorkflowType | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[AgentRunRecord]:
    return agent_run_store.list(
        patient_id=patient_id,
        conversation_id=conversation_id,
        status=status,
        workflow_type=workflow_type,
        limit=limit,
    )


@router.get("/ai/runs/{run_id}", response_model=AgentRunRecord)
async def ai_run_detail(run_id: str) -> AgentRunRecord:
    record = agent_run_store.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run_not_found")
    return record


@router.post("/ai/runs/{run_id}/retry", response_model=WorkflowOutput)
async def ai_run_retry(run_id: str) -> WorkflowOutput:
    payload = agent_run_store.retry_request(run_id)
    if payload is None:
        raise HTTPException(status_code=409, detail="retry_unavailable")
    return await runtime.run(payload)


@router.post("/ai/queue/tasks", response_model=AgentQueueTask)
async def ai_queue_enqueue(payload: AgentQueueEnqueueRequest) -> AgentQueueTask:
    task = agent_queue_store.enqueue(
        payload.payload,
        requested_engine=payload.requested_engine,
        priority=payload.priority,
    )
    agent_task_worker.notify()
    return task


@router.get("/ai/queue/tasks", response_model=list[AgentQueueTask])
async def ai_queue_tasks(
    patient_id: str | None = Query(default=None),
    conversation_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[AgentQueueTask]:
    return agent_queue_store.list(
        patient_id=patient_id,
        conversation_id=conversation_id,
        status=status,
        limit=limit,
    )


@router.get("/ai/queue/tasks/{task_id}", response_model=AgentQueueTask)
async def ai_queue_task_detail(task_id: str) -> AgentQueueTask:
    task = agent_queue_store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="queue_task_not_found")
    return task


@router.post("/ai/queue/tasks/{task_id}/approve", response_model=AgentQueueTask)
async def ai_queue_task_approve(task_id: str, payload: AgentQueueDecisionRequest) -> AgentQueueTask:
    if agent_queue_store.get(task_id) is None:
        raise HTTPException(status_code=404, detail="queue_task_not_found")
    task = agent_queue_store.approve(
        task_id,
        approval_ids=payload.approval_ids,
        decided_by=payload.decided_by,
        comment=payload.comment,
    )
    if task is None:
        raise HTTPException(status_code=409, detail="queue_task_not_waiting_approval")
    if task.status == "queued":
        agent_task_worker.notify()
    return task


@router.post("/ai/queue/tasks/{task_id}/reject", response_model=AgentQueueTask)
async def ai_queue_task_reject(task_id: str, payload: AgentQueueDecisionRequest) -> AgentQueueTask:
    if agent_queue_store.get(task_id) is None:
        raise HTTPException(status_code=404, detail="queue_task_not_found")
    task = agent_queue_store.reject(
        task_id,
        approval_ids=payload.approval_ids,
        decided_by=payload.decided_by,
        comment=payload.comment,
    )
    if task is None:
        raise HTTPException(status_code=409, detail="queue_task_not_waiting_approval")
    if task.status == "queued":
        agent_task_worker.notify()
    return task


@router.post("/ai/chat", response_model=AIChatResponse)
async def ai_chat(payload: AIChatRequest) -> AIChatResponse:
    if payload.mode == ChatMode.SINGLE_MODEL:
        selected = payload.selected_model or "minicpm3_4b_local"

        if selected == "medgemma_local":
            local_result = await _run_medgemma_single(payload)
            output = WorkflowOutput(
                workflow_type=WorkflowType.SINGLE_MODEL_CHAT,
                summary=local_result["summary"],
                findings=local_result["findings"],
                recommendations=local_result["recommendations"],
                confidence=float(local_result["confidence"]),
                review_required=bool(local_result["review_required"]),
                steps=[AgentStep(agent="MedGemma Runner", status="done")],
                created_at=datetime.now(timezone.utc),
            )
        elif selected in _local_aliases():
            prompt = payload.user_input
            if payload.patient_id:
                prompt = f"patient_id={payload.patient_id}; question={payload.user_input}"
            local_model_name = _resolve_selected_local_model(selected)
            if not local_model_name:
                refined = "当前模型别名未配置。请在 .env.local 中设置对应的 LOCAL_LLM_MODEL_* 变量。"
            else:
                refined = await local_refine_with_model(prompt, local_model_name)
            if not refined:
                refined = (
                    "本地模型暂时不可用，请先启动本地模型服务，"
                    "或检查模型别名是否与当前服务暴露的一致。"
                )
            refined = _safe_with_question(refined, payload.user_input)
            output = WorkflowOutput(
                workflow_type=WorkflowType.SINGLE_MODEL_CHAT,
                summary=refined,
                findings=[],
                recommendations=[
                    {"title": "如需多模态，请切换 MedGemma 本地模型", "priority": 1},
                    {"title": "如需复杂推理，请切换 AI Agent 集群", "priority": 2},
                ],
                confidence=0.72,
                review_required=True,
                steps=[AgentStep(agent="Local CN Model Runner", status="done", input={"selected_model": selected})],
                created_at=datetime.now(timezone.utc),
            )
        else:
            prompt = payload.user_input
            if payload.patient_id:
                prompt = f"patient_id={payload.patient_id}; question={payload.user_input}"
            if settings.local_only_mode:
                refined = await local_refine_with_model(prompt, settings.local_llm_model_primary)
                if not refined:
                    refined = "本地模型暂时不可用，当前已禁用云端回退。请先启动本地模型服务。"
            else:
                refined = await bailian_refine(prompt)
            refined = _safe_with_question(refined, payload.user_input)
            findings = []
            if payload.attachments:
                findings.append(f"已接收{len(payload.attachments)}个附件，可切换本地多模态模型进一步分析。")
            output = WorkflowOutput(
                workflow_type=WorkflowType.SINGLE_MODEL_CHAT,
                summary=refined,
                findings=findings,
                recommendations=[
                    {"title": "先给出初步判断，再触发人工复核", "priority": 1},
                    {"title": "必要时切换到AI Agent集群获取多模型协同结论", "priority": 2},
                ],
                confidence=0.76,
                review_required=True,
                steps=[AgentStep(agent="Single Model Runner", status="done", input={"selected_model": selected})],
                execution_profile=payload.execution_profile,
                mission_title=payload.mission_title,
                success_criteria=list(payload.success_criteria),
                created_at=datetime.now(timezone.utc),
            )

        history_request = WorkflowRequest(
            workflow_type=WorkflowType.SINGLE_MODEL_CHAT,
            patient_id=payload.patient_id,
            conversation_id=payload.conversation_id,
            department_id=payload.department_id,
            bed_no=payload.bed_no,
            user_input=payload.user_input,
            mission_title=payload.mission_title,
            success_criteria=list(payload.success_criteria),
            operator_notes=payload.operator_notes,
            attachments=payload.attachments,
            requested_by=payload.requested_by,
            agent_mode="direct_answer",
            execution_profile=payload.execution_profile,
        )
        output = agentic_orchestrator.finalize(
            history_request,
            output.model_copy(
                update={
                    "agent_mode": "direct_answer",
                    "execution_profile": payload.execution_profile,
                    "mission_title": payload.mission_title,
                    "success_criteria": list(payload.success_criteria),
                }
            ),
        )
        workflow_history_store.append(history_request, output)

        await _write_audit(
            action="ai_chat.single_model",
            resource_type="ai_chat",
            resource_id=payload.patient_id,
            detail={"selected_model": selected, "attachments": len(payload.attachments)},
            user_id=payload.requested_by,
        )

        if selected == "medgemma_local":
            model_name = "MedGemma 4B（本地）"
            model_role = "本地多模态判读"
            model_task = "图像/PDF/病历分析"
        elif selected == "minicpm3_4b_local":
            model_name = "MiniCPM3-4B（本地中文）"
            model_role = "本地中文问答"
            model_task = "低资源中文临床问答"
        elif selected == "qwen2_5_3b_local":
            model_name = "Qwen2.5-3B（本地轻量）"
            model_role = "本地轻量问答"
            model_task = "低内存中文问答"
        else:
            model_name = "本地中文主模型"
            model_role = "直接回答"
            model_task = "按本地单模型策略完成问答"

        return AIChatResponse(
            mode=payload.mode,
            selected_model=selected,
            cluster_profile=None,
            conversation_id=payload.conversation_id,
            workflow_type=WorkflowType.SINGLE_MODEL_CHAT,
            summary=_normalize_output_text(output.summary),
            findings=output.findings,
            recommendations=output.recommendations,
            confidence=output.confidence,
            review_required=output.review_required,
            steps=output.steps,
            model_plan=[
                AIModelTask(
                    model_id=selected,
                    model_name=model_name,
                    role=model_role,
                    task=model_task,
                    enabled=True,
                )
            ],
            run_id=output.run_id,
            runtime_engine=output.runtime_engine,
            agent_goal=output.agent_goal,
            agent_mode=output.agent_mode,
            execution_profile=output.execution_profile or payload.execution_profile,
            mission_title=output.mission_title or payload.mission_title,
            success_criteria=list(output.success_criteria or payload.success_criteria),
            plan=output.plan,
            memory=output.memory,
            artifacts=output.artifacts,
            specialist_profiles=output.specialist_profiles,
            hybrid_care_path=output.hybrid_care_path,
            data_capsule=output.data_capsule,
            health_graph=output.health_graph,
            reasoning_cards=output.reasoning_cards,
            pending_approvals=output.pending_approvals,
            next_actions=output.next_actions,
            created_at=output.created_at,
        )

    # agent cluster
    effective_agent_mode = payload.agent_mode or ("autonomous" if _normalize_execution_profile(payload.execution_profile) == "full_loop" else None)
    intent = _coerce_chat_workflow(await runtime.route_intent(payload.user_input), payload.execution_profile)
    workflow_payload = WorkflowRequest(
        workflow_type=intent,
        patient_id=payload.patient_id,
        conversation_id=payload.conversation_id,
        department_id=payload.department_id,
        bed_no=payload.bed_no,
        user_input=payload.user_input,
        mission_title=payload.mission_title,
        success_criteria=list(payload.success_criteria),
        operator_notes=payload.operator_notes,
        attachments=payload.attachments,
        requested_by=payload.requested_by,
        agent_mode=effective_agent_mode,
        execution_profile=payload.execution_profile,
    )

    try:
        output = await runtime.run(workflow_payload)
    except Exception:
        output = agentic_orchestrator.finalize(
            workflow_payload,
            WorkflowOutput(
            workflow_type=WorkflowType.VOICE_INQUIRY,
            summary=_safe_with_question("集群推理暂时超时，已返回安全降级结果，请稍后重试。", payload.user_input),
            findings=["agent-orchestrator 执行超时或上游不可用"],
            recommendations=[
                {"title": "先人工复核当前病例风险", "priority": 1},
                {"title": "稍后重新发起Agent集群分析", "priority": 2},
            ],
            confidence=0.32,
            review_required=True,
            steps=[AgentStep(agent="Agent Cluster Fallback", status="done")],
            agent_mode=effective_agent_mode or "assisted",
            execution_profile=payload.execution_profile,
            mission_title=payload.mission_title,
            success_criteria=list(payload.success_criteria),
            created_at=datetime.now(timezone.utc),
            ),
        )
        workflow_history_store.append(workflow_payload, output)

    await _write_audit(
        action="ai_chat.agent_cluster",
        resource_type="ai_chat",
        resource_id=payload.patient_id,
        detail={
            "cluster_profile": payload.cluster_profile,
            "workflow_type": output.workflow_type.value,
            "execution_profile": _normalize_execution_profile(payload.execution_profile),
            "mission_title": payload.mission_title,
        },
        user_id=payload.requested_by,
    )

    try:
        local_status = await probe_local_models()
        model_plan = _cluster_tasks(payload.attachments, _online_set(local_status))
    except Exception:
        # Keep the primary agent result available even if local model probing fails.
        model_plan = _cluster_tasks(payload.attachments, set())

    return AIChatResponse(
        mode=payload.mode,
        selected_model="minicpm3_4b_local" if settings.local_only_mode else "bailian_main",
        cluster_profile=payload.cluster_profile,
        conversation_id=payload.conversation_id,
        workflow_type=output.workflow_type,
        summary=_normalize_output_text(output.summary),
        findings=output.findings,
        recommendations=output.recommendations,
        confidence=output.confidence,
        review_required=output.review_required,
        steps=output.steps,
        model_plan=model_plan,
        run_id=output.run_id,
        runtime_engine=output.runtime_engine,
        agent_goal=output.agent_goal,
        agent_mode=output.agent_mode,
        execution_profile=output.execution_profile or payload.execution_profile,
        mission_title=output.mission_title or payload.mission_title,
        success_criteria=list(output.success_criteria or payload.success_criteria),
        plan=output.plan,
        memory=output.memory,
        artifacts=output.artifacts,
        specialist_profiles=output.specialist_profiles,
        hybrid_care_path=output.hybrid_care_path,
        data_capsule=output.data_capsule,
        health_graph=output.health_graph,
        reasoning_cards=output.reasoning_cards,
        pending_approvals=output.pending_approvals,
        next_actions=output.next_actions,
        created_at=output.created_at,
    )


@router.post("/workflow/voice-inquiry", response_model=WorkflowOutput)
async def voice_inquiry(payload: WorkflowRequest) -> WorkflowOutput:
    payload.workflow_type = WorkflowType.VOICE_INQUIRY
    return await runtime.run(payload)


@router.post("/workflow/handover", response_model=WorkflowOutput)
async def handover(payload: WorkflowRequest) -> WorkflowOutput:
    payload.workflow_type = WorkflowType.HANDOVER
    return await runtime.run(payload)


@router.post("/workflow/recommendation", response_model=WorkflowOutput)
async def recommendation(payload: WorkflowRequest) -> WorkflowOutput:
    payload.workflow_type = WorkflowType.RECOMMENDATION
    return await runtime.run(payload)


@router.post("/workflow/document", response_model=WorkflowOutput)
async def document(payload: WorkflowRequest) -> WorkflowOutput:
    payload.workflow_type = WorkflowType.DOCUMENT
    return await runtime.run(payload)


@router.post("/workflow/autonomous-care", response_model=WorkflowOutput)
async def autonomous_care(payload: WorkflowRequest) -> WorkflowOutput:
    payload.workflow_type = WorkflowType.AUTONOMOUS_CARE
    if not payload.agent_mode:
        payload.agent_mode = "autonomous"
    return await runtime.run(payload)


@router.get("/workflow/history", response_model=list[WorkflowHistoryItem])
async def workflow_history(
    patient_id: str | None = Query(default=None),
    conversation_id: str | None = Query(default=None),
    requested_by: str | None = Query(default=None),
    workflow_type: WorkflowType | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[WorkflowHistoryItem]:
    return workflow_history_store.list(
        patient_id=patient_id,
        conversation_id=conversation_id,
        requested_by=requested_by,
        workflow_type=workflow_type,
        limit=limit,
    )
