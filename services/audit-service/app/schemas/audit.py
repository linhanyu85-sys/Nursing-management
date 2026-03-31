from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AuditLogCreate(BaseModel):
    user_id: str | None = None
    action: str
    resource_type: str
    resource_id: str | None = None
    request_id: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
    ip_address: str | None = None
    device_info: str | None = None


class AuditLogOut(AuditLogCreate):
    id: str
    created_at: datetime
