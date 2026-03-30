from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    patient_id: str
    input_refs: list[str] = Field(default_factory=list)
    question: str | None = None


class AnalyzeResponse(BaseModel):
    patient_id: str
    summary: str
    findings: list[str]
    recommendations: list[dict[str, Any]]
    confidence: float
    review_required: bool
    created_at: datetime
