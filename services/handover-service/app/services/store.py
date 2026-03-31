from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from app.schemas.handover import HandoverRecord


class HandoverStore:
    def __init__(self) -> None:
        self._records: list[HandoverRecord] = []
        self._data_file = Path(__file__).resolve().parents[2] / "data" / "handover_records.json"
        self._load()

    def add(self, record: HandoverRecord) -> HandoverRecord:
        self._records.append(record)
        self._save()
        return record

    def create(
        self,
        *,
        patient_id: str,
        encounter_id: str | None,
        shift_date: date,
        shift_type: str,
        generated_by: str | None,
        summary: str,
        new_changes: list[dict],
        worsening_points: list[str],
        improved_points: list[str],
        pending_closures: list[str],
        next_shift_priorities: list[str],
    ) -> HandoverRecord:
        return self.add(
            HandoverRecord(
                id=str(uuid.uuid4()),
                patient_id=patient_id,
                encounter_id=encounter_id,
                shift_date=shift_date,
                shift_type=shift_type,
                generated_by=generated_by,
                summary=summary,
                new_changes=new_changes,
                worsening_points=worsening_points,
                improved_points=improved_points,
                pending_closures=pending_closures,
                next_shift_priorities=next_shift_priorities,
                created_at=datetime.now(timezone.utc),
            )
        )

    def latest_by_patient(self, patient_id: str) -> HandoverRecord | None:
        for item in reversed(self._records):
            if item.patient_id == patient_id:
                return item
        return None

    def latest_by_patient_for_user(self, patient_id: str, generated_by: str | None = None) -> HandoverRecord | None:
        owner = (generated_by or "").strip()
        for item in reversed(self._records):
            if item.patient_id != patient_id:
                continue
            if owner and (item.generated_by or "").strip() != owner:
                continue
            return item
        return None

    def list_by_patient(self, patient_id: str, limit: int = 50) -> list[HandoverRecord]:
        result: list[HandoverRecord] = []
        for item in reversed(self._records):
            if item.patient_id == patient_id:
                result.append(item)
            if len(result) >= limit:
                break
        return result

    def list_by_user(
        self,
        generated_by: str,
        *,
        patient_id: str | None = None,
        limit: int = 50,
    ) -> list[HandoverRecord]:
        owner = (generated_by or "").strip()
        if not owner:
            return []
        result: list[HandoverRecord] = []
        for item in reversed(self._records):
            if (item.generated_by or "").strip() != owner:
                continue
            if patient_id and item.patient_id != patient_id:
                continue
            result.append(item)
            if len(result) >= limit:
                break
        return result

    def get(self, record_id: str) -> HandoverRecord | None:
        for item in self._records:
            if item.id == record_id:
                return item
        return None

    def review(self, record_id: str, reviewed_by: str) -> HandoverRecord | None:
        item = self.get(record_id)
        if item is None:
            return None
        item.reviewed_by = reviewed_by
        item.reviewed_at = datetime.now(timezone.utc)
        self._save()
        return item

    def _load(self) -> None:
        if not self._data_file.exists():
            return
        try:
            payload = json.loads(self._data_file.read_text(encoding="utf-8"))
            self._records = [HandoverRecord.model_validate(item) for item in payload.get("records", []) if isinstance(item, dict)]
        except Exception:
            self._records = []

    def _save(self) -> None:
        self._data_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "records": [item.model_dump(mode="json") for item in self._records[-3000:]],
        }
        self._data_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


handover_store = HandoverStore()
