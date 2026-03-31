from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.schemas.workflow import AgentApprovalRequest, WorkflowOutput, WorkflowRequest, WorkflowType  # noqa: E402
from app.services.agent_queue_store import AgentQueueStore  # noqa: E402


class AgentQueueStoreTests(unittest.TestCase):
    def test_wait_for_approval_then_approve_requeues_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_file = Path(tmpdir) / "agent_queue.json"
            store = AgentQueueStore(data_file)
            task = store.enqueue(
                WorkflowRequest(
                    workflow_type=WorkflowType.AUTONOMOUS_CARE,
                    patient_id="p-001",
                    bed_no="12",
                    user_input="autonomous follow up bed 12",
                    requested_by="u_test",
                )
            )

            claimed = store.claim_next()
            self.assertIsNotNone(claimed)
            assert claimed is not None
            self.assertEqual(claimed.status, "running")

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
                run_id="run-001",
                runtime_engine="state_machine",
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

            waiting = store.wait_for_approval(task.id, output)
            self.assertIsNotNone(waiting)
            assert waiting is not None
            self.assertEqual(waiting.status, "waiting_approval")
            self.assertEqual(waiting.run_id, "run-001")
            self.assertEqual(len(waiting.approvals), 1)

            approved = store.approve(task.id, approval_ids=["approval-1"], decided_by="u_charge")
            self.assertIsNotNone(approved)
            assert approved is not None
            self.assertEqual(approved.status, "queued")
            self.assertIn("send_collaboration", approved.payload.approved_actions)
            self.assertEqual(approved.resume_count, 1)

    def test_reject_marks_action_and_requeues_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_file = Path(tmpdir) / "agent_queue.json"
            store = AgentQueueStore(data_file)
            task = store.enqueue(
                WorkflowRequest(
                    workflow_type=WorkflowType.AUTONOMOUS_CARE,
                    patient_id="p-001",
                    bed_no="12",
                    user_input="autonomous follow up bed 12",
                    requested_by="u_test",
                )
            )
            store.claim_next()

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
                        id="approval-2",
                        item_id="create_document",
                        tool_id="document",
                        title="Create document",
                        created_at=datetime.now(timezone.utc),
                    )
                ],
                created_at=datetime.now(timezone.utc),
            )
            store.wait_for_approval(task.id, output)

            rejected = store.reject(task.id, approval_ids=["approval-2"], decided_by="u_charge")
            self.assertIsNotNone(rejected)
            assert rejected is not None
            self.assertEqual(rejected.status, "queued")
            self.assertIn("create_document", rejected.payload.rejected_actions)
            self.assertEqual(rejected.approvals[0].status, "rejected")

    def test_recover_running_tasks_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_file = Path(tmpdir) / "agent_queue.json"
            store = AgentQueueStore(data_file)
            task = store.enqueue(
                WorkflowRequest(
                    workflow_type=WorkflowType.RECOMMENDATION,
                    patient_id="p-001",
                    user_input="recommend for bed 12",
                )
            )
            store.claim_next()

            reloaded = AgentQueueStore(data_file)
            recovered = reloaded.recover_incomplete_tasks()
            self.assertEqual(recovered, 1)
            saved = reloaded.get(task.id)
            self.assertIsNotNone(saved)
            assert saved is not None
            self.assertEqual(saved.status, "queued")


if __name__ == "__main__":
    unittest.main()
