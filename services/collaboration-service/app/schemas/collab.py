from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ThreadCreateRequest(BaseModel):
    patient_id: str | None = None
    encounter_id: str | None = None
    thread_type: str = "discussion"
    title: str
    created_by: str | None = None


class MessageCreateRequest(BaseModel):
    thread_id: str
    sender_id: str | None = None
    message_type: str = "text"
    content: str
    attachment_refs: list[str] = Field(default_factory=list)
    ai_generated: bool = False


class EscalateRequest(BaseModel):
    thread_id: str
    reason: str
    requested_by: str | None = None


class ThreadOut(BaseModel):
    id: str
    patient_id: str | None = None
    encounter_id: str | None = None
    thread_type: str
    title: str
    created_by: str | None = None
    status: str = "open"
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    id: str
    thread_id: str
    sender_id: str | None = None
    message_type: str
    content: str
    attachment_refs: list[str] = Field(default_factory=list)
    ai_generated: bool = False
    created_at: datetime


class ThreadDetailOut(BaseModel):
    thread: ThreadOut
    messages: list[MessageOut] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ThreadHistoryItem(BaseModel):
    thread: ThreadOut
    latest_message: MessageOut | None = None
    message_count: int = 0


class AccountOut(BaseModel):
    id: str
    account: str
    full_name: str
    role_code: str
    department: str | None = None
    title: str | None = None


class ContactAddRequest(BaseModel):
    user_id: str
    account: str


class ContactListOut(BaseModel):
    user_id: str
    contacts: list[AccountOut] = Field(default_factory=list)


class DirectSessionOpenRequest(BaseModel):
    user_id: str
    contact_user_id: str
    patient_id: str | None = None


class DirectSessionOut(BaseModel):
    id: str
    user_id: str
    contact_user_id: str
    patient_id: str | None = None
    status: str = "open"
    created_at: datetime
    updated_at: datetime
    latest_message: MessageOut | None = None
    unread_count: int = 0
    contact: AccountOut | None = None


class DirectMessageCreateRequest(BaseModel):
    session_id: str
    sender_id: str
    message_type: str = "text"
    content: str
    attachment_refs: list[str] = Field(default_factory=list)


class DirectSessionDetailOut(BaseModel):
    session: DirectSessionOut
    messages: list[MessageOut] = Field(default_factory=list)


class AssistantDigestRequest(BaseModel):
    user_id: str
    patient_id: str
    note: str | None = None


class AssistantDigestOut(BaseModel):
    summary: str
    tasks: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    generated_message: str
