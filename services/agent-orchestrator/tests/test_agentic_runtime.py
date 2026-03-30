from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.schemas.workflow import (  # noqa: E402
    AgentApprovalRequest,
    AgentArtifact,
    AgentMemorySnapshot,
    AgentPlanItem,
    WorkflowOutput,
    WorkflowRequest,
    WorkflowType,
)
from app.services.agentic_orchestrator import agentic_orchestrator, is_autonomous_request  # noqa: E402


class AgenticRuntimeTests(unittest.TestCase):
    def test_autonomous_request_detection(self) -> None:
        self.assertTrue(is_autonomous_request("autonomous follow up bed 12 and notify doctor"))
        self.assertTrue(is_autonomous_request("agent please notify doctor and create document"))
        self.assertFalse(is_autonomous_request("show me bed 12 status"))

    def test_build_plan_for_autonomous_care_contains_closure_tools(self) -> None:
        payload = WorkflowRequest(
            workflow_type=WorkflowType.AUTONOMOUS_CARE,
            patient_id="p-001",
            user_input="autonomous follow up bed 12, notify doctor, handover, and document it",
            requested_by="u_linmeili",
        )
        memory = AgentMemorySnapshot()
        plan = asyncio.run(agentic_orchestrator.build_plan(payload, WorkflowType.AUTONOMOUS_CARE, memory))
        ids = {item.id for item in plan}
        self.assertIn("fetch_context", ids)
        self.assertIn("fetch_orders", ids)
        self.assertIn("recommend", ids)
        self.assertIn("send_collaboration", ids)
        self.assertIn("create_handover", ids)
        self.assertIn("create_document", ids)

    def test_full_loop_execution_profile_forces_closure_actions(self) -> None:
        payload = WorkflowRequest(
            workflow_type=WorkflowType.AUTONOMOUS_CARE,
            patient_id="p-001",
            user_input="follow up bed 12",
            requested_by="u_linmeili",
            execution_profile="full_loop",
        )
        memory = AgentMemorySnapshot()
        plan = asyncio.run(agentic_orchestrator.build_plan(payload, WorkflowType.AUTONOMOUS_CARE, memory))
        ids = {item.id for item in plan}
        self.assertIn("send_collaboration", ids)
        self.assertIn("create_handover", ids)
        self.assertIn("create_document", ids)

    def test_execution_profile_can_coerce_workflow_route(self) -> None:
        async def fallback_route(_: str) -> WorkflowType:
            return WorkflowType.VOICE_INQUIRY

        payload = WorkflowRequest(
            workflow_type=WorkflowType.VOICE_INQUIRY,
            patient_id="p-001",
            user_input="show me bed 12 status",
            execution_profile="document",
        )
        routed = asyncio.run(agentic_orchestrator.route_workflow(payload, fallback_route))
        self.assertEqual(routed, WorkflowType.DOCUMENT)

    def test_planning_brief_can_trigger_autonomous_route(self) -> None:
        async def fallback_route(_: str) -> WorkflowType:
            return WorkflowType.VOICE_INQUIRY

        payload = WorkflowRequest(
            workflow_type=WorkflowType.VOICE_INQUIRY,
            patient_id="p-001",
            user_input="follow up bed 12",
            mission_title="夜班闭环跟进",
            success_criteria=["通知医生", "生成交班草稿"],
        )
        routed = asyncio.run(agentic_orchestrator.route_workflow(payload, fallback_route))
        self.assertEqual(routed, WorkflowType.AUTONOMOUS_CARE)

    def test_build_agent_goal_includes_mission_context(self) -> None:
        payload = WorkflowRequest(
            workflow_type=WorkflowType.RECOMMENDATION,
            patient_id="p-001",
            user_input="review bed 12",
            mission_title="梳理升级风险",
            success_criteria=["明确是否需要上报", "给出下一步观察重点"],
            execution_profile="escalate",
        )
        goal = agentic_orchestrator._build_agent_goal(payload, WorkflowType.RECOMMENDATION)
        self.assertIn("梳理升级风险", goal)
        self.assertIn("明确是否需要上报", goal)

    def test_reflect_adds_collaboration_when_output_requests_escalation(self) -> None:
        payload = WorkflowRequest(
            workflow_type=WorkflowType.AUTONOMOUS_CARE,
            patient_id="p-001",
            user_input="autonomous follow up bed 12",
            requested_by="u_linmeili",
        )
        output = WorkflowOutput(
            workflow_type=WorkflowType.AUTONOMOUS_CARE,
            summary="Bed 12 has overdue orders and should be escalated.",
            findings=["There are 2 overdue orders.", "Escalation is recommended."],
            recommendations=[{"title": "Immediately notify doctor on duty", "priority": 1}],
            confidence=0.86,
            review_required=True,
            context_hit=True,
            patient_id="p-001",
            patient_name="Test Patient",
            bed_no="12",
            artifacts=[],
            created_at=datetime.now(timezone.utc),
        )
        critique = agentic_orchestrator.reflect(payload, output)
        followup_ids = {item.id for item in critique["followup_actions"]}
        self.assertIn("send_collaboration", followup_ids)

    def test_reflect_stops_when_waiting_for_approval(self) -> None:
        payload = WorkflowRequest(
            workflow_type=WorkflowType.AUTONOMOUS_CARE,
            patient_id="p-001",
            user_input="autonomous follow up bed 12",
            requested_by="u_linmeili",
        )
        output = WorkflowOutput(
            workflow_type=WorkflowType.AUTONOMOUS_CARE,
            summary="Waiting for approval.",
            findings=[],
            recommendations=[],
            confidence=0.8,
            review_required=True,
            context_hit=True,
            patient_id="p-001",
            bed_no="12",
            pending_approvals=[
                AgentApprovalRequest(
                    id="approval-1",
                    item_id="send_collaboration",
                    tool_id="collaboration",
                    title="Notify doctor",
                    created_at=datetime.now(timezone.utc),
                )
            ],
            created_at=datetime.now(timezone.utc),
        )
        critique = agentic_orchestrator.reflect(payload, output)
        self.assertEqual(critique["reason"], "awaiting_approval")
        self.assertEqual(critique["followup_actions"], [])

    def test_default_next_actions_prefers_recommendations(self) -> None:
        output = WorkflowOutput(
            workflow_type=WorkflowType.RECOMMENDATION,
            summary="done",
            findings=[],
            recommendations=[
                {"title": "Prioritize bed 12", "priority": 1},
                {"title": "Review vitals", "priority": 1},
            ],
            confidence=0.8,
            review_required=True,
            context_hit=True,
            patient_id="p-001",
            patient_name="Test Patient",
            bed_no="12",
            artifacts=[AgentArtifact(kind="document_draft", title="Draft created")],
            created_at=datetime.now(timezone.utc),
        )
        next_actions = agentic_orchestrator._default_next_actions(output)
        self.assertEqual(next_actions[0], "Prioritize bed 12")

    def test_execute_autonomous_plan_requires_approval_for_sensitive_tool(self) -> None:
        state = {
            "patient_id": "p-001",
            "bed_no": "12",
            "patient_name": "Test Patient",
            "findings": [],
            "recommendations": [],
            "artifacts": [],
            "confidence": 0.7,
            "orders": None,
            "completed": {"send_collaboration": "pending"},
            "tool_steps": [],
            "tool_executions": [],
            "pending_approvals": [],
        }
        plan = [
            AgentPlanItem(
                id="send_collaboration",
                title="Notify doctor",
                tool="collaboration",
                reason="High risk signal requires escalation",
            )
        ]

        asyncio.run(
            agentic_orchestrator._execute_autonomous_plan(
                helper=object(),
                payload=WorkflowRequest(workflow_type=WorkflowType.AUTONOMOUS_CARE, patient_id="p-001"),
                question="autonomous follow up bed 12",
                plan=plan,
                state=state,
            )
        )

        self.assertEqual(state["completed"]["send_collaboration"], "approval_required")
        self.assertEqual(len(state["pending_approvals"]), 1)
        self.assertEqual(len(state["tool_executions"]), 0)
        self.assertEqual(state["tool_steps"][0].status, "approval_required")

    def test_execute_autonomous_plan_retries_retryable_tool(self) -> None:
        registered = agentic_orchestrator._tool_registry.get("recommend")
        self.assertIsNotNone(registered)
        assert registered is not None

        original_handler = registered.handler
        attempts = {"count": 0}

        async def flaky_recommend(**kwargs):
            attempts["count"] += 1
            if attempts["count"] == 1:
                return "failed", {"error": "temporary_failure"}
            return "done", {"recommendation_count": 1}

        agentic_orchestrator._tool_registry.register(registered.spec, flaky_recommend)
        try:
            state = {
                "patient_id": "p-001",
                "bed_no": "12",
                "patient_name": "Test Patient",
                "findings": [],
                "recommendations": [],
                "artifacts": [],
                "confidence": 0.7,
                "orders": None,
                "completed": {"recommend": "pending"},
                "tool_steps": [],
                "tool_executions": [],
                "pending_approvals": [],
            }
            plan = [AgentPlanItem(id="recommend", title="Generate recommendation", tool="recommendation")]

            asyncio.run(
                agentic_orchestrator._execute_autonomous_plan(
                    helper=object(),
                    payload=WorkflowRequest(workflow_type=WorkflowType.AUTONOMOUS_CARE, patient_id="p-001"),
                    question="auto follow up bed 12",
                    plan=plan,
                    state=state,
                )
            )
        finally:
            agentic_orchestrator._tool_registry.register(registered.spec, original_handler)

        self.assertEqual(state["completed"]["recommend"], "done")
        self.assertEqual(len(state["tool_executions"]), 1)
        self.assertEqual(state["tool_executions"][0].attempts, 2)
        self.assertEqual(state["tool_steps"][0].output["attempts"], 2)

    def test_finalize_builds_structured_role_and_reasoning_views(self) -> None:
        payload = WorkflowRequest(
            workflow_type=WorkflowType.AUTONOMOUS_CARE,
            patient_id="p-001",
            bed_no="12",
            user_input="请持续跟进12床低血压、通知医生并留痕",
            mission_title="夜班风险闭环",
            success_criteria=["完成风险扫描", "准备协作摘要", "沉淀护理记录"],
            execution_profile="full_loop",
        )
        output = WorkflowOutput(
            workflow_type=WorkflowType.AUTONOMOUS_CARE,
            summary="12床存在低血压与少尿信号，建议先复测血压并准备协作。",
            findings=["低血压风险", "尿量减少", "需要人工复核"],
            recommendations=[
                {"title": "立即复测血压并校验趋势", "priority": 1},
                {"title": "准备协作摘要并通知医生", "priority": 1},
                {"title": "同步生成护理记录草稿", "priority": 2},
            ],
            confidence=0.84,
            review_required=True,
            context_hit=True,
            patient_id="p-001",
            patient_name="Test Patient",
            bed_no="12",
            artifacts=[
                AgentArtifact(kind="document_draft", title="12床护理记录草稿"),
            ],
            pending_approvals=[
                AgentApprovalRequest(
                    id="approval-structured",
                    item_id="send_collaboration",
                    tool_id="collaboration",
                    title="通知值班医生",
                    created_at=datetime.now(timezone.utc),
                )
            ],
            created_at=datetime.now(timezone.utc),
        )

        finalized = agentic_orchestrator.finalize(payload, output)

        self.assertGreaterEqual(len(finalized.specialist_profiles), 2)
        self.assertTrue(any(item.id == "human_gate" for item in finalized.hybrid_care_path))
        self.assertIsNotNone(finalized.data_capsule)
        self.assertIsNotNone(finalized.health_graph)
        self.assertGreaterEqual(len(finalized.reasoning_cards), 3)


if __name__ == "__main__":
    unittest.main()
