from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.schemas.workflow import AgentMemorySnapshot, WorkflowOutput, WorkflowRequest, WorkflowType
from app.services.agent_run_store import AgentRunStore


class AgentRunStoreTests(unittest.TestCase):
    def test_start_complete_and_reload_run_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_file = Path(tmpdir) / "agent_runs.json"
            store = AgentRunStore(data_file)
            request = WorkflowRequest(
                workflow_type=WorkflowType.AUTONOMOUS_CARE,
                patient_id="p-001",
                conversation_id="conv-001",
                bed_no="12",
                user_input="auto follow up bed 12",
                requested_by="u_test",
            )

            record = store.start(
                request,
                workflow_type=WorkflowType.AUTONOMOUS_CARE,
                runtime_engine="state_machine",
                agent_goal="close the loop for bed 12",
                agent_mode="autonomous",
                plan=[],
                memory=AgentMemorySnapshot(conversation_summary="recent memory"),
            )
            self.assertEqual(record.status, "running")
            self.assertTrue(store.has_retry_request(record.id))
            self.assertIsNotNone(store.retry_request(record.id))

            output = WorkflowOutput(
                workflow_type=WorkflowType.AUTONOMOUS_CARE,
                summary="completed",
                findings=["low blood pressure"],
                recommendations=[{"title": "notify doctor", "priority": 1}],
                confidence=0.82,
                review_required=True,
                context_hit=True,
                patient_id="p-001",
                bed_no="12",
                run_id=record.id,
                runtime_engine="state_machine",
                created_at=datetime.now(timezone.utc),
            )
            completed = store.complete(record.id, output, tool_executions=[])
            self.assertIsNotNone(completed)
            assert completed is not None
            self.assertEqual(completed.status, "completed")

            reloaded = AgentRunStore(data_file)
            saved = reloaded.get(record.id)
            self.assertIsNotNone(saved)
            assert saved is not None
            self.assertEqual(saved.status, "completed")
            self.assertEqual(saved.request.attachments_count, 0)
            self.assertFalse(saved.retry_available)


if __name__ == "__main__":
    unittest.main()
