from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query, status

from app.core.config import settings
from app.schemas.collab import (
    AccountOut,
    AdminAccountUpsertRequest,
    AssistantDigestOut,
    AssistantDigestRequest,
    ContactAddRequest,
    ContactListOut,
    DirectMessageCreateRequest,
    DirectSessionDetailOut,
    DirectSessionOpenRequest,
    DirectSessionOut,
    EscalateRequest,
    MessageCreateRequest,
    MessageOut,
    ThreadHistoryItem,
    ThreadCreateRequest,
    ThreadDetailOut,
    ThreadOut,
)
from app.services.store import collaboration_store

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": settings.service_name}


@router.get("/ready")
def ready() -> dict:
    return {"status": "ready", "service": settings.service_name}


@router.get("/version")
def version() -> dict:
    return {
        "service": settings.service_name,
        "version": settings.app_version,
        "env": settings.app_env,
        "mock_mode": settings.mock_mode,
    }


@router.post("/collab/thread", response_model=ThreadOut)
def create_thread(payload: ThreadCreateRequest) -> ThreadOut:
    return collaboration_store.create_thread(
        patient_id=payload.patient_id,
        encounter_id=payload.encounter_id,
        thread_type=payload.thread_type,
        title=payload.title,
        created_by=payload.created_by,
    )


@router.post("/collab/message", response_model=MessageOut)
def create_message(payload: MessageCreateRequest) -> MessageOut:
    thread = collaboration_store.get_thread(payload.thread_id)
    if thread is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="thread_not_found")
    return collaboration_store.add_message(
        thread_id=payload.thread_id,
        sender_id=payload.sender_id,
        message_type=payload.message_type,
        content=payload.content,
        attachment_refs=payload.attachment_refs,
        ai_generated=payload.ai_generated,
    )


@router.get("/collab/thread/{thread_id}", response_model=ThreadDetailOut)
def get_thread(thread_id: str) -> ThreadDetailOut:
    thread = collaboration_store.get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="thread_not_found")
    messages = collaboration_store.list_messages(thread_id)
    return ThreadDetailOut(thread=thread, messages=messages, metadata={"message_count": len(messages)})


@router.get("/collab/history", response_model=list[ThreadHistoryItem])
def get_thread_history(
    patient_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ThreadHistoryItem]:
    return collaboration_store.list_thread_history(patient_id=patient_id, limit=limit)


@router.get("/collab/accounts", response_model=list[AccountOut])
def search_accounts(
    query: str = Query(default=""),
    exclude_user_id: str | None = Query(default=None),
) -> list[AccountOut]:
    return collaboration_store.search_accounts(query=query, exclude_user_id=exclude_user_id)


@router.get("/collab/admin/accounts", response_model=list[AccountOut])
def admin_list_accounts(query: str = Query(default=""), status_filter: str | None = Query(default=None)) -> list[AccountOut]:
    return collaboration_store.list_accounts_admin(query=query, status_filter=status_filter)


@router.post("/collab/admin/accounts/upsert", response_model=AccountOut)
def admin_upsert_account(payload: AdminAccountUpsertRequest) -> AccountOut:
    try:
        return collaboration_store.upsert_account(
            account_id=payload.id,
            account=payload.account,
            full_name=payload.full_name,
            role_code=payload.role_code,
            department=payload.department,
            title=payload.title,
            phone=payload.phone,
            email=payload.email,
            status=payload.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/collab/contacts/{user_id}", response_model=ContactListOut)
def list_contacts(user_id: str) -> ContactListOut:
    return ContactListOut(user_id=user_id, contacts=collaboration_store.list_contacts(user_id=user_id))


@router.post("/collab/contacts/add", response_model=AccountOut)
def add_contact(payload: ContactAddRequest) -> AccountOut:
    try:
        return collaboration_store.add_contact(user_id=payload.user_id, account=payload.account)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/collab/direct/sessions/{user_id}", response_model=list[DirectSessionOut])
def list_direct_sessions(user_id: str, limit: int = Query(default=100, ge=1, le=300)) -> list[DirectSessionOut]:
    return collaboration_store.list_direct_sessions(user_id=user_id, limit=limit)


@router.get("/collab/admin/direct-sessions", response_model=list[DirectSessionOut])
def admin_list_direct_sessions(
    query: str = Query(default=""),
    status_filter: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
) -> list[DirectSessionOut]:
    return collaboration_store.list_direct_sessions_admin(query=query, status_filter=status_filter, limit=limit)


@router.post("/collab/direct/open", response_model=DirectSessionOut)
def open_direct_session(payload: DirectSessionOpenRequest) -> DirectSessionOut:
    try:
        return collaboration_store.open_direct_session(
            user_id=payload.user_id,
            contact_user_id=payload.contact_user_id,
            patient_id=payload.patient_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/collab/direct/message", response_model=MessageOut)
def send_direct_message(payload: DirectMessageCreateRequest) -> MessageOut:
    try:
        return collaboration_store.send_direct_message(
            session_id=payload.session_id,
            sender_id=payload.sender_id,
            content=payload.content,
            message_type=payload.message_type,
            attachment_refs=payload.attachment_refs,
        )
    except ValueError as exc:
        detail = str(exc)
        code = status.HTTP_404_NOT_FOUND if detail == "session_not_found" else status.HTTP_403_FORBIDDEN
        raise HTTPException(status_code=code, detail=detail) from exc


@router.get("/collab/direct/session/{session_id}", response_model=DirectSessionDetailOut)
def get_direct_session_detail(session_id: str, user_id: str = Query(...)) -> DirectSessionDetailOut:
    detail = collaboration_store.get_direct_session_detail(session_id=session_id, owner_user_id=user_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="direct_session_not_found")
    return detail


@router.get("/collab/admin/direct-sessions/{session_id}", response_model=DirectSessionDetailOut)
def admin_get_direct_session_detail(session_id: str) -> DirectSessionDetailOut:
    detail = collaboration_store.get_direct_session_detail_admin(session_id=session_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="direct_session_not_found")
    return detail


@router.post("/collab/assistant/digest", response_model=AssistantDigestOut)
async def assistant_digest(payload: AssistantDigestRequest) -> AssistantDigestOut:
    context = await _fetch_patient_context(payload.patient_id)
    orders = await _fetch_patient_orders(payload.patient_id)

    risk_tags = context.get("risk_tags", []) if isinstance(context.get("risk_tags"), list) else []
    pending_tasks = context.get("pending_tasks", []) if isinstance(context.get("pending_tasks"), list) else []
    bed_no = str(context.get("bed_no") or "-")

    stats = orders.get("stats", {}) if isinstance(orders, dict) else {}
    pending_count = int(stats.get("pending", 0) or 0)
    due_30m = int(stats.get("due_30m", 0) or 0)
    overdue = int(stats.get("overdue", 0) or 0)

    tasks: list[str] = []
    tasks.extend([f"立即处理：{item}" for item in pending_tasks[:3]])
    if pending_count > 0:
        tasks.append(f"当前有 {pending_count} 项医嘱待执行")
    if due_30m > 0:
        tasks.append(f"{due_30m} 项医嘱 30 分钟内到时")
    if overdue > 0:
        tasks.append(f"存在 {overdue} 项超时医嘱，请优先升级处理")

    suggestions = [
        "先处理 P1 与高警示医嘱，再回填护理文书",
        "涉及升压药/抗凝/输血等场景优先双人核对",
        "异常项先上报医生，再补写执行与复核记录",
    ]

    summary = (
        f"{bed_no}床任务整理："
        f"风险 {('、'.join(risk_tags[:3]) if risk_tags else '暂无高风险标签')}；"
        f"待处理 {len(tasks)} 项。"
    )
    if payload.note:
        summary = f"{summary} 备注：{payload.note}"

    generated_message = (
        f"[AI值班助理 {datetime.now(timezone.utc).strftime('%H:%M')}] "
        f"{bed_no}床请协助处理："
        f"{'；'.join(tasks[:3]) if tasks else '请关注患者变化并完成复核'}。"
    )

    return AssistantDigestOut(
        summary=summary,
        tasks=tasks,
        suggestions=suggestions,
        generated_message=generated_message,
    )


@router.post("/collab/escalate", response_model=ThreadOut)
def escalate(payload: EscalateRequest) -> ThreadOut:
    thread = collaboration_store.close_thread(payload.thread_id)
    if thread is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="thread_not_found")
    return thread


async def _fetch_patient_context(patient_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(8, connect=4), trust_env=False) as client:
        try:
            resp = await client.get(f"{settings.patient_context_service_url}/patients/{patient_id}/context")
            if resp.status_code >= 400:
                return {}
            return resp.json()
        except Exception:
            return {}


async def _fetch_patient_orders(patient_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(8, connect=4), trust_env=False) as client:
        try:
            resp = await client.get(f"{settings.patient_context_service_url}/patients/{patient_id}/orders")
            if resp.status_code >= 400:
                return {}
            return resp.json()
        except Exception:
            return {}
