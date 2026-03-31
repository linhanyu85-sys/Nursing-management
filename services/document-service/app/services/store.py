from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.schemas.document import DocumentDraft, DocumentTemplate


class DocumentStore:
    def __init__(self) -> None:
        self._items: list[DocumentDraft] = []
        self._templates: list[DocumentTemplate] = []
        self._data_file = Path(__file__).resolve().parents[2] / "data" / "document_store.json"
        self._load()
        if not self._templates:
            self._seed_default_templates()
            self._save()

    def _seed_default_templates(self) -> None:
        now = datetime.now(timezone.utc)
        self._templates.append(
            DocumentTemplate(
                id="tpl-default-nursing-note",
                name="默认护理记录模板",
                source_type="system",
                template_text=(
                    "【护理记录】\n"
                    "患者ID：{{patient_id}}  床号：{{bed_no}}\n"
                    "主要诊断：{{diagnoses}}\n"
                    "当前风险：{{risk_tags}}\n"
                    "待处理事项：{{pending_tasks}}\n"
                    "记录内容：{{spoken_text}}\n"
                    "护士评估：\n"
                    "处理措施：\n"
                    "复评与计划：\n"
                ),
                created_by="system",
                created_at=now,
                updated_at=now,
            )
        )

    def create(
        self,
        *,
        patient_id: str,
        encounter_id: str | None,
        document_type: str,
        draft_text: str,
        structured_fields: dict,
        created_by: str | None,
    ) -> DocumentDraft:
        now = datetime.now(timezone.utc)
        item = DocumentDraft(
            id=str(uuid.uuid4()),
            patient_id=patient_id,
            encounter_id=encounter_id,
            document_type=document_type,
            draft_text=draft_text,
            structured_fields=structured_fields,
            status="draft",
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )
        self._items.append(item)
        self._save()
        return item

    def list_by_patient(self, patient_id: str, requested_by: str | None = None) -> list[DocumentDraft]:
        owner = (requested_by or "").strip()
        items = [item for item in reversed(self._items) if item.patient_id == patient_id]
        if owner:
            items = [item for item in items if (item.created_by or "").strip() == owner]
        return items

    def list_history(
        self,
        *,
        patient_id: str | None = None,
        requested_by: str | None = None,
        limit: int = 50,
    ) -> list[DocumentDraft]:
        items = list(reversed(self._items))
        if patient_id:
            items = [item for item in items if item.patient_id == patient_id]
        owner = (requested_by or "").strip()
        if owner:
            items = [item for item in items if (item.created_by or "").strip() == owner]
        return items[:limit]

    def get(self, draft_id: str) -> DocumentDraft | None:
        for item in self._items:
            if item.id == draft_id:
                return item
        return None

    def create_template(
        self,
        *,
        name: str,
        template_text: str,
        source_type: str = "import",
        created_by: str | None = None,
    ) -> DocumentTemplate:
        now = datetime.now(timezone.utc)
        item = DocumentTemplate(
            id=str(uuid.uuid4()),
            name=name,
            source_type=source_type,
            template_text=template_text,
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )
        self._templates.append(item)
        self._save()
        return item

    def list_templates(self) -> list[DocumentTemplate]:
        return list(reversed(self._templates))

    def get_template(self, template_id: str) -> DocumentTemplate | None:
        for item in self._templates:
            if item.id == template_id:
                return item
        return None

    def review(self, draft_id: str, reviewed_by: str) -> DocumentDraft | None:
        item = self.get(draft_id)
        if item is None:
            return None
        item.status = "reviewed"
        item.reviewed_by = reviewed_by
        item.reviewed_at = datetime.now(timezone.utc)
        item.updated_at = item.reviewed_at
        self._save()
        return item

    def submit(self, draft_id: str) -> DocumentDraft | None:
        item = self.get(draft_id)
        if item is None:
            return None
        item.status = "submitted"
        item.updated_at = datetime.now(timezone.utc)
        self._save()
        return item

    def edit(self, draft_id: str, draft_text: str, edited_by: str | None = None) -> DocumentDraft | None:
        item = self.get(draft_id)
        if item is None:
            return None
        item.draft_text = draft_text
        item.status = "draft"
        item.updated_at = datetime.now(timezone.utc)
        if edited_by:
            item.created_by = edited_by
        item.structured_fields = {
            **(item.structured_fields or {}),
            "manual_edited": True,
            "edited_by": edited_by,
            "edited_at": item.updated_at.isoformat(),
        }
        self._save()
        return item

    def _load(self) -> None:
        if not self._data_file.exists():
            return
        try:
            payload = json.loads(self._data_file.read_text(encoding="utf-8"))
            self._items = [DocumentDraft.model_validate(item) for item in payload.get("items", []) if isinstance(item, dict)]
            self._templates = [
                DocumentTemplate.model_validate(item) for item in payload.get("templates", []) if isinstance(item, dict)
            ]
        except Exception:
            self._items = []
            self._templates = []

    def _save(self) -> None:
        self._data_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "items": [item.model_dump(mode="json") for item in self._items[-2000:]],
            "templates": [item.model_dump(mode="json") for item in self._templates[-1000:]],
        }
        self._data_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


document_store = DocumentStore()
