from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DraftRequest(BaseModel):
    patient_id: str
    document_type: str = "nursing_note"
    spoken_text: str | None = None
    template_id: str | None = None
    template_text: str | None = None
    template_name: str | None = None
    requested_by: str | None = None


class DraftReviewRequest(BaseModel):
    reviewed_by: str
    review_note: str | None = None


class DraftSubmitRequest(BaseModel):
    submitted_by: str


class DraftEditRequest(BaseModel):
    draft_text: str
    edited_by: str | None = None


class TemplateImportRequest(BaseModel):
    name: str | None = None
    template_text: str | None = None
    template_base64: str | None = None
    file_name: str | None = None
    mime_type: str | None = None
    requested_by: str | None = None


class DocumentTemplate(BaseModel):
    id: str
    name: str
    source_type: str = "import"
    template_text: str
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class DocumentDraft(BaseModel):
    id: str
    patient_id: str
    encounter_id: str | None = None
    document_type: str
    draft_text: str
    structured_fields: dict[str, Any] = Field(default_factory=dict)
    source_type: str = "ai"
    status: str = "draft"
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime
