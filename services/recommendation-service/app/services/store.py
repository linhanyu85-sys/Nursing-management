from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.schemas.recommendation import RecommendationOutput


class RecommendationStore:
    def __init__(self) -> None:
        self._items: list[RecommendationOutput] = []
        self._last_question_by_patient: dict[str, str] = {}
        self._data_file = Path(__file__).resolve().parents[2] / "data" / "recommendation_history.json"
        self._load()

    def create(
        self,
        *,
        patient_id: str,
        summary: str,
        findings: list[str],
        recommendations,
        confidence: float,
        escalation_rules: list[str],
        review_required: bool,
        metadata: dict,
    ) -> RecommendationOutput:
        item = RecommendationOutput(
            id=str(uuid.uuid4()),
            patient_id=patient_id,
            summary=summary,
            findings=findings,
            recommendations=recommendations,
            confidence=confidence,
            review_required=review_required,
            escalation_rules=escalation_rules,
            status="draft",
            created_at=datetime.now(timezone.utc),
            metadata=metadata,
        )
        self._items.append(item)
        if metadata.get("question"):
            self._last_question_by_patient[patient_id] = str(metadata["question"])
        elif metadata.get("effective_question"):
            self._last_question_by_patient[patient_id] = str(metadata["effective_question"])[:120]
        self._save()
        return item

    def list_by_patient(self, patient_id: str) -> list[RecommendationOutput]:
        return [item for item in reversed(self._items) if item.patient_id == patient_id]

    def list_by_patient_for_user(self, patient_id: str, requested_by: str | None = None) -> list[RecommendationOutput]:
        owner = (requested_by or "").strip()
        items = [item for item in reversed(self._items) if item.patient_id == patient_id]
        if owner:
            items = [item for item in items if str((item.metadata or {}).get("requested_by") or "").strip() == owner]
        return items

    def list_by_user(
        self,
        requested_by: str,
        *,
        patient_id: str | None = None,
        limit: int = 50,
    ) -> list[RecommendationOutput]:
        owner = (requested_by or "").strip()
        if not owner:
            return []
        output: list[RecommendationOutput] = []
        for item in reversed(self._items):
            owner_tag = str((item.metadata or {}).get("requested_by") or "").strip()
            if owner_tag != owner:
                continue
            if patient_id and item.patient_id != patient_id:
                continue
            output.append(item)
            if len(output) >= limit:
                break
        return output

    def get_last_question(self, patient_id: str) -> str | None:
        return self._last_question_by_patient.get(patient_id)

    def _load(self) -> None:
        if not self._data_file.exists():
            return
        try:
            payload = json.loads(self._data_file.read_text(encoding="utf-8"))
            items_raw = payload.get("items", [])
            self._items = [RecommendationOutput.model_validate(item) for item in items_raw if isinstance(item, dict)]
            self._last_question_by_patient = {
                str(key): str(value) for key, value in payload.get("last_question_by_patient", {}).items()
            }
        except Exception:
            self._items = []
            self._last_question_by_patient = {}

    def _save(self) -> None:
        self._data_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "items": [item.model_dump(mode="json") for item in self._items[-1000:]],
            "last_question_by_patient": self._last_question_by_patient,
        }
        self._data_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


recommendation_store = RecommendationStore()
