from __future__ import annotations

import asyncio
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
from app.services.agent_task_worker import AgentTaskWorker  # noqa: E402


class _FakeRuntime:
    def __init__(self, output: WorkflowOutput) -> None:
        self.output = output

    async def run(self, payload: WorkflowRequest, *, engine_override: str | None = None) -> WorkflowOutput:
        return self.output


class AgentTaskWorkerTests(unittest.TestCase):
    def test_process_task_moves_task_to_waiting_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = AgentQueueStore(Path(tmpdir) / "agent_queue.json")
            task = store.enqueue(
                WorkflowRequest(
                    workflow_type=WorkflowType.AUTONOMOUS_CARE,
                    patient_id="p-001",
                    user_input="autonomous follow up bed 12",
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
                        id="approval-1",
                        item_id="send_collaboration",
                        tool_id="collaboration",
                        title="Notify doctor",
                        created_at=datetime.now(timezone.utc),
                    )
                ],
                created_at=datetime.now(timezone.utc),
            )

            worker = AgentTaskWorker(queue_store=store, runtime_service=_FakeRuntime(output))
            asyncio.run(worker._process_task(task.id))

            saved = store.get(task.id)
            self.assertIsNotNone(saved)
            assert saved is not None
            self.assertEqual(saved.status, "waiting_approval")
            self.assertEqual(len(saved.approvals), 1)

    def test_process_task_completes_without_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = AgentQueueStore(Path(tmpdir) / "agent_queue.json")
            task = store.enqueue(
                WorkflowRequest(
                    workflow_type=WorkflowType.RECOMMENDATION,
                    patient_id="p-001",
                    user_input="recommend for bed 12",
                )
            )
            store.claim_next()

            output = WorkflowOutput(
                workflow_type=WorkflowType.RECOMMENDATION,
                summary="Completed.",
                findings=["stable"],
                recommendations=[{"title": "review vitals", "priority": 1}],
                confidence=0.8,
                review_required=True,
                context_hit=True,
                patient_id="p-001",
                bed_no="12",
                created_at=datetime.now(timezone.utc),
            )

            worker = AgentTaskWorker(queue_store=store, runtime_service=_FakeRuntime(output))
            asyncio.run(worker._process_task(task.id))

            saved = store.get(task.id)
            self.assertIsNotNone(saved)
            assert saved is not None
            self.assertEqual(saved.status, "completed")
            self.assertEqual(saved.summary, "Completed.")


if __name__ == "__main__":
    unittest.main()
