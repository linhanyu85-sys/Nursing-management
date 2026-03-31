from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class HandoverGenerateRequest(BaseModel):
    patient_id: str
    shift_date: date | None = None
    shift_type: str = "day"
    generated_by: str | None = None


class HandoverBatchRequest(BaseModel):
    department_id: str
    shift_date: date | None = None
    shift_type: str = "day"
    generated_by: str | None = None


class HandoverReviewRequest(BaseModel):
    reviewed_by: str
    review_note: str | None = None


class HandoverRecord(BaseModel):
    id: str
    patient_id: str
    encounter_id: str | None = None
    shift_date: date
    shift_type: str
    source_type: str = "ai"
    summary: str
    new_changes: list[dict[str, Any]] = Field(default_factory=list)
    worsening_points: list[str] = Field(default_factory=list)
    improved_points: list[str] = Field(default_factory=list)
    pending_closures: list[str] = Field(default_factory=list)
    next_shift_priorities: list[str] = Field(default_factory=list)
    generated_by: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime
