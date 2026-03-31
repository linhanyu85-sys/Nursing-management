from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from app.core.config import settings
from app.schemas.workflow import (
    AgentApprovalRequest,
    AgentArtifact,
    AgentMemorySnapshot,
    AgentPlanItem,
    AgentStep,
    AgentToolExecution,
    AgentToolSpec,
    HealthDataCapsule,
    HealthGraphSnapshot,
    HybridCareStage,
    ReasoningCard,
    SpecialistDigitalTwin,
    WorkflowOutput,
    WorkflowRequest,
    WorkflowType,
)
from app.services.agent_memory import agent_memory_store
from app.services.agent_run_store import agent_run_store
from app.services.agent_tool_registry import AgentToolRegistry
from app.services.llm_client import local_structured_json

AUTO_KW = (
    "自动",
    "闭环",
    "持续跟进",
    "帮我处理",
    "直接处理",
    "自动协作",
    "自动交班",
    "自动文书",
    "通知并",
    "同时通知",
    "并生成",
    "盯一下",
    "跟进一下",
    "全程跟进",
    "agent",
    "autonomous",
)
COLLAB_KW = ("通知", "联系", "协作", "转告", "值班医生", "护士长", "发送给", "发给", "提醒医生")
DOC_KW = ("文书", "记录", "草稿", "留痕", "护理记录", "病程记录")
HANDOVER_KW = ("交班", "交接班", "handover")
ORDER_KW = ("医嘱", "补开", "申请医嘱", "请求处置", "执行", "超时", "到时", "double check")
REC_KW = ("建议", "处置", "怎么办", "优先级", "风险", "升级", "上报")
URGENT_KW = (
    "危急",
    "高危",
    "恶化",
    "胸痛",
    "气促",
    "呼吸困难",
    "血氧",
    "低血压",
    "发热",
    "高热",
    "出血",
    "抽搐",
    "意识",
    "overdue",
    "urgent",
    "紧急",
)
APPROVAL_TOOL_IDS = {"send_collaboration", "create_handover", "create_document", "request_order"}
COLLAB_KW = COLLAB_KW + ("notify", "send", "doctor", "escalate")
DOC_KW = DOC_KW + ("document", "draft", "note")
HANDOVER_KW = HANDOVER_KW + ("shift",)
ORDER_KW = ORDER_KW + ("order",)
REC_KW = REC_KW + ("recommend", "priority")
PROFILE_ACTIONS: dict[str, list[str]] = {
    "observe": ["fetch_orders", "recommend"],
    "escalate": ["fetch_orders", "recommend", "send_collaboration"],
    "document": ["fetch_orders", "recommend", "create_handover", "create_document"],
    "full_loop": ["fetch_orders", "recommend", "send_collaboration", "create_handover", "create_document"],
}


def is_autonomous_request(txt: str | None) -> bool:
    q = str(txt or "").strip().lower()
    if q == "":
        return False
    has_auto = False
    for kw in AUTO_KW:
        if kw in q:
            has_auto = True
            break
    if has_auto:
        return True

    cnt = 0
    for kw in COLLAB_KW:
        if kw in q:
            cnt += 1
            break
    for kw in DOC_KW:
        if kw in q:
            cnt += 1
            break
    for kw in HANDOVER_KW:
        if kw in q:
            cnt += 1
            break
    for kw in ORDER_KW:
        if kw in q:
            cnt += 1
            break
    return cnt >= 2


class AgenticOrchestrator:
    def __init__(self) -> None:
        self._tool_registry = AgentToolRegistry()
        self._register_tools()

    def route_workflow(
        self,
        payload: WorkflowRequest,
        fallback_route: Callable[[str], Awaitable[WorkflowType]],
    ) -> Awaitable[WorkflowType]:
        return self._route_workflow(payload, fallback_route)

    async def _route_workflow(
        self,
        payload: WorkflowRequest,
        fallback_route: Callable[[str], Awaitable[WorkflowType]],
    ) -> WorkflowType:
        planning_brief = self._planning_brief(payload)
        profile_workflow = self._workflow_for_profile(payload.execution_profile, payload.workflow_type)
        if profile_workflow is not None:
            return profile_workflow
        if payload.workflow_type != WorkflowType.VOICE_INQUIRY:
            return payload.workflow_type
        if is_autonomous_request(planning_brief):
            return WorkflowType.AUTONOMOUS_CARE
        return await fallback_route(planning_brief)

    def retrieve_memory(self, payload: WorkflowRequest) -> AgentMemorySnapshot:
        return agent_memory_store.snapshot(
            patient_id=payload.patient_id,
            conversation_id=payload.conversation_id,
            requested_by=payload.requested_by,
            user_input=payload.user_input,
        )

    def tool_specs(self) -> list[AgentToolSpec]:
        return self._tool_registry.specs()

    def approval_tool_ids(self) -> list[str]:
        return sorted(APPROVAL_TOOL_IDS)

    def _register_tools(self) -> None:
        self._tool_registry.register(
            AgentToolSpec(
                id="fetch_orders",
                title="补充医嘱执行状态",
                agent="Order Signal Agent",
                description="查询待执行、到时和超时医嘱信号。",
                retryable=True,
                max_retries=1,
                produces_artifact=False,
                category="patient_state",
            ),
            self._tool_fetch_orders,
        )
        self._tool_registry.register(
            AgentToolSpec(
                id="recommend",
                title="生成临床处置建议",
                agent="Recommendation Agent",
                description="调用推荐服务生成结构化处置建议。",
                retryable=True,
                max_retries=1,
                produces_artifact=False,
                category="reasoning",
            ),
            self._tool_recommend,
        )
        self._tool_registry.register(
            AgentToolSpec(
                id="send_collaboration",
                title="向值班医生发起协作",
                agent="Collaboration Agent",
                description="生成协作摘要并发送给值班医生。",
                retryable=True,
                max_retries=1,
                produces_artifact=True,
                category="coordination",
            ),
            self._tool_send_collaboration,
        )
        self._tool_registry.register(
            AgentToolSpec(
                id="create_handover",
                title="生成交班草稿",
                agent="Handover Agent",
                description="基于患者状态生成交班草稿。",
                retryable=True,
                max_retries=1,
                produces_artifact=True,
                category="documentation",
            ),
            self._tool_create_handover,
        )
        self._tool_registry.register(
            AgentToolSpec(
                id="create_document",
                title="生成护理文书草稿",
                agent="Document Agent",
                description="创建可审核的护理文书草稿。",
                retryable=True,
                max_retries=1,
                produces_artifact=True,
                category="documentation",
            ),
            self._tool_create_document,
        )
        self._tool_registry.register(
            AgentToolSpec(
                id="request_order",
                title="创建医嘱请求",
                agent="Order Request Agent",
                description="只创建待确认的医嘱请求，不直接执行医嘱。",
                retryable=True,
                max_retries=1,
                produces_artifact=True,
                category="coordination",
            ),
            self._tool_request_order,
        )

    async def build_plan(
        self,
        payload: WorkflowRequest,
        workflow_type: WorkflowType,
        memory: AgentMemorySnapshot,
        *,
        critique: dict[str, Any] | None = None,
        existing_plan: list[AgentPlanItem] | None = None,
    ) -> list[AgentPlanItem]:
        if critique and critique.get("followup_actions"):
            return self._merge_followup_plan(existing_plan or [], critique["followup_actions"])

        goal = self._build_agent_goal(payload, workflow_type)
        library = self._plan_library(goal)
        plan = self._base_plan(workflow_type, memory, library)
        if workflow_type != WorkflowType.AUTONOMOUS_CARE:
            return plan

        question = self._planning_brief(payload)
        heuristic_ids = self._candidate_action_ids(
            question,
            memory,
            execution_profile=payload.execution_profile,
        )
        planned_items = await self._plan_with_llm(
            question=question,
            goal=goal,
            workflow_type=workflow_type,
            memory=memory,
            library=library,
        )
        merged_items = self._merge_planned_items(
            heuristic_ids=heuristic_ids,
            planned_items=planned_items,
            library=library,
        )
        return self._trim_plan([*plan, *merged_items])

    def _plan_library(self, goal: str) -> dict[str, AgentPlanItem]:
        return {
            "review_memory": AgentPlanItem(
                id="review_memory",
                title="回看会话与患者记忆",
                tool="memory",
                reason="结合历史交互避免重复追问与重复处置。",
            ),
            "fetch_context": AgentPlanItem(
                id="fetch_context",
                title="定位患者上下文",
                tool="patient_context",
                reason=f"围绕目标“{goal}”先建立当前患者或病区状态。",
            ),
            "fetch_orders": AgentPlanItem(
                id="fetch_orders",
                title="补充医嘱执行状态",
                tool="patient_orders",
                reason="闭环处理需要知道待执行、到时和超时医嘱。",
            ),
            "recommend": AgentPlanItem(
                id="recommend",
                title="生成临床处置建议",
                tool="recommendation",
                reason="先产出结构化判断，再决定后续动作。",
            ),
            "send_collaboration": AgentPlanItem(
                id="send_collaboration",
                title="向值班医生发起协作",
                tool="collaboration",
                reason="高风险或明确通知诉求需要形成协作闭环。",
            ),
            "create_handover": AgentPlanItem(
                id="create_handover",
                title="生成交班草稿",
                tool="handover",
                reason="将风险与待办沉淀为可审核交班记录。",
            ),
            "create_document": AgentPlanItem(
                id="create_document",
                title="生成护理文书草稿",
                tool="document",
                reason="为闭环动作保留可审核留痕。",
            ),
            "request_order": AgentPlanItem(
                id="request_order",
                title="创建医嘱请求",
                tool="order_request",
                reason="用户明确要求补开/申请医嘱时，只创建请求，不直接执行。",
            ),
            "voice_assessment": AgentPlanItem(
                id="voice_assessment",
                title="完成床旁问询分析",
                tool="voice_assessment",
                reason="输出当前患者或病区风险总结。",
            ),
        }

    def _base_plan(
        self,
        workflow_type: WorkflowType,
        memory: AgentMemorySnapshot,
        library: dict[str, AgentPlanItem],
    ) -> list[AgentPlanItem]:
        review_memory = library["review_memory"].model_copy(
            update={"status": "done" if memory.conversation_summary or memory.patient_facts else "skipped"}
        )
        plan = [review_memory, library["fetch_context"]]

        workflow_step_id = {
            WorkflowType.VOICE_INQUIRY: "voice_assessment",
            WorkflowType.RECOMMENDATION: "recommend",
            WorkflowType.HANDOVER: "create_handover",
            WorkflowType.DOCUMENT: "create_document",
        }.get(workflow_type)
        if workflow_step_id:
            plan.append(library[workflow_step_id])
        return plan

    def _candidate_action_ids(
        self,
        question: str,
        memory: AgentMemorySnapshot,
        *,
        execution_profile: str | None = None,
    ) -> list[str]:
        ids = ["fetch_orders", "recommend"]
        urgent_score = self._urgent_score(question, None)

        if self._needs_collaboration(question) or urgent_score >= 2 or self._memory_prefers(memory, "协作"):
            ids.append("send_collaboration")
        if self._needs_handover(question) or self._memory_prefers(memory, "交班"):
            ids.append("create_handover")
        if (
            self._needs_document(question)
            or "闭环" in question
            or "留痕" in question
            or self._memory_prefers(memory, "文书")
        ):
            ids.append("create_document")
        if self._needs_order_request(question):
            ids.append("request_order")
        ids.extend(self._profile_action_ids(execution_profile))
        return self._dedupe_ids(ids)

    async def _plan_with_llm(
        self,
        *,
        question: str,
        goal: str,
        workflow_type: WorkflowType,
        memory: AgentMemorySnapshot,
        library: dict[str, AgentPlanItem],
    ) -> list[AgentPlanItem]:
        if workflow_type != WorkflowType.AUTONOMOUS_CARE:
            return []
        if not settings.agent_planner_llm_enabled:
            return []

        candidate_ids = ["fetch_orders", "recommend", "send_collaboration", "create_handover", "create_document", "request_order"]
        available_items = [library[item_id] for item_id in candidate_ids if item_id in library]
        available_text = "\n".join(
            f"- {item.id}: {item.title}。用途：{item.reason}" for item in available_items
        )
        prompt = (
            "你是护理场景 AI agent 的 Planner。"
            "请只从给定步骤中选择，返回严格 JSON，格式为 "
            '{"steps":[{"id":"step_id","reason":"为什么需要这一步"}]}。'
            "不要输出 markdown，不要发明新的 step id。"
            "review_memory 和 fetch_context 已经固定执行，无需返回。"
            "request_order 只能在用户明确要求补开/申请医嘱时选择。"
            "当问题或已知偏好呈现高风险、上报、通知医生、超时医嘱等信号时，应优先考虑 send_collaboration。"
            f"\n目标：{goal}"
            f"\n用户问题：{question or '未提供'}"
            f"\n历史记忆摘要：{memory.conversation_summary or '无'}"
            f"\n用户偏好：{'；'.join(memory.user_preferences) if memory.user_preferences else '无'}"
            f"\n候选步骤：\n{available_text}"
        )
        body = await local_structured_json(
            prompt,
            model=settings.local_llm_model_planner,
            timeout_sec=settings.agent_planner_timeout_sec,
        )
        if not isinstance(body, dict):
            return []

        steps = body.get("steps")
        if not isinstance(steps, list):
            return []

        planned: list[AgentPlanItem] = []
        seen: set[str] = set()
        for step in steps:
            if not isinstance(step, dict):
                continue
            item_id = str(step.get("id") or step.get("tool") or "").strip()
            template = library.get(item_id)
            if template is None or item_id in seen:
                continue
            seen.add(item_id)
            reason = str(step.get("reason") or "").strip() or template.reason
            title = str(step.get("title") or "").strip() or template.title
            planned.append(template.model_copy(update={"title": title, "reason": reason}))
        return planned

    def _merge_planned_items(
        self,
        *,
        heuristic_ids: list[str],
        planned_items: list[AgentPlanItem],
        library: dict[str, AgentPlanItem],
    ) -> list[AgentPlanItem]:
        merged: list[AgentPlanItem] = []
        seen: set[str] = set()

        for item in planned_items:
            if item.id in seen:
                continue
            seen.add(item.id)
            merged.append(item)

        for item_id in heuristic_ids:
            if item_id in seen:
                continue
            template = library.get(item_id)
            if template is None:
                continue
            seen.add(item_id)
            merged.append(template)
        return merged

    @staticmethod
    def _dedupe_ids(ids: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for item_id in ids:
            if item_id in seen:
                continue
            seen.add(item_id)
            deduped.append(item_id)
        return deduped

    @staticmethod
    def _trim_plan(plan: list[AgentPlanItem]) -> list[AgentPlanItem]:
        trimmed: list[AgentPlanItem] = []
        seen: set[str] = set()
        for item in plan:
            if item.id in seen:
                continue
            seen.add(item.id)
            trimmed.append(item)
        return trimmed[: settings.agent_planner_max_steps]

    def reflect(
        self,
        payload: WorkflowRequest,
        output: WorkflowOutput,
    ) -> dict[str, Any]:
        if output.workflow_type != WorkflowType.AUTONOMOUS_CARE:
            return {"followup_actions": [], "reason": "standard_workflow"}
        if output.pending_approvals:
            return {
                "followup_actions": [],
                "reason": "awaiting_approval",
                "pending_approvals": len(output.pending_approvals),
            }

        question = str(payload.user_input or "").strip()
        urgent_score = self._urgent_score(question, output)
        followups: list[AgentPlanItem] = []

        has_collab = any(item.kind == "collaboration_message" for item in output.artifacts)
        has_document = any(item.kind == "document_draft" for item in output.artifacts)
        has_handover = any(item.kind == "handover_draft" for item in output.artifacts)
        has_order_request = any(item.kind == "order_request" for item in output.artifacts)

        should_collaborate = (
            urgent_score >= 2
            or self._needs_collaboration(question)
            or self._has_collaboration_signal(output)
        )
        if should_collaborate and not has_collab:
            followups.append(
                AgentPlanItem(
                    id="send_collaboration",
                    title="补发协作通知",
                    tool="collaboration",
                    reason="反思发现存在高风险信号，但尚未形成协作闭环。",
                )
            )
        if ("留痕" in question or "闭环" in question or self._needs_document(question)) and not has_document:
            followups.append(
                AgentPlanItem(
                    id="create_document",
                    title="补生成文书草稿",
                    tool="document",
                    reason="反思认为需要留下可审核记录。",
                )
            )
        if self._needs_handover(question) and not has_handover:
            followups.append(
                AgentPlanItem(
                    id="create_handover",
                    title="补生成交班草稿",
                    tool="handover",
                    reason="用户要求交班联动，但当前结果尚未生成交班材料。",
                )
            )
        if self._needs_order_request(question) and not has_order_request:
            followups.append(
                AgentPlanItem(
                    id="request_order",
                    title="补创建医嘱请求",
                    tool="order_request",
                    reason="用户提出处置/补开诉求，但尚未形成请求单。",
                )
            )

        return {
            "followup_actions": followups,
            "urgent_score": urgent_score,
            "reason": "autonomous_reflection",
        }

    def finalize(self, request: WorkflowRequest, output: WorkflowOutput) -> WorkflowOutput:
        memory = agent_memory_store.remember(request, output)
        next_actions = list(output.next_actions)
        if not next_actions:
            next_actions = self._default_next_actions(output)
        if output.pending_approvals:
            next_actions = self._merge_unique_text(
                [f"等待人工审批：{item.title}" for item in output.pending_approvals if item.status == "pending"],
                next_actions,
            )
        enriched = output.model_copy(update={"memory": memory, "next_actions": next_actions[:6]})
        return self._enrich_structured_views(request, enriched, memory)

    def persist_finalized_run(self, output: WorkflowOutput) -> None:
        if not output.run_id:
            return
        existing = agent_run_store.get(output.run_id)
        tool_executions = list(existing.tool_executions) if existing else output.tool_executions
        if output.pending_approvals:
            agent_run_store.wait_for_approval(
                output.run_id,
                output,
                tool_executions=tool_executions,
            )
            return
        agent_run_store.complete(
            output.run_id,
            output,
            tool_executions=tool_executions,
        )

    async def run(
        self,
        payload: WorkflowRequest,
        *,
        helper: Any,
        workflow_type: WorkflowType,
        memory: AgentMemorySnapshot,
        plan: list[AgentPlanItem],
        prior_output: WorkflowOutput | None = None,
        runtime_engine: str = "state_machine",
    ) -> WorkflowOutput:
        run_id = self._start_or_resume_run(
            payload,
            workflow_type=workflow_type,
            memory=memory,
            plan=plan,
            runtime_engine=runtime_engine,
            prior_output=prior_output,
        )
        try:
            if workflow_type == WorkflowType.AUTONOMOUS_CARE:
                output = await self._run_autonomous(
                    payload,
                    helper=helper,
                    memory=memory,
                    plan=plan,
                    prior_output=prior_output,
                )
            else:
                output = await self._run_wrapped_workflow(
                    payload,
                    helper=helper,
                    memory=memory,
                    plan=plan,
                    workflow_type=workflow_type,
                )
        except Exception as exc:
            agent_run_store.fail(
                run_id,
                error=str(exc) or exc.__class__.__name__,
                runtime_engine=runtime_engine,
                steps=list(prior_output.steps) if prior_output else None,
                plan=plan,
            )
            raise

        output = output.model_copy(
            update={
                "run_id": run_id,
                "runtime_engine": runtime_engine,
                "execution_profile": payload.execution_profile or output.execution_profile,
                "mission_title": payload.mission_title or output.mission_title,
                "success_criteria": list(payload.success_criteria or output.success_criteria),
            }
        )
        agent_run_store.update(
            run_id,
            status="running",
            runtime_engine=runtime_engine,
            patient_id=output.patient_id,
            patient_name=output.patient_name,
            bed_no=output.bed_no,
            summary=output.summary,
            agent_goal=output.agent_goal,
            agent_mode=output.agent_mode,
            plan=output.plan,
            memory=output.memory or memory,
            artifacts=output.artifacts,
            specialist_profiles=output.specialist_profiles,
            hybrid_care_path=output.hybrid_care_path,
            data_capsule=output.data_capsule,
            health_graph=output.health_graph,
            reasoning_cards=output.reasoning_cards,
            next_actions=output.next_actions,
            steps=output.steps,
            tool_executions=output.tool_executions,
            pending_approvals=output.pending_approvals,
            retry_available=agent_run_store.has_retry_request(run_id),
            error=None,
        )
        return output

    def _start_or_resume_run(
        self,
        payload: WorkflowRequest,
        *,
        workflow_type: WorkflowType,
        memory: AgentMemorySnapshot,
        plan: list[AgentPlanItem],
        runtime_engine: str,
        prior_output: WorkflowOutput | None,
    ) -> str:
        if prior_output and prior_output.run_id:
            agent_run_store.update(
                prior_output.run_id,
                status="running",
                runtime_engine=runtime_engine,
                plan=plan,
                memory=memory,
                agent_goal=self._build_agent_goal(payload, workflow_type),
                agent_mode=payload.agent_mode or prior_output.agent_mode or "workflow",
            )
            return prior_output.run_id

        record = agent_run_store.start(
            payload,
            workflow_type=workflow_type,
            runtime_engine=runtime_engine,
            agent_goal=self._build_agent_goal(payload, workflow_type),
            agent_mode=payload.agent_mode or "workflow",
            plan=plan,
            memory=memory,
        )
        return record.id

    async def _run_wrapped_workflow(
        self,
        payload: WorkflowRequest,
        *,
        helper: Any,
        memory: AgentMemorySnapshot,
        plan: list[AgentPlanItem],
        workflow_type: WorkflowType,
    ) -> WorkflowOutput:
        payload = payload.model_copy(deep=True)
        payload.workflow_type = workflow_type

        if workflow_type == WorkflowType.HANDOVER:
            output = await helper._run_handover(payload)
            completed = {"fetch_context": "done" if output.context_hit else "failed", "create_handover": "done"}
        elif workflow_type == WorkflowType.RECOMMENDATION:
            output = await helper._run_recommendation(payload)
            completed = {"fetch_context": "done" if output.context_hit else "failed", "recommend": "done"}
        elif workflow_type == WorkflowType.DOCUMENT:
            output = await helper._run_document(payload)
            completed = {"fetch_context": "done" if output.context_hit else "failed", "create_document": "done"}
        else:
            output = await helper._run_voice(payload)
            completed = {"fetch_context": "done" if output.context_hit else "failed", "voice_assessment": "done"}

        enriched_steps = [
            AgentStep(
                agent="Planner Agent",
                status="done",
                output={"workflow_type": workflow_type.value, "goal": self._build_agent_goal(payload, workflow_type)},
            ),
            AgentStep(
                agent="Memory Agent",
                status="done" if memory.conversation_summary or memory.patient_facts else "skipped",
                output={
                    "patient_facts": len(memory.patient_facts),
                    "unresolved_tasks": len(memory.unresolved_tasks),
                },
            ),
            *output.steps,
            AgentStep(
                agent="Critic Agent",
                status="done",
                output={"followup_actions": 0, "reason": "standard_workflow"},
            ),
        ]
        return output.model_copy(
            update={
                "agent_goal": self._build_agent_goal(payload, workflow_type),
                "agent_mode": payload.agent_mode or "agentic_workflow",
                "plan": self._apply_plan_status(plan, completed),
                "memory": memory,
                "steps": enriched_steps,
                "tool_executions": [],
                "pending_approvals": [],
                "next_actions": self._default_next_actions(output),
            }
        )

    async def _run_autonomous(
        self,
        payload: WorkflowRequest,
        *,
        helper: Any,
        memory: AgentMemorySnapshot,
        plan: list[AgentPlanItem],
        prior_output: WorkflowOutput | None = None,
    ) -> WorkflowOutput:
        question = str(payload.user_input or "").strip()
        beds = helper._extract_beds(question)
        if payload.bed_no and payload.bed_no not in beds:
            beds.insert(0, payload.bed_no)
        ward_scope = helper._is_ward_scope(question, beds)

        current_steps = list(prior_output.steps) if prior_output else []
        if not current_steps:
            current_steps = [
                AgentStep(
                    agent="Planner Agent",
                    status="done",
                    output={"workflow_type": WorkflowType.AUTONOMOUS_CARE.value, "goal": self._build_agent_goal(payload, WorkflowType.AUTONOMOUS_CARE)},
                ),
                AgentStep(
                    agent="Memory Agent",
                    status="done" if memory.conversation_summary or memory.patient_facts else "skipped",
                    output={"conversation_summary": memory.conversation_summary[:80]},
                ),
            ]

        contexts = await helper._fetch_contexts(payload, beds, allow_ward_fallback=True)
        current_steps.append(
            AgentStep(
                agent="Patient Context Agent",
                status="done" if contexts else "failed",
                output={"context_count": len(contexts), "ward_scope": ward_scope},
            )
        )

        if not contexts:
            return WorkflowOutput(
                workflow_type=WorkflowType.AUTONOMOUS_CARE,
                summary=helper._ensure_question("还未定位到具体患者上下文，请补充床号或患者后再启动自动闭环。", question),
                findings=[],
                recommendations=[{"title": "示例：自动跟进12床，高风险就通知医生并生成交班。", "priority": 1}],
                confidence=0.28,
                review_required=True,
                context_hit=False,
                steps=current_steps,
                agent_goal=self._build_agent_goal(payload, WorkflowType.AUTONOMOUS_CARE),
                agent_mode=payload.agent_mode or "autonomous",
                plan=self._apply_plan_status(plan, {"fetch_context": "failed"}),
                memory=memory,
                next_actions=["补充床号或患者标识后重新发起自动闭环。"],
                tool_executions=[],
                pending_approvals=[],
                created_at=datetime.now(timezone.utc),
            )

        if ward_scope or len(contexts) > 1:
            return await self._run_autonomous_ward(
                payload,
                helper=helper,
                memory=memory,
                plan=plan,
                question=question,
                current_steps=current_steps,
                contexts=contexts,
            )

        return await self._run_autonomous_single(
            payload,
            helper=helper,
            memory=memory,
            plan=plan,
            question=question,
            current_steps=current_steps,
            context=contexts[0],
            prior_output=prior_output,
        )

    async def _run_autonomous_ward(
        self,
        payload: WorkflowRequest,
        *,
        helper: Any,
        memory: AgentMemorySnapshot,
        plan: list[AgentPlanItem],
        question: str,
        current_steps: list[AgentStep],
        contexts: list[dict[str, Any]],
    ) -> WorkflowOutput:
        ranked = sorted(
            [
                {
                    "patient_id": str(ctx.get("patient_id") or ""),
                    "bed_no": str(ctx.get("bed_no") or "-"),
                    "risk_score": helper._risk_score(ctx),
                }
                for ctx in contexts
            ],
            key=lambda item: item["risk_score"],
            reverse=True,
        )
        findings = [f"{row['bed_no']}床：风险分={row['risk_score']}" for row in ranked[:8]]
        recommendations = [{"title": f"优先处理 {row['bed_no']}床", "priority": 1} for row in ranked[:5]]
        artifacts: list[AgentArtifact] = []
        completed = {"fetch_context": "done", "fetch_orders": "skipped", "recommend": "done"}

        if self._plan_has_pending(plan, "create_handover"):
            batch = await helper._call_json(
                "POST",
                f"{settings.handover_service_url}/handover/batch-generate",
                payload={
                    "department_id": payload.department_id or settings.default_department_id,
                    "generated_by": payload.requested_by,
                },
                timeout=30,
            )
            if isinstance(batch, list) and batch:
                artifacts.append(
                    AgentArtifact(
                        kind="handover_batch",
                        title=f"已生成病区交班草稿 {len(batch)} 份",
                        summary="病区高风险患者交班草稿已生成，等待人工审核。",
                        metadata={"count": len(batch)},
                    )
                )
                completed["create_handover"] = "done"
            else:
                completed["create_handover"] = "failed"

        summary = "已完成病区自动巡检。"
        if findings:
            summary = f"{summary} 当前优先关注：{'、'.join([row['bed_no'] + '床' for row in ranked[:3]])}。"
        if artifacts:
            summary = f"{summary}{artifacts[0].title}。"

        current_steps.append(
            AgentStep(
                agent="Ward Coordination Agent",
                status="done",
                output={"top_beds": [row["bed_no"] for row in ranked[:3]]},
            )
        )
        return WorkflowOutput(
            workflow_type=WorkflowType.AUTONOMOUS_CARE,
            summary=helper._ensure_question(summary, question),
            findings=self._merge_unique_text(findings),
            recommendations=helper._normalize_recommendations(recommendations),
            confidence=0.82,
            review_required=True,
            context_hit=True,
            steps=current_steps,
            patient_id=None,
            patient_name=None,
            bed_no=None,
            agent_goal=self._build_agent_goal(payload, WorkflowType.AUTONOMOUS_CARE),
            agent_mode=payload.agent_mode or "autonomous",
            plan=self._apply_plan_status(plan, completed),
            memory=memory,
            artifacts=artifacts,
            next_actions=self._merge_unique_text(
                [rec.get("title") for rec in recommendations if isinstance(rec, dict)],
                [artifact.title for artifact in artifacts],
            )[:6],
            tool_executions=[],
            pending_approvals=[],
            created_at=datetime.now(timezone.utc),
        )

    async def _run_autonomous_single(
        self,
        payload: WorkflowRequest,
        *,
        helper: Any,
        memory: AgentMemorySnapshot,
        plan: list[AgentPlanItem],
        question: str,
        current_steps: list[AgentStep],
        context: dict[str, Any],
        prior_output: WorkflowOutput | None,
    ) -> WorkflowOutput:
        patient_id = str(context.get("patient_id") or payload.patient_id or "").strip()
        bed_no = str(context.get("bed_no") or payload.bed_no or "").strip() or None
        patient_name = str(context.get("patient_name") or "").strip() or None

        state: dict[str, Any] = {
            "patient_id": patient_id,
            "bed_no": bed_no,
            "patient_name": patient_name,
            "findings": list(prior_output.findings) if prior_output else helper._build_context_findings(context),
            "recommendations": list(prior_output.recommendations) if prior_output else [],
            "artifacts": list(prior_output.artifacts) if prior_output else [],
            "confidence": float(prior_output.confidence if prior_output else 0.7),
            "orders": None,
            "completed": {
                "fetch_context": "done",
                "fetch_orders": "skipped",
                "recommend": "skipped",
                "send_collaboration": "skipped",
                "create_handover": "skipped",
                "create_document": "skipped",
                "request_order": "skipped",
            },
            "tool_steps": [],
            "tool_executions": list(prior_output.tool_executions) if prior_output else [],
            "pending_approvals": [],
        }

        await self._execute_autonomous_plan(
            helper=helper,
            payload=payload,
            question=question,
            plan=plan,
            state=state,
        )

        recommendations = self._merge_recommendations(
            state["recommendations"],
            [{"title": artifact.title, "priority": 1} for artifact in state["artifacts"]],
        )
        summary = self._compose_autonomous_summary(
            question=question,
            patient_name=patient_name,
            bed_no=bed_no,
            memory=memory,
            findings=state["findings"],
            recommendations=recommendations,
            artifacts=state["artifacts"],
            orders=state["orders"],
        )
        if state["pending_approvals"]:
            summary = f"{summary} 等待人工审批：{'、'.join([item.title for item in state['pending_approvals'][:3]])}。"

        current_steps.extend(state["tool_steps"])
        current_steps.append(
            AgentStep(
                agent="Action Agent",
                status="done",
                output={"artifact_count": len(state["artifacts"])},
            )
        )
        return WorkflowOutput(
            workflow_type=WorkflowType.AUTONOMOUS_CARE,
            summary=helper._ensure_question(summary, question),
            findings=self._merge_unique_text(state["findings"]),
            recommendations=helper._normalize_recommendations(recommendations),
            confidence=min(max(float(state["confidence"]), 0.74), 0.93),
            review_required=True,
            context_hit=True,
            patient_id=patient_id or None,
            patient_name=patient_name,
            bed_no=bed_no,
            steps=current_steps,
            agent_goal=self._build_agent_goal(payload, WorkflowType.AUTONOMOUS_CARE),
            agent_mode=payload.agent_mode or "autonomous",
            plan=self._apply_plan_status(plan, state["completed"]),
            memory=memory,
            artifacts=state["artifacts"],
            next_actions=self._merge_unique_text(
                [f"等待人工审批：{item.title}" for item in state["pending_approvals"] if item.status == "pending"],
                [item.get("title") for item in recommendations if isinstance(item, dict)],
                [artifact.title for artifact in state["artifacts"]],
            )[:6],
            tool_executions=state["tool_executions"],
            pending_approvals=state["pending_approvals"],
            created_at=datetime.now(timezone.utc),
        )

    async def _execute_autonomous_plan(
        self,
        *,
        helper: Any,
        payload: WorkflowRequest,
        question: str,
        plan: list[AgentPlanItem],
        state: dict[str, Any],
    ) -> None:
        approved_actions = {str(item or "").strip() for item in payload.approved_actions if str(item or "").strip()}
        rejected_actions = {str(item or "").strip() for item in payload.rejected_actions if str(item or "").strip()}

        for item in plan:
            if item.id in {"review_memory", "fetch_context"}:
                continue
            if item.status != "pending":
                state["completed"][item.id] = item.status
                continue

            registered = self._tool_registry.get(item.id)
            if registered is None:
                state["completed"][item.id] = "skipped"
                continue

            if item.id in rejected_actions:
                state["completed"][item.id] = "rejected"
                state["tool_steps"].append(
                    AgentStep(
                        agent=registered.spec.agent,
                        status="rejected",
                        input={"tool": item.id, "title": item.title},
                        output={"reason": "rejected_by_human"},
                    )
                )
                continue

            if self._requires_approval(item.id) and item.id not in approved_actions:
                approval = self._build_approval_request(item=item, payload=payload, state=state)
                state["pending_approvals"].append(approval)
                state["completed"][item.id] = "approval_required"
                state["tool_steps"].append(
                    AgentStep(
                        agent=registered.spec.agent,
                        status="approval_required",
                        input={"tool": item.id, "title": item.title},
                        output={
                            "approval_id": approval.id,
                            "reason": approval.reason,
                        },
                    )
                )
                continue

            attempts = 0
            started_at = datetime.now(timezone.utc)
            status = "skipped"
            output: dict[str, Any] = {}
            while True:
                attempts += 1
                status, output = await self._tool_registry.execute(
                    item.id,
                    helper=helper,
                    payload=payload,
                    question=question,
                    state=state,
                )
                if status == "done":
                    break
                if not registered.spec.retryable or attempts > registered.spec.max_retries:
                    break
                output = {
                    **(output if isinstance(output, dict) else {}),
                    "retrying": True,
                    "attempt": attempts,
                }

            finished_at = datetime.now(timezone.utc)
            state["completed"][item.id] = status
            execution = AgentToolExecution(
                item_id=item.id,
                title=item.title,
                tool=item.tool,
                agent=registered.spec.agent,
                status=status,
                attempts=attempts,
                retryable=registered.spec.retryable,
                started_at=started_at,
                finished_at=finished_at,
                output=output if isinstance(output, dict) else {},
                error=str((output or {}).get("error") or "") or None,
            )
            state["tool_executions"].append(execution)
            state["tool_steps"].append(
                AgentStep(
                    agent=registered.spec.agent,
                    status=status,
                    input={
                        "tool": item.id,
                        "title": item.title,
                        "retryable": registered.spec.retryable,
                        "max_retries": registered.spec.max_retries,
                    },
                    output={
                        **(output if isinstance(output, dict) else {}),
                        "attempts": attempts,
                    },
                )
            )

    @staticmethod
    def _requires_approval(item_id: str) -> bool:
        return item_id in APPROVAL_TOOL_IDS

    def _build_approval_request(
        self,
        *,
        item: AgentPlanItem,
        payload: WorkflowRequest,
        state: dict[str, Any],
    ) -> AgentApprovalRequest:
        return AgentApprovalRequest(
            id=str(uuid.uuid4()),
            item_id=item.id,
            tool_id=item.tool,
            title=item.title,
            reason=item.reason or "This action requires human approval before execution.",
            created_at=datetime.now(timezone.utc),
            metadata={
                "patient_id": state.get("patient_id"),
                "patient_name": state.get("patient_name"),
                "bed_no": state.get("bed_no"),
                "requested_by": payload.requested_by,
            },
        )

    async def _tool_fetch_orders(
        self,
        *,
        helper: Any,
        payload: WorkflowRequest,
        question: str,
        state: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        orders = await helper._call_json(
            "GET",
            f"{settings.patient_context_service_url}/patients/{state['patient_id']}/orders",
            timeout=10,
        )
        state["orders"] = orders if isinstance(orders, dict) else None
        state["findings"] = self._merge_unique_text(state["findings"], self._order_findings(orders))
        if isinstance(orders, dict):
            return "done", {"order_signals": self._order_findings(orders)}
        return "failed", {"order_signals": [], "error": "orders_unavailable"}

    async def _tool_recommend(
        self,
        *,
        helper: Any,
        payload: WorkflowRequest,
        question: str,
        state: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        rec = await helper._call_json(
            "POST",
            f"{settings.recommendation_service_url}/recommendation/run",
            payload={
                "patient_id": state["patient_id"],
                "question": question or f"请给出{state['bed_no'] or '-'}床处置建议",
                "bed_no": state["bed_no"],
                "department_id": payload.department_id,
                "attachments": payload.attachments,
                "requested_by": payload.requested_by,
                "fast_mode": False,
            },
            timeout=32,
        )
        if not isinstance(rec, dict):
            state["recommendations"] = self._merge_recommendations(
                state["recommendations"],
                [{"title": "推荐服务暂不可用，请先人工复核风险。", "priority": 1}],
            )
            return "failed", {"recommendation_count": 0, "error": "recommendation_unavailable"}

        state["findings"] = self._merge_unique_text(state["findings"], rec.get("findings"))
        state["recommendations"] = self._merge_recommendations(state["recommendations"], rec.get("recommendations"))
        state["confidence"] = max(float(state["confidence"]), float(rec.get("confidence", 0.8) or 0.8))
        return "done", {"recommendation_count": len(state["recommendations"])}

    async def _tool_send_collaboration(
        self,
        *,
        helper: Any,
        payload: WorkflowRequest,
        question: str,
        state: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        artifact = await self._create_collaboration_artifact(
            helper=helper,
            payload=payload,
            patient_id=state["patient_id"],
            summary_hint=self._compose_summary_hint(
                state["patient_name"],
                state["bed_no"],
                state["findings"],
                state["recommendations"],
            ),
        )
        if artifact is None:
            return "failed", {"artifact": "collaboration_message", "error": "collaboration_unavailable"}
        state["artifacts"].append(artifact)
        return "done", {"artifact": artifact.title}

    async def _tool_create_handover(
        self,
        *,
        helper: Any,
        payload: WorkflowRequest,
        question: str,
        state: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        record = await helper._call_json(
            "POST",
            f"{settings.handover_service_url}/handover/generate",
            payload={"patient_id": state["patient_id"], "generated_by": payload.requested_by},
            timeout=20,
        )
        if not isinstance(record, dict):
            return "failed", {"artifact": "handover_draft", "error": "handover_unavailable"}
        artifact = AgentArtifact(
            kind="handover_draft",
            title="已生成交班草稿",
            reference_id=str(record.get("id") or "").strip() or None,
            summary=str(record.get("summary") or "").strip() or None,
        )
        state["artifacts"].append(artifact)
        return "done", {"artifact": artifact.title}

    async def _tool_create_document(
        self,
        *,
        helper: Any,
        payload: WorkflowRequest,
        question: str,
        state: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        draft = await helper._call_json(
            "POST",
            f"{settings.document_service_url}/document/draft",
            payload={
                "patient_id": state["patient_id"],
                "document_type": helper._infer_document_type(question),
                "spoken_text": question,
                "requested_by": payload.requested_by,
            },
            timeout=20,
        )
        if not isinstance(draft, dict):
            return "failed", {"artifact": "document_draft", "error": "document_unavailable"}
        draft_text = str(draft.get("draft_text") or "").strip()
        artifact = AgentArtifact(
            kind="document_draft",
            title="已生成护理文书草稿",
            reference_id=str(draft.get("id") or "").strip() or None,
            summary=(draft_text[:100] + ("..." if len(draft_text) > 100 else "")) if draft_text else None,
        )
        state["artifacts"].append(artifact)
        return "done", {"artifact": artifact.title}

    async def _tool_request_order(
        self,
        *,
        helper: Any,
        payload: WorkflowRequest,
        question: str,
        state: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        order_request = await helper._call_json(
            "POST",
            f"{settings.patient_context_service_url}/orders/request",
            payload={
                "patient_id": state["patient_id"],
                "requested_by": payload.requested_by,
                "title": self._build_order_request_title(question, state["bed_no"]),
                "details": self._build_order_request_details(question, state["findings"], state["recommendations"]),
                "priority": "P1" if self._urgent_score(question, None) >= 2 else "P2",
            },
            timeout=16,
        )
        if not isinstance(order_request, dict):
            return "failed", {"artifact": "order_request", "error": "order_request_unavailable"}
        artifact = AgentArtifact(
            kind="order_request",
            title="已创建医嘱请求",
            reference_id=str(order_request.get("id") or "").strip() or None,
            summary=str(order_request.get("title") or "").strip() or None,
        )
        state["artifacts"].append(artifact)
        return "done", {"artifact": artifact.title}

    @staticmethod
    def _tool_agent_name(item_id: str) -> str:
        return {
            "fetch_orders": "Order Signal Agent",
            "recommend": "Recommendation Agent",
            "send_collaboration": "Collaboration Agent",
            "create_handover": "Handover Agent",
            "create_document": "Document Agent",
            "request_order": "Order Request Agent",
        }.get(item_id, "Action Agent")

    async def _create_collaboration_artifact(
        self,
        *,
        helper: Any,
        payload: WorkflowRequest,
        patient_id: str,
        summary_hint: str,
    ) -> AgentArtifact | None:
        digest = await helper._call_json(
            "POST",
            f"{settings.collaboration_service_url}/collab/assistant/digest",
            payload={
                "user_id": payload.requested_by,
                "patient_id": patient_id,
                "note": summary_hint[:120],
            },
            timeout=12,
        )
        message_text = summary_hint
        if isinstance(digest, dict):
            message_text = str(digest.get("generated_message") or summary_hint).strip() or summary_hint

        accounts = await helper._call_json(
            "GET",
            f"{settings.collaboration_service_url}/collab/accounts",
            params={"query": "doctor", "exclude_user_id": payload.requested_by},
            timeout=8,
        )
        if not isinstance(accounts, list) or not accounts:
            return None

        target = accounts[0] if isinstance(accounts[0], dict) else {}
        contact_user_id = str(target.get("id") or target.get("user_id") or "").strip()
        target_name = str(target.get("full_name") or target.get("account") or "值班医生").strip()
        if not contact_user_id:
            return None

        session = await helper._call_json(
            "POST",
            f"{settings.collaboration_service_url}/collab/direct/open",
            payload={
                "user_id": payload.requested_by,
                "contact_user_id": contact_user_id,
                "patient_id": patient_id,
            },
            timeout=8,
        )
        if not isinstance(session, dict):
            return None

        session_id = str(session.get("id") or "").strip()
        sent = await helper._call_json(
            "POST",
            f"{settings.collaboration_service_url}/collab/direct/message",
            payload={
                "session_id": session_id,
                "sender_id": payload.requested_by,
                "content": message_text[:260],
                "message_type": "text",
                "attachment_refs": [],
            },
            timeout=8,
        )
        if not isinstance(sent, dict):
            return None

        return AgentArtifact(
            kind="collaboration_message",
            title=f"已通知{target_name}",
            reference_id=str(sent.get("id") or "").strip() or session_id or None,
            summary=message_text[:120],
            metadata={"session_id": session_id, "contact_user_id": contact_user_id},
        )

    def _compose_autonomous_summary(
        self,
        *,
        question: str,
        patient_name: str | None,
        bed_no: str | None,
        memory: AgentMemorySnapshot,
        findings: list[str],
        recommendations: list[dict[str, Any]],
        artifacts: list[AgentArtifact],
        orders: Any,
    ) -> str:
        subject = f"{bed_no or '-'}床"
        if patient_name:
            subject = f"{subject}（{patient_name}）"

        parts = [f"{subject}自动闭环已完成初步分析。"]
        if memory.conversation_summary:
            parts.append(f"已参考历史记忆：{memory.conversation_summary[:80]}。")
        if findings:
            parts.append(f"当前重点：{'；'.join(findings[:3])}。")
        order_brief = self._order_brief(orders)
        if order_brief:
            parts.append(f"医嘱状态：{order_brief}。")
        if recommendations:
            top_actions = [str(item.get('title') or '').strip() for item in recommendations[:3] if isinstance(item, dict)]
            top_actions = [item for item in top_actions if item]
            if top_actions:
                parts.append(f"建议动作：{'、'.join(top_actions)}。")
        if artifacts:
            parts.append(f"已执行动作：{'、'.join([item.title for item in artifacts[:3]])}。")
        if not artifacts and is_autonomous_request(question):
            parts.append("当前未直接生成外部动作，仍需护士人工确认后继续。")
        return "".join(parts)

    @staticmethod
    def _planning_brief(payload: WorkflowRequest) -> str:
        parts = [str(payload.user_input or "").strip()]
        if payload.mission_title:
            parts.append(f"任务标题：{payload.mission_title}")
        if payload.success_criteria:
            criteria = [str(item).strip() for item in payload.success_criteria if str(item).strip()]
            if criteria:
                parts.append("成功标准：" + "；".join(criteria))
        if payload.operator_notes:
            parts.append(f"操作备注：{payload.operator_notes}")
        return "\n".join([part for part in parts if part]).strip()

    @staticmethod
    def _mission_goal_hint(payload: WorkflowRequest) -> str:
        hints: list[str] = []
        if payload.mission_title:
            hints.append(f"本次任务目标是“{payload.mission_title}”")
        if payload.success_criteria:
            criteria = [str(item).strip() for item in payload.success_criteria if str(item).strip()]
            if criteria:
                hints.append("成功标准包括" + "、".join(criteria[:4]))
        return "，".join(hints)

    def _build_agent_goal(self, payload: WorkflowRequest, workflow_type: WorkflowType) -> str:
        base_goal = self._build_goal(payload, workflow_type)
        mission_hint = self._mission_goal_hint(payload)
        if not mission_hint:
            return base_goal
        return f"{base_goal}，{mission_hint}"

    def _build_goal(self, payload: WorkflowRequest, workflow_type: WorkflowType) -> str:
        profile_hint = self._execution_profile_goal_hint(payload.execution_profile)
        if workflow_type == WorkflowType.AUTONOMOUS_CARE:
            goal = "围绕患者风险完成感知、决策、协作与留痕闭环"
            return f"{goal}，{profile_hint}" if profile_hint else goal
        if workflow_type == WorkflowType.HANDOVER:
            goal = "沉淀可审核的交班材料"
            return f"{goal}，{profile_hint}" if profile_hint else goal
        if workflow_type == WorkflowType.RECOMMENDATION:
            goal = "输出结构化建议和升级条件"
            return f"{goal}，{profile_hint}" if profile_hint else goal
        if workflow_type == WorkflowType.DOCUMENT:
            goal = "生成可复核的护理文书草稿"
            return f"{goal}，{profile_hint}" if profile_hint else goal
        goal = "完成患者或病区风险问询"
        return f"{goal}，{profile_hint}" if profile_hint else goal

    @staticmethod
    def _normalized_execution_profile(execution_profile: str | None) -> str | None:
        profile = str(execution_profile or "").strip().lower()
        return profile or None

    def _workflow_for_profile(
        self,
        execution_profile: str | None,
        workflow_type: WorkflowType,
    ) -> WorkflowType | None:
        profile = self._normalized_execution_profile(execution_profile)
        if profile == "full_loop":
            return WorkflowType.AUTONOMOUS_CARE
        if profile == "document" and workflow_type == WorkflowType.VOICE_INQUIRY:
            return WorkflowType.DOCUMENT
        if profile == "escalate" and workflow_type == WorkflowType.VOICE_INQUIRY:
            return WorkflowType.RECOMMENDATION
        return None

    def _profile_action_ids(self, execution_profile: str | None) -> list[str]:
        profile = self._normalized_execution_profile(execution_profile)
        return list(PROFILE_ACTIONS.get(profile or "", []))

    def _execution_profile_goal_hint(self, execution_profile: str | None) -> str:
        profile = self._normalized_execution_profile(execution_profile)
        hints = {
            "observe": "优先整理异常体征、风险标签与下一步观察重点",
            "escalate": "优先识别升级信号并准备医生协作摘要",
            "document": "优先沉淀交班与护理文书留痕",
            "full_loop": "优先推动多步骤闭环并在关键节点等待人工审批",
        }
        return hints.get(profile or "", "")

    def _enrich_structured_views(
        self,
        request: WorkflowRequest,
        output: WorkflowOutput,
        memory: AgentMemorySnapshot,
    ) -> WorkflowOutput:
        specialist_profiles = output.specialist_profiles or self._build_specialist_profiles(request, output, memory)
        hybrid_care_path = output.hybrid_care_path or self._build_hybrid_care_path(request, output)
        data_capsule = output.data_capsule or self._build_data_capsule(request, output, memory)
        health_graph = output.health_graph or self._build_health_graph(request, output, data_capsule)
        reasoning_cards = output.reasoning_cards or self._build_reasoning_cards(output, memory)
        return output.model_copy(
            update={
                "specialist_profiles": specialist_profiles,
                "hybrid_care_path": hybrid_care_path,
                "data_capsule": data_capsule,
                "health_graph": health_graph,
                "reasoning_cards": reasoning_cards,
            }
        )

    def _build_specialist_profiles(
        self,
        request: WorkflowRequest,
        output: WorkflowOutput,
        memory: AgentMemorySnapshot,
    ) -> list[SpecialistDigitalTwin]:
        text = self._structured_context_text(request, output, memory)
        profile = self._normalized_execution_profile(output.execution_profile or request.execution_profile) or "observe"
        bed_no = output.bed_no or request.bed_no or "-"
        profiles = [
            SpecialistDigitalTwin(
                id="care_orchestrator",
                title="护理总控代理",
                role="总控编排",
                focus="汇总床旁信号、审批状态与执行顺序。",
                status="active",
                reason=f"当前任务围绕{bed_no}床展开，需要稳定的主控视角。",
                next_action=output.next_actions[0] if output.next_actions else None,
            )
        ]
        if profile in {"escalate", "full_loop"} or self._contains_any(
            text, "doctor", "escalat", "notify", "协作", "上报", "会诊", "高危", "overdue"
        ):
            profiles.append(
                SpecialistDigitalTwin(
                    id="risk_bridge",
                    title="风险升级代理",
                    role="协作桥接",
                    focus="把异常体征整理成可沟通的升级摘要。",
                    status="active" if output.pending_approvals else "recommended",
                    reason="当前任务带有升级协作信号，适合提前准备人工介入依据。",
                    next_action="确认是否触发医生协作与人工复核",
                )
            )
        if profile in {"document", "full_loop"} or self._contains_any(
            text, "document", "note", "handover", "文书", "交班", "记录"
        ):
            profiles.append(
                SpecialistDigitalTwin(
                    id="record_keeper",
                    title="记录沉淀代理",
                    role="文书留痕",
                    focus="把建议沉淀成护理记录、交接草稿和审批留痕。",
                    status="recommended",
                    reason="当前任务需要把执行结果转成可审阅材料。",
                    next_action="同步生成交接摘要与记录草稿",
                )
            )
        if self._contains_any(text, "饮食", "营养", "血糖", "膳食", "food", "nutrition"):
            profiles.append(
                SpecialistDigitalTwin(
                    id="nutrition_support",
                    title="营养支持代理",
                    role="照护支持",
                    focus="关注饮食限制、摄入风险和代谢信号。",
                    status="recommended",
                    reason="任务文本或患者事实中包含营养/代谢相关线索。",
                    next_action="核对饮食禁忌与代谢风险提示",
                )
            )
        if self._contains_any(text, "运动", "活动", "跌倒", "康复", "mobility", "rehab", "exercise"):
            profiles.append(
                SpecialistDigitalTwin(
                    id="mobility_support",
                    title="活动恢复代理",
                    role="恢复支持",
                    focus="关注活动耐量、跌倒风险和恢复节奏。",
                    status="recommended",
                    reason="当前任务涉及活动恢复或床旁安全管理。",
                    next_action="补充活动耐量和安全提醒",
                )
            )
        if profile == "full_loop" or self._contains_any(text, "follow", "随访", "宣教", "复测", "出院", "慢病"):
            profiles.append(
                SpecialistDigitalTwin(
                    id="followup_link",
                    title="随访连接代理",
                    role="延续照护",
                    focus="承接复测、宣教和后续跟进事项。",
                    status="recommended",
                    reason="当前任务需要把当次处置延伸到后续追踪。",
                    next_action="把下一步动作收敛成随访任务单",
                )
            )
        return profiles[:5]

    def _build_hybrid_care_path(
        self,
        request: WorkflowRequest,
        output: WorkflowOutput,
    ) -> list[HybridCareStage]:
        awaiting_approval = any(item.status == "pending" for item in output.pending_approvals)
        has_collaboration = self._has_collaboration_signal(output) or any(
            artifact.kind == "collaboration_message" for artifact in output.artifacts
        )
        has_records = any(artifact.kind in {"handover", "document_draft"} for artifact in output.artifacts)
        return [
            HybridCareStage(
                id="task_intake",
                title="任务接收",
                status="done",
                owner="护理总控代理",
                summary=request.mission_title or "已接收当前问题与任务约束。",
            ),
            HybridCareStage(
                id="bedside_assessment",
                title="床旁研判",
                status="done" if output.findings or output.recommendations else "active",
                owner="风险扫描",
                summary=self._short_text((output.findings[0] if output.findings else output.summary), 100),
            ),
            HybridCareStage(
                id="human_gate",
                title="人工闸门",
                status="active" if awaiting_approval else ("done" if has_collaboration or output.review_required else "pending"),
                owner="责任护士 / 医生",
                summary="敏感动作进入审批或人工复核；未触发时保持待命。",
            ),
            HybridCareStage(
                id="execution_recycle",
                title="执行回收",
                status="done" if has_records or output.artifacts else ("active" if output.next_actions else "pending"),
                owner="执行队列",
                summary="将建议、文书与后续任务重新汇总回本次 run。",
            ),
        ]

    def _build_data_capsule(
        self,
        request: WorkflowRequest,
        output: WorkflowOutput,
        memory: AgentMemorySnapshot,
    ) -> HealthDataCapsule:
        created = output.created_at.astimezone(timezone.utc).strftime("%Y%m%d%H%M")
        event_summary = self._merge_unique_text(
            request.mission_title,
            output.summary,
            output.findings[:3],
            [str(item.get("title") or "").strip() for item in output.recommendations[:3] if isinstance(item, dict)],
            [artifact.title for artifact in output.artifacts[:3]],
        )[:6]
        time_axis = self._merge_unique_text(
            f"current_run:{created}",
            memory.last_actions[:3],
            [f"pending_gate:{item.title}" for item in output.pending_approvals if item.status == "pending"],
            output.next_actions[:2],
        )[:6]
        risk_factors = [
            item
            for item in self._merge_unique_text(output.findings, memory.patient_facts, output.next_actions)
            if self._contains_any(
                item,
                "风险",
                "异常",
                "高危",
                "urgent",
                "overdue",
                "review",
                "复核",
                "notify",
                "升级",
            )
        ][:6]
        if not risk_factors and output.review_required:
            risk_factors = ["当前结果仍需人工复核后再闭环执行。"]
        return HealthDataCapsule(
            patient_id=output.patient_id or request.patient_id,
            version=f"capsule-{created}",
            event_summary=event_summary,
            time_axis=time_axis,
            data_layers=[
                "任务意图层：记录本次目标、成功标准与操作备注。",
                "风险信号层：沉淀异常观察、重点 findings 与需关注阈值。",
                "执行记录层：保留计划、工具调用与产出物。",
                "人工闸门层：追踪审批、复核与后续动作。",
            ],
            risk_factors=risk_factors,
        )

    def _build_health_graph(
        self,
        request: WorkflowRequest,
        output: WorkflowOutput,
        data_capsule: HealthDataCapsule,
    ) -> HealthGraphSnapshot:
        patient_node = output.patient_name or output.patient_id or request.patient_id or "current_patient"
        risk_nodes = [f"risk:{item}" for item in data_capsule.risk_factors[:3]]
        action_nodes = [
            f"action:{str(item.get('title') or '').strip()}"
            for item in output.recommendations[:3]
            if isinstance(item, dict) and str(item.get("title") or "").strip()
        ]
        artifact_nodes = [f"artifact:{artifact.title}" for artifact in output.artifacts[:2] if artifact.title.strip()]
        nodes = self._merge_unique_text(f"patient:{patient_node}", risk_nodes, action_nodes, artifact_nodes)[:8]
        edges: list[str] = []
        for risk in risk_nodes[:3]:
            edges.append(f"patient:{patient_node} -> {risk}")
        for index, action in enumerate(action_nodes[:3]):
            source = risk_nodes[index] if index < len(risk_nodes) else f"patient:{patient_node}"
            edges.append(f"{source} -> {action}")
        for artifact in artifact_nodes[:2]:
            if action_nodes:
                edges.append(f"{action_nodes[0]} -> {artifact}")
        dynamic_updates = self._merge_unique_text(
            output.next_actions[:3],
            [f"approval:{item.title}" for item in output.pending_approvals if item.status == "pending"],
            data_capsule.time_axis[:2],
        )[:6]
        return HealthGraphSnapshot(nodes=nodes, edges=edges[:8], dynamic_updates=dynamic_updates)

    def _build_reasoning_cards(
        self,
        output: WorkflowOutput,
        memory: AgentMemorySnapshot,
    ) -> list[ReasoningCard]:
        recommendation_titles = [
            str(item.get("title") or "").strip()
            for item in output.recommendations[:3]
            if isinstance(item, dict) and str(item.get("title") or "").strip()
        ]
        cards = [
            ReasoningCard(
                mode="signal_scan",
                title="风险扫描",
                summary=self._short_text(
                    "；".join(output.findings[:3]) or output.summary or "已完成本轮床旁信号梳理。",
                    120,
                ),
                confidence=output.confidence,
            ),
            ReasoningCard(
                mode="counter_check",
                title="逆向校核",
                summary=self._short_text(
                    "；".join(memory.patient_facts[:2] + output.findings[:2]) or "结合既往事实进行交叉核对。",
                    120,
                ),
                confidence=max(0.0, min(1.0, output.confidence - 0.06)),
            ),
            ReasoningCard(
                mode="action_alignment",
                title="行动对齐",
                summary=self._short_text(
                    "；".join(recommendation_titles[:3]) or "建议已对齐到本次目标与执行姿态。",
                    120,
                ),
                confidence=output.confidence,
            ),
        ]
        if output.pending_approvals or output.review_required:
            cards.append(
                ReasoningCard(
                    mode="human_gate",
                    title="人工介入依据",
                    summary=self._short_text(
                        "；".join(
                            [item.title for item in output.pending_approvals if item.title]
                            or ["当前结果仍需人工复核后再推进敏感动作。"]
                        ),
                        120,
                    ),
                    confidence=max(0.0, min(1.0, output.confidence - 0.1)),
                )
            )
        return cards[:4]

    @staticmethod
    def _contains_any(text: str | None, *tokens: str) -> bool:
        haystack = str(text or "").strip().lower()
        return any(str(token or "").lower() in haystack for token in tokens if str(token or "").strip())

    def _structured_context_text(
        self,
        request: WorkflowRequest,
        output: WorkflowOutput,
        memory: AgentMemorySnapshot,
    ) -> str:
        recommendation_titles = [
            str(item.get("title") or "").strip()
            for item in output.recommendations
            if isinstance(item, dict) and str(item.get("title") or "").strip()
        ]
        parts = [
            request.user_input,
            request.mission_title,
            request.operator_notes,
            output.summary,
            " ".join(output.findings),
            " ".join(recommendation_titles),
            " ".join(memory.patient_facts),
            " ".join(memory.unresolved_tasks),
            " ".join(output.next_actions),
        ]
        return " ".join(part for part in parts if part)

    @staticmethod
    def _short_text(text: str | None, limit: int = 120) -> str:
        value = str(text or "").strip()
        if len(value) <= limit:
            return value
        return value[: limit - 1].rstrip() + "…"

    def _urgent_score(self, question: str, output: WorkflowOutput | None) -> int:
        score = 0
        low = question.lower()
        if any(token in low for token in URGENT_KW):
            score += 2
        if output is not None:
            text = " ".join(output.findings + [output.summary]).lower()
            if "超时医嘱" in text or "高警示" in text or "上报" in text:
                score += 1
            if any(token in text for token in URGENT_KW):
                score += 1
        return score

    @staticmethod
    def _memory_prefers(memory: AgentMemorySnapshot, keyword: str) -> bool:
        return any(keyword in item for item in memory.user_preferences)

    @staticmethod
    def _has_collaboration_signal(output: WorkflowOutput) -> bool:
        phrases = (
            "上报",
            "通知医生",
            "联系医生",
            "值班医生",
            "提醒医生",
            "协作",
            "notify doctor",
            "doctor on duty",
            "escalate",
            "overdue",
        )
        text_parts = [output.summary, *output.findings]
        text_parts.extend(
            str(item.get("title") or "").strip()
            for item in output.recommendations
            if isinstance(item, dict)
        )
        joined = " ".join(part for part in text_parts if part).lower()
        return any(phrase in joined for phrase in phrases)

    @staticmethod
    def _needs_collaboration(question: str) -> bool:
        return any(token in question for token in COLLAB_KW)

    @staticmethod
    def _needs_document(question: str) -> bool:
        return any(token in question for token in DOC_KW)

    @staticmethod
    def _needs_handover(question: str) -> bool:
        return any(token in question for token in HANDOVER_KW)

    @staticmethod
    def _needs_order_request(question: str) -> bool:
        return any(token in question for token in ORDER_KW if token not in {"执行", "超时", "到时"})

    @staticmethod
    def _plan_has_pending(plan: list[AgentPlanItem], item_id: str) -> bool:
        return any(item.id == item_id and item.status == "pending" for item in plan)

    @staticmethod
    def _apply_plan_status(plan: list[AgentPlanItem], status_map: dict[str, str]) -> list[AgentPlanItem]:
        updated: list[AgentPlanItem] = []
        for item in plan:
            updated.append(item.model_copy(update={"status": status_map.get(item.id, item.status)}))
        return updated

    @staticmethod
    def _merge_followup_plan(plan: list[AgentPlanItem], followups: list[AgentPlanItem]) -> list[AgentPlanItem]:
        merged = list(plan)
        existing_ids = {item.id for item in merged}
        for followup in followups:
            if followup.id in existing_ids:
                merged = [
                    item.model_copy(update={"status": "pending"}) if item.id == followup.id else item
                    for item in merged
                ]
                continue
            merged.append(followup)
        return merged

    @staticmethod
    def _merge_unique_text(*groups: Any) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for group in groups:
            if not group:
                continue
            if not isinstance(group, list):
                group = [group]
            for item in group:
                text = str(item or "").strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                merged.append(text)
        return merged

    def _merge_recommendations(self, *groups: Any) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for group in groups:
            if not group:
                continue
            if not isinstance(group, list):
                group = [group]
            for item in group:
                if isinstance(item, dict):
                    title = str(item.get("title") or item.get("action") or "").strip()
                    priority = int(item.get("priority", 2) or 2)
                else:
                    title = str(item or "").strip()
                    priority = 2
                if not title or title in seen:
                    continue
                seen.add(title)
                merged.append({"title": title, "priority": priority})
        return merged

    @staticmethod
    def _order_findings(orders: Any) -> list[str]:
        if not isinstance(orders, dict):
            return []
        stats = orders.get("stats") if isinstance(orders.get("stats"), dict) else {}
        findings: list[str] = []
        pending = int(stats.get("pending", 0) or 0)
        due_30m = int(stats.get("due_30m", 0) or 0)
        overdue = int(stats.get("overdue", 0) or 0)
        high_alert = int(stats.get("high_alert", 0) or 0)
        if pending > 0:
            findings.append(f"待执行医嘱 {pending} 项")
        if due_30m > 0:
            findings.append(f"{due_30m} 项医嘱 30 分钟内到时")
        if overdue > 0:
            findings.append(f"存在 {overdue} 项超时医嘱")
        if high_alert > 0:
            findings.append(f"存在 {high_alert} 项高警示医嘱")
        return findings

    def _order_brief(self, orders: Any) -> str:
        findings = self._order_findings(orders)
        return "；".join(findings[:3])

    @staticmethod
    def _compose_summary_hint(
        patient_name: str | None,
        bed_no: str | None,
        findings: list[str],
        recommendations: list[dict[str, Any]],
    ) -> str:
        subject = f"{bed_no or '-'}床"
        if patient_name:
            subject = f"{subject}（{patient_name}）"
        actions = [str(item.get("title") or "").strip() for item in recommendations[:2] if isinstance(item, dict)]
        actions = [item for item in actions if item]
        parts = [f"{subject}需要关注。"]
        if findings:
            parts.append(f"重点：{'；'.join(findings[:2])}。")
        if actions:
            parts.append(f"建议：{'、'.join(actions)}。")
        return "".join(parts)

    @staticmethod
    def _build_order_request_title(question: str, bed_no: str | None) -> str:
        if "补开" in question:
            return f"{bed_no or '-'}床补开医嘱请求"
        if "镇痛" in question:
            return f"{bed_no or '-'}床镇痛处置请求"
        return f"{bed_no or '-'}床护理处置医嘱请求"

    @staticmethod
    def _build_order_request_details(
        question: str,
        findings: list[str],
        recommendations: list[dict[str, Any]],
    ) -> str:
        summary = [f"用户诉求：{question}"]
        if findings:
            summary.append(f"当前发现：{'；'.join(findings[:3])}")
        actions = [str(item.get("title") or "").strip() for item in recommendations[:3] if isinstance(item, dict)]
        actions = [item for item in actions if item]
        if actions:
            summary.append(f"建议动作：{'；'.join(actions)}")
        return "。".join(summary)

    @staticmethod
    def _default_next_actions(output: WorkflowOutput) -> list[str]:
        if output.pending_approvals:
            return [
                f"等待人工审批：{item.title}"
                for item in output.pending_approvals[:4]
                if item.status == "pending"
            ]
        actions = [
            str(item.get("title") or "").strip()
            for item in output.recommendations[:4]
            if isinstance(item, dict) and str(item.get("title") or "").strip()
        ]
        if not actions and output.review_required:
            actions.append("人工复核当前输出后再执行。")
        return actions


agentic_orchestrator = AgenticOrchestrator()
