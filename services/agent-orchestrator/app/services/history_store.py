from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Iterable

from app.schemas.workflow import WorkflowHistoryItem, WorkflowOutput, WorkflowRequest, WorkflowType


class WorkflowHistoryStore:
    def __init__(self) -> None:
        self._items: list[WorkflowHistoryItem] = []
        self._data_file = Path(__file__).resolve().parents[2] / "data" / "workflow_history.json"
        self._load()

    def append(self, request: WorkflowRequest, output: WorkflowOutput) -> WorkflowHistoryItem:
        item = WorkflowHistoryItem(
            id=str(uuid.uuid4()),
            workflow_type=output.workflow_type,
            patient_id=request.patient_id,
            conversation_id=request.conversation_id,
            department_id=request.department_id,
            bed_no=request.bed_no,
            requested_by=request.requested_by,
            user_input=request.user_input,
            summary=output.summary,
            findings=output.findings,
            recommendations=output.recommendations,
            confidence=output.confidence,
            review_required=output.review_required,
            steps=output.steps,
            run_id=output.run_id,
            runtime_engine=output.runtime_engine,
            agent_goal=output.agent_goal,
            agent_mode=output.agent_mode,
            execution_profile=output.execution_profile or request.execution_profile,
            mission_title=output.mission_title or request.mission_title,
            success_criteria=list(output.success_criteria or request.success_criteria),
            plan=output.plan,
            memory=output.memory,
            artifacts=output.artifacts,
            specialist_profiles=output.specialist_profiles,
            hybrid_care_path=output.hybrid_care_path,
            data_capsule=output.data_capsule,
            health_graph=output.health_graph,
            reasoning_cards=output.reasoning_cards,
            tool_executions=output.tool_executions,
            pending_approvals=output.pending_approvals,
            next_actions=output.next_actions,
            created_at=output.created_at,
        )
        self._items.append(item)
        self._save()
        return item

    def list(
        self,
        *,
        patient_id: str | None = None,
        conversation_id: str | None = None,
        requested_by: str | None = None,
        workflow_type: WorkflowType | None = None,
        limit: int = 50,
    ) -> list[WorkflowHistoryItem]:
        selected: Iterable[WorkflowHistoryItem] = reversed(self._items)
        if patient_id:
            selected = (item for item in selected if item.patient_id == patient_id)
        if conversation_id:
            selected = (item for item in selected if item.conversation_id == conversation_id)
        if requested_by:
            selected = (item for item in selected if item.requested_by == requested_by)
        if workflow_type:
            selected = (item for item in selected if item.workflow_type == workflow_type)
        result = list(selected)
        return result[:limit]

    def _load(self) -> None:
        if not self._data_file.exists():
            return
        try:
            payload = json.loads(self._data_file.read_text(encoding="utf-8"))
            items_raw = payload.get("items", [])
            self._items = [WorkflowHistoryItem.model_validate(item) for item in items_raw if isinstance(item, dict)]
        except Exception:
            self._items = []

    def _save(self) -> None:
        self._data_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {"items": [item.model_dump(mode="json") for item in self._items[-1000:]]}
        self._data_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


workflow_history_store = WorkflowHistoryStore()
