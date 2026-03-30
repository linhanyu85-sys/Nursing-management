from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class BedOverview(BaseModel):
    id: str
    department_id: str
    bed_no: str
    room_no: str | None = None
    status: str
    current_patient_id: str | None = None
    patient_name: str | None = None
    risk_tags: list[str] = Field(default_factory=list)
    pending_tasks: list[str] = Field(default_factory=list)
    latest_document_sync: str | None = None


class PatientBase(BaseModel):
    id: str
    mrn: str
    inpatient_no: str | None = None
    full_name: str
    gender: str | None = None
    age: int | None = None
    blood_type: str | None = None
    allergy_info: str | None = None
    current_status: str


class PatientContextOut(BaseModel):
    patient_id: str
    patient_name: str | None = None
    bed_no: str | None = None
    encounter_id: str | None = None
    diagnoses: list[str] = Field(default_factory=list)
    risk_tags: list[str] = Field(default_factory=list)
    pending_tasks: list[str] = Field(default_factory=list)
    latest_observations: list[dict[str, Any]] = Field(default_factory=list)
    latest_document_sync: str | None = None
    latest_document_status: str | None = None
    latest_document_type: str | None = None
    latest_document_excerpt: str | None = None
    latest_document_updated_at: datetime | None = None
    updated_at: datetime | None = None


class ObservationInput(BaseModel):
    name: str
    value: str
    abnormal_flag: str | None = None


class PatientCaseUpsertRequest(BaseModel):
    patient_id: str | None = None
    bed_no: str
    room_no: str | None = None
    full_name: str
    mrn: str | None = None
    inpatient_no: str | None = None
    gender: str | None = None
    age: int | None = None
    blood_type: str | None = None
    allergy_info: str | None = None
    current_status: str = "admitted"
    encounter_id: str | None = None
    diagnoses: list[str] = Field(default_factory=list)
    risk_tags: list[str] = Field(default_factory=list)
    pending_tasks: list[str] = Field(default_factory=list)
    latest_observations: list[ObservationInput] = Field(default_factory=list)


class PatientCaseBundleOut(BaseModel):
    created: bool
    patient: PatientBase
    context: PatientContextOut
    bed: BedOverview


class OrderExecutionTrail(BaseModel):
    action: str
    actor: str
    note: str | None = None
    created_at: datetime


class OrderOut(BaseModel):
    id: str
    patient_id: str
    encounter_id: str | None = None
    order_no: str
    order_type: str
    title: str
    instruction: str
    route: str | None = None
    dosage: str | None = None
    frequency: str | None = None
    priority: str = "P2"
    status: str
    ordered_by: str | None = None
    ordered_at: datetime | None = None
    due_at: datetime | None = None
    requires_double_check: bool = False
    check_by: str | None = None
    check_at: datetime | None = None
    executed_by: str | None = None
    executed_at: datetime | None = None
    execution_note: str | None = None
    exception_reason: str | None = None
    risk_hints: list[str] = Field(default_factory=list)
    audit_trail: list[OrderExecutionTrail] = Field(default_factory=list)


class OrderCheckRequest(BaseModel):
    checked_by: str
    note: str | None = None


class OrderExecuteRequest(BaseModel):
    executed_by: str
    note: str | None = None


class OrderExceptionRequest(BaseModel):
    reported_by: str
    reason: str


class OrderRequestCreateRequest(BaseModel):
    patient_id: str
    requested_by: str
    title: str
    details: str
    priority: str = "P2"


class OrderStatsOut(BaseModel):
    pending: int
    due_30m: int
    overdue: int
    high_alert: int


class OrderListOut(BaseModel):
    patient_id: str
    stats: OrderStatsOut
    orders: list[OrderOut] = Field(default_factory=list)
