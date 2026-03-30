from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RecommendationRequest(BaseModel):
    patient_id: str
    question: str
    bed_no: str | None = None
    department_id: str | None = None
    attachments: list[str] = Field(default_factory=list)
    requested_by: str | None = None
    fast_mode: bool = False


class RecommendationItem(BaseModel):
    title: str
    priority: int = 2
    rationale: str | None = None


class RecommendationOutput(BaseModel):
    id: str
    patient_id: str
    summary: str
    findings: list[str] = Field(default_factory=list)
    recommendations: list[RecommendationItem] = Field(default_factory=list)
    confidence: float = 0.0
    review_required: bool = True
    escalation_rules: list[str] = Field(default_factory=list)
    status: str = "draft"
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
