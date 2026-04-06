from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.services.proxy import forward_get, forward_json

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


@router.post("/api/auth/login")
async def auth_login(payload: dict[str, Any]) -> Any:
    return await forward_json("POST", f"{settings.auth_service_url}/auth/login", payload=payload)


@router.post("/api/auth/register")
async def auth_register(payload: dict[str, Any]) -> Any:
    return await forward_json("POST", f"{settings.auth_service_url}/auth/register", payload=payload)


@router.get("/api/wards/{department_id}/beds")
async def ward_beds(department_id: str) -> Any:
    return await forward_get(f"{settings.patient_context_service_url}/wards/{department_id}/beds")


@router.get("/api/patients/{patient_id}")
async def patient_detail(patient_id: str) -> Any:
    return await forward_get(f"{settings.patient_context_service_url}/patients/{patient_id}")


@router.get("/api/patients/{patient_id}/context")
async def patient_context(patient_id: str) -> Any:
    return await forward_get(f"{settings.patient_context_service_url}/patients/{patient_id}/context")


@router.get("/api/patients/{patient_id}/case")
async def patient_case(patient_id: str) -> Any:
    return await forward_get(f"{settings.patient_context_service_url}/patients/{patient_id}/case")


@router.post("/api/admin/patient-cases")
async def admin_patient_case_upsert(payload: dict[str, Any]) -> Any:
    return await forward_json("POST", f"{settings.patient_context_service_url}/admin/patient-cases", payload=payload)


@router.get("/api/admin/departments")
async def admin_departments() -> Any:
    return await forward_get(f"{settings.patient_context_service_url}/admin/departments")


@router.get("/api/admin/patient-cases")
async def admin_patient_cases(
    department_id: str | None = Query(default=None),
    query: str = Query(default=""),
    current_status: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
) -> Any:
    params: dict[str, Any] = {"query": query, "limit": limit}
    if department_id:
        params["department_id"] = department_id
    if current_status:
        params["current_status"] = current_status
    return await forward_get(f"{settings.patient_context_service_url}/admin/patient-cases", params=params)


@router.get("/api/admin/patient-cases/{patient_id}")
async def admin_patient_case_detail(patient_id: str) -> Any:
    return await forward_get(f"{settings.patient_context_service_url}/admin/patient-cases/{patient_id}")


@router.get("/api/admin/ward-analytics")
async def admin_ward_analytics(department_id: str | None = Query(default=None)) -> Any:
    params: dict[str, Any] = {}
    if department_id:
        params["department_id"] = department_id
    return await forward_get(f"{settings.patient_context_service_url}/admin/ward-analytics", params=params or None)


@router.get("/api/admin/accounts")
async def admin_accounts(query: str = Query(default=""), status_filter: str | None = Query(default=None)) -> Any:
    auth_users = await forward_get(
        f"{settings.auth_service_url}/auth/admin/users",
        params={"query": query, "status_filter": status_filter or ""},
    )
    collab_accounts = await forward_get(
        f"{settings.collaboration_service_url}/collab/admin/accounts",
        params={"query": query, "status_filter": status_filter or ""},
    )
    return _merge_admin_accounts(auth_users, collab_accounts)


@router.post("/api/admin/accounts/upsert")
async def admin_accounts_upsert(payload: dict[str, Any]) -> Any:
    username = str(payload.get("username") or payload.get("account") or "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="username_required")

    auth_payload = {
        "username": username,
        "full_name": payload.get("full_name") or username,
        "role_code": payload.get("role_code") or "nurse",
        "password": payload.get("password"),
        "phone": payload.get("phone"),
        "email": payload.get("email"),
        "department": payload.get("department"),
        "title": payload.get("title"),
        "status": payload.get("status") or "active",
    }
    auth_user = await forward_json(
        "POST",
        f"{settings.auth_service_url}/auth/admin/users/upsert",
        payload=auth_payload,
    )
    collab_user = await forward_json(
        "POST",
        f"{settings.collaboration_service_url}/collab/admin/accounts/upsert",
        payload={
            "id": payload.get("id") or auth_user.get("id"),
            "account": username,
            "full_name": payload.get("full_name") or auth_user.get("full_name") or username,
            "role_code": payload.get("role_code") or auth_user.get("role_code") or "nurse",
            "department": payload.get("department"),
            "title": payload.get("title"),
            "phone": payload.get("phone"),
            "email": payload.get("email"),
            "status": payload.get("status") or auth_user.get("status") or "active",
        },
    )
    merged = _merge_admin_accounts([auth_user], [collab_user])
    return merged[0] if merged else {"username": username, **payload}


@router.get("/api/orders/patients/{patient_id}")
async def patient_orders(patient_id: str) -> Any:
    return await forward_get(f"{settings.patient_context_service_url}/patients/{patient_id}/orders")


@router.get("/api/orders/patients/{patient_id}/history")
async def patient_orders_history(patient_id: str, limit: int = Query(default=50, ge=1, le=200)) -> Any:
    return await forward_get(
        f"{settings.patient_context_service_url}/patients/{patient_id}/orders/history",
        params={"limit": limit},
    )


@router.post("/api/orders/{order_id}/double-check")
async def order_double_check(order_id: str, payload: dict[str, Any]) -> Any:
    return await forward_json(
        "POST",
        f"{settings.patient_context_service_url}/orders/{order_id}/double-check",
        payload=payload,
    )


@router.post("/api/orders/{order_id}/execute")
async def order_execute(order_id: str, payload: dict[str, Any]) -> Any:
    return await forward_json(
        "POST",
        f"{settings.patient_context_service_url}/orders/{order_id}/execute",
        payload=payload,
    )


@router.post("/api/orders/{order_id}/exception")
async def order_exception(order_id: str, payload: dict[str, Any]) -> Any:
    return await forward_json(
        "POST",
        f"{settings.patient_context_service_url}/orders/{order_id}/exception",
        payload=payload,
    )


@router.post("/api/orders/request")
async def order_request_create(payload: dict[str, Any]) -> Any:
    return await forward_json(
        "POST",
        f"{settings.patient_context_service_url}/orders/request",
        payload=payload,
    )


@router.post("/api/voice/upload")
async def voice_upload(payload: dict[str, Any]) -> Any:
    return await forward_json("POST", f"{settings.asr_service_url}/voice/upload", payload=payload)


@router.post("/api/asr/transcribe")
async def asr_transcribe(payload: dict[str, Any]) -> Any:
    return await forward_json("POST", f"{settings.asr_service_url}/asr/transcribe", payload=payload)


@router.post("/api/tts/speak")
async def tts_speak(payload: dict[str, Any]) -> Any:
    return await forward_json("POST", f"{settings.tts_service_url}/tts/speak", payload=payload)


@router.get("/api/device/binding")
async def device_binding() -> Any:
    return await forward_get(f"{settings.device_gateway_service_url}/api/device/binding")


@router.post("/api/device/bind")
async def device_bind(payload: dict[str, Any]) -> Any:
    return await forward_json("POST", f"{settings.device_gateway_service_url}/api/device/bind", payload=payload)


@router.post("/api/device/audio/upload")
async def device_audio_upload(request: Request) -> Any:
    body = await request.body()
    content_type = request.headers.get("content-type", "application/octet-stream")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=8), trust_env=False) as client:
            response = await client.post(
                f"{settings.device_gateway_service_url}/api/device/audio/upload",
                content=body,
                headers={"content-type": content_type},
            )
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="upstream_timeout") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="upstream_unavailable") from exc
    if response.status_code >= 400:
        detail: Any = response.text or "upstream_error"
        try:
            parsed = response.json()
            detail = parsed.get("detail", parsed) if isinstance(parsed, dict) else parsed
        except Exception:
            pass
        raise HTTPException(status_code=response.status_code, detail=detail)
    try:
        return response.json()
    except Exception:
        return {"raw": response.text}


@router.post("/api/device/query")
async def device_query(payload: dict[str, Any]) -> Any:
    return await forward_json("POST", f"{settings.device_gateway_service_url}/api/device/query", payload=payload)


@router.get("/api/device/result/{session_id}")
async def device_result(session_id: str) -> Any:
    return await forward_get(f"{settings.device_gateway_service_url}/api/device/result/{session_id}")


@router.get("/api/device/audio/{session_id}")
async def device_audio(session_id: str) -> Response:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=8), trust_env=False) as client:
            response = await client.get(f"{settings.device_gateway_service_url}/api/device/audio/{session_id}")
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="upstream_timeout") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="upstream_unavailable") from exc
    if response.status_code >= 400:
        detail: Any = response.text or "upstream_error"
        try:
            parsed = response.json()
            detail = parsed.get("detail", parsed) if isinstance(parsed, dict) else parsed
        except Exception:
            pass
        raise HTTPException(status_code=response.status_code, detail=detail)
    media_type = response.headers.get("content-type", "audio/wav")
    return Response(content=response.content, media_type=media_type)


@router.post("/api/device/heartbeat")
async def device_heartbeat(payload: dict[str, Any]) -> Any:
    return await forward_json("POST", f"{settings.device_gateway_service_url}/api/device/heartbeat", payload=payload)


@router.get("/api/device/sessions")
async def device_sessions() -> Any:
    return await forward_get(f"{settings.device_gateway_service_url}/api/device/sessions")


@router.get("/api/device/silent")
async def device_silent_get() -> Any:
    return await forward_get(f"{settings.device_gateway_service_url}/api/device/silent")


@router.post("/api/device/silent")
async def device_silent_set(payload: dict[str, Any]) -> Any:
    return await forward_json("POST", f"{settings.device_gateway_service_url}/api/device/silent", payload=payload)


@router.post("/api/handover/generate")
async def handover_generate(payload: dict[str, Any]) -> Any:
    return await forward_json("POST", f"{settings.handover_service_url}/handover/generate", payload=payload)


@router.post("/api/handover/batch-generate")
async def handover_batch_generate(payload: dict[str, Any]) -> Any:
    return await forward_json("POST", f"{settings.handover_service_url}/handover/batch-generate", payload=payload)


@router.get("/api/handover/{patient_id}/latest")
async def handover_latest(patient_id: str, generated_by: str | None = Query(default=None)) -> Any:
    params: dict[str, Any] = {}
    if generated_by:
        params["generated_by"] = generated_by
    return await forward_get(f"{settings.handover_service_url}/handover/{patient_id}/latest", params=params or None)


@router.get("/api/handover/{patient_id}/history")
async def handover_history(
    patient_id: str,
    generated_by: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    params: dict[str, Any] = {"limit": limit}
    if generated_by:
        params["generated_by"] = generated_by
    return await forward_get(
        f"{settings.handover_service_url}/handover/{patient_id}/history",
        params=params,
    )


@router.get("/api/handover/inbox/{generated_by}")
async def handover_inbox(
    generated_by: str,
    patient_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    params: dict[str, Any] = {"limit": limit}
    if patient_id:
        params["patient_id"] = patient_id
    return await forward_get(
        f"{settings.handover_service_url}/handover/inbox/{generated_by}",
        params=params,
    )


@router.post("/api/handover/{record_id}/review")
async def handover_review(record_id: str, payload: dict[str, Any]) -> Any:
    return await forward_json("POST", f"{settings.handover_service_url}/handover/{record_id}/review", payload=payload)


@router.post("/api/recommendation/run")
async def recommendation_run(payload: dict[str, Any]) -> Any:
    return await forward_json("POST", f"{settings.recommendation_service_url}/recommendation/run", payload=payload)


@router.get("/api/recommendation/{patient_id}/history")
async def recommendation_history(
    patient_id: str,
    requested_by: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    params: dict[str, Any] = {"limit": limit}
    if requested_by:
        params["requested_by"] = requested_by
    return await forward_get(
        f"{settings.recommendation_service_url}/recommendation/{patient_id}/history",
        params=params,
    )


@router.get("/api/recommendation/inbox/{requested_by}")
async def recommendation_inbox(
    requested_by: str,
    patient_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    params: dict[str, Any] = {"limit": limit}
    if patient_id:
        params["patient_id"] = patient_id
    return await forward_get(
        f"{settings.recommendation_service_url}/recommendation/inbox/{requested_by}",
        params=params,
    )


@router.post("/api/document/draft")
async def document_draft(payload: dict[str, Any]) -> Any:
    return await forward_json("POST", f"{settings.document_service_url}/document/draft", payload=payload)


@router.post("/api/document/template/import")
async def document_template_import(payload: dict[str, Any]) -> Any:
    return await forward_json("POST", f"{settings.document_service_url}/document/template/import", payload=payload)


@router.get("/api/document/templates")
async def document_templates() -> Any:
    return await forward_get(f"{settings.document_service_url}/document/templates")


@router.get("/api/document/drafts/{patient_id}")
async def document_drafts(patient_id: str, requested_by: str | None = Query(default=None)) -> Any:
    params: dict[str, Any] = {}
    if requested_by:
        params["requested_by"] = requested_by
    return await forward_get(f"{settings.document_service_url}/document/drafts/{patient_id}", params=params or None)


@router.get("/api/document/history")
async def document_history(
    patient_id: str | None = Query(default=None),
    requested_by: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    params: dict[str, Any] = {"limit": limit}
    if patient_id:
        params["patient_id"] = patient_id
    if requested_by:
        params["requested_by"] = requested_by
    return await forward_get(f"{settings.document_service_url}/document/history", params=params)


@router.get("/api/document/inbox/{requested_by}")
async def document_inbox(
    requested_by: str,
    patient_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    params: dict[str, Any] = {"limit": limit}
    if patient_id:
        params["patient_id"] = patient_id
    return await forward_get(
        f"{settings.document_service_url}/document/inbox/{requested_by}",
        params=params,
    )


@router.post("/api/document/{draft_id}/review")
async def document_review(draft_id: str, payload: dict[str, Any]) -> Any:
    return await forward_json("POST", f"{settings.document_service_url}/document/{draft_id}/review", payload=payload)


@router.post("/api/document/{draft_id}/submit")
async def document_submit(draft_id: str, payload: dict[str, Any]) -> Any:
    return await forward_json("POST", f"{settings.document_service_url}/document/{draft_id}/submit", payload=payload)


@router.post("/api/document/{draft_id}/edit")
async def document_edit(draft_id: str, payload: dict[str, Any]) -> Any:
    return await forward_json("POST", f"{settings.document_service_url}/document/{draft_id}/edit", payload=payload)


@router.post("/api/multimodal/analyze")
async def multimodal_analyze(payload: dict[str, Any]) -> Any:
    return await forward_json("POST", f"{settings.multimodal_service_url}/multimodal/analyze", payload=payload)


@router.post("/api/collab/thread")
async def collab_thread(payload: dict[str, Any]) -> Any:
    return await forward_json("POST", f"{settings.collaboration_service_url}/collab/thread", payload=payload)


@router.post("/api/collab/message")
async def collab_message(payload: dict[str, Any]) -> Any:
    return await forward_json("POST", f"{settings.collaboration_service_url}/collab/message", payload=payload)


@router.get("/api/collab/accounts")
async def collab_accounts(query: str = Query(default=""), exclude_user_id: str | None = Query(default=None)) -> Any:
    params: dict[str, Any] = {"query": query}
    if exclude_user_id:
        params["exclude_user_id"] = exclude_user_id
    return await forward_get(f"{settings.collaboration_service_url}/collab/accounts", params=params)


@router.get("/api/collab/contacts/{user_id}")
async def collab_contacts(user_id: str) -> Any:
    return await forward_get(f"{settings.collaboration_service_url}/collab/contacts/{user_id}")


@router.post("/api/collab/contacts/add")
async def collab_contacts_add(payload: dict[str, Any]) -> Any:
    return await forward_json("POST", f"{settings.collaboration_service_url}/collab/contacts/add", payload=payload)


@router.get("/api/collab/direct/sessions/{user_id}")
async def collab_direct_sessions(user_id: str, limit: int = Query(default=100, ge=1, le=300)) -> Any:
    return await forward_get(
        f"{settings.collaboration_service_url}/collab/direct/sessions/{user_id}",
        params={"limit": limit},
    )


@router.get("/api/admin/direct-sessions")
async def admin_direct_sessions(
    query: str = Query(default=""),
    status_filter: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
) -> Any:
    return await forward_get(
        f"{settings.collaboration_service_url}/collab/admin/direct-sessions",
        params={"query": query, "status_filter": status_filter or "", "limit": limit},
    )


@router.post("/api/collab/direct/open")
async def collab_direct_open(payload: dict[str, Any]) -> Any:
    return await forward_json("POST", f"{settings.collaboration_service_url}/collab/direct/open", payload=payload)


@router.post("/api/collab/direct/message")
async def collab_direct_message(payload: dict[str, Any]) -> Any:
    return await forward_json("POST", f"{settings.collaboration_service_url}/collab/direct/message", payload=payload)


@router.get("/api/collab/direct/session/{session_id}")
async def collab_direct_session(session_id: str, user_id: str = Query(...)) -> Any:
    return await forward_get(
        f"{settings.collaboration_service_url}/collab/direct/session/{session_id}",
        params={"user_id": user_id},
    )


@router.get("/api/admin/direct-sessions/{session_id}")
async def admin_direct_session_detail(session_id: str) -> Any:
    return await forward_get(f"{settings.collaboration_service_url}/collab/admin/direct-sessions/{session_id}")


@router.post("/api/collab/assistant/digest")
async def collab_assistant_digest(payload: dict[str, Any]) -> Any:
    return await forward_json("POST", f"{settings.collaboration_service_url}/collab/assistant/digest", payload=payload)


@router.get("/api/collab/thread/{thread_id}")
async def collab_get_thread(thread_id: str) -> Any:
    return await forward_get(f"{settings.collaboration_service_url}/collab/thread/{thread_id}")


@router.get("/api/collab/history")
async def collab_history(
    patient_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    params: dict[str, Any] = {"limit": limit}
    if patient_id:
        params["patient_id"] = patient_id
    return await forward_get(f"{settings.collaboration_service_url}/collab/history", params=params)


@router.post("/api/collab/escalate")
async def collab_escalate(payload: dict[str, Any]) -> Any:
    return await forward_json("POST", f"{settings.collaboration_service_url}/collab/escalate", payload=payload)


@router.get("/api/audit/{resource_type}/{resource_id}")
async def audit_get(resource_type: str, resource_id: str, limit: int = Query(default=50, ge=1, le=200)) -> Any:
    return await forward_get(
        f"{settings.audit_service_url}/audit/{resource_type}/{resource_id}",
        params={"limit": limit},
    )


@router.get("/api/audit/history")
async def audit_history(
    requested_by: str | None = Query(default=None),
    action: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> Any:
    params: dict[str, Any] = {"limit": limit}
    if requested_by:
        params["requested_by"] = requested_by
    if action:
        params["action"] = action
    return await forward_get(f"{settings.audit_service_url}/audit/history", params=params)


@router.post("/api/workflow/run")
async def workflow_run(payload: dict[str, Any]) -> Any:
    return await forward_json("POST", f"{settings.agent_orchestrator_service_url}/workflow/run", payload=payload)


@router.get("/api/ai/models")
async def ai_models() -> Any:
    return await forward_get(f"{settings.agent_orchestrator_service_url}/ai/models")


@router.get("/api/ai/runtime")
async def ai_runtime_status() -> Any:
    return await forward_get(f"{settings.agent_orchestrator_service_url}/ai/runtime")


@router.post("/api/ai/runtime")
async def ai_runtime_set(payload: dict[str, Any]) -> Any:
    return await forward_json("POST", f"{settings.agent_orchestrator_service_url}/ai/runtime", payload=payload)


@router.delete("/api/ai/runtime")
async def ai_runtime_clear() -> Any:
    return await forward_json("DELETE", f"{settings.agent_orchestrator_service_url}/ai/runtime")


@router.get("/api/ai/runs")
async def ai_runs(
    patient_id: str | None = Query(default=None),
    conversation_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    workflow_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    params: dict[str, Any] = {"limit": limit}
    if patient_id:
        params["patient_id"] = patient_id
    if conversation_id:
        params["conversation_id"] = conversation_id
    if status:
        params["status"] = status
    if workflow_type:
        params["workflow_type"] = workflow_type
    return await forward_get(f"{settings.agent_orchestrator_service_url}/ai/runs", params=params)


@router.get("/api/ai/runs/{run_id}")
async def ai_run_detail(run_id: str) -> Any:
    return await forward_get(f"{settings.agent_orchestrator_service_url}/ai/runs/{run_id}")


@router.post("/api/ai/runs/{run_id}/retry")
async def ai_run_retry(run_id: str) -> Any:
    return await forward_json("POST", f"{settings.agent_orchestrator_service_url}/ai/runs/{run_id}/retry")


@router.post("/api/ai/queue/tasks")
async def ai_queue_enqueue(payload: dict[str, Any]) -> Any:
    return await forward_json("POST", f"{settings.agent_orchestrator_service_url}/ai/queue/tasks", payload=payload)


@router.get("/api/ai/queue/tasks")
async def ai_queue_tasks(
    patient_id: str | None = Query(default=None),
    conversation_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    params: dict[str, Any] = {"limit": limit}
    if patient_id:
        params["patient_id"] = patient_id
    if conversation_id:
        params["conversation_id"] = conversation_id
    if status:
        params["status"] = status
    return await forward_get(f"{settings.agent_orchestrator_service_url}/ai/queue/tasks", params=params)


@router.get("/api/ai/queue/tasks/{task_id}")
async def ai_queue_task_detail(task_id: str) -> Any:
    return await forward_get(f"{settings.agent_orchestrator_service_url}/ai/queue/tasks/{task_id}")


@router.post("/api/ai/queue/tasks/{task_id}/approve")
async def ai_queue_task_approve(task_id: str, payload: dict[str, Any]) -> Any:
    return await forward_json(
        "POST",
        f"{settings.agent_orchestrator_service_url}/ai/queue/tasks/{task_id}/approve",
        payload=payload,
    )


@router.post("/api/ai/queue/tasks/{task_id}/reject")
async def ai_queue_task_reject(task_id: str, payload: dict[str, Any]) -> Any:
    return await forward_json(
        "POST",
        f"{settings.agent_orchestrator_service_url}/ai/queue/tasks/{task_id}/reject",
        payload=payload,
    )


@router.post("/api/ai/chat")
async def ai_chat(payload: dict[str, Any]) -> Any:
    return await forward_json("POST", f"{settings.agent_orchestrator_service_url}/ai/chat", payload=payload)


@router.get("/api/workflow/history")
async def workflow_history(
    patient_id: str | None = Query(default=None),
    conversation_id: str | None = Query(default=None),
    requested_by: str | None = Query(default=None),
    workflow_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    params: dict[str, Any] = {"limit": limit}
    if patient_id:
        params["patient_id"] = patient_id
    if conversation_id:
        params["conversation_id"] = conversation_id
    if requested_by:
        params["requested_by"] = requested_by
    if workflow_type:
        params["workflow_type"] = workflow_type
    return await forward_get(f"{settings.agent_orchestrator_service_url}/workflow/history", params=params)


def _time_key(x: dict[str, Any]) -> datetime:
    ts = str(x.get("created_at") or "")
    if ts == "":
        return datetime.fromtimestamp(0, timezone.utc)
    try:
        s = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except ValueError:
        return datetime.fromtimestamp(0, timezone.utc)


@router.get("/api/conversation/history")
async def conversation_history(
    patient_id: str,
    conversation_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, Any]]:
    return await _agg_hist(pid=patient_id, cid=conversation_id, lim=limit)


@router.get("/api/history/all")
async def all_history(
    patient_id: str,
    conversation_id: str | None = Query(default=None),
    limit: int = Query(default=80, ge=1, le=300),
) -> list[dict[str, Any]]:
    return await _agg_hist(pid=patient_id, cid=conversation_id, lim=limit)


async def _agg_hist(*, pid: str, cid: str | None, lim: int) -> list[dict[str, Any]]:
    rec_data = await _get_json(
        f"{settings.recommendation_service_url}/recommendation/{pid}/history",
        params={"limit": lim},
    )
    wf_data = await _get_json(
        f"{settings.agent_orchestrator_service_url}/workflow/history",
        params={"patient_id": pid, "conversation_id": cid, "limit": lim},
    )
    doc_data = await _get_json(
        f"{settings.document_service_url}/document/history",
        params={"patient_id": pid, "limit": lim},
    )
    ho_data = await _get_json(
        f"{settings.handover_service_url}/handover/{pid}/history",
        params={"limit": lim},
    )
    col_data = await _get_json(
        f"{settings.collaboration_service_url}/collab/history",
        params={"patient_id": pid, "limit": lim},
    )

    lst: list[dict[str, Any]] = []

    if isinstance(rec_data, list):
        for r in rec_data:
            ok = isinstance(r, dict)
            if not ok:
                continue
            meta = r.get("metadata")
            if not isinstance(meta, dict):
                meta = {}
            q = meta.get("original_question")
            if not q:
                q = meta.get("question")
            lst.append(
                {
                    "id": r.get("id"),
                    "source": "recommendation-service",
                    "workflow_type": "recommendation_request",
                    "patient_id": r.get("patient_id"),
                    "conversation_id": meta.get("conversation_id"),
                    "requested_by": meta.get("requested_by"),
                    "user_input": q or "",
                    "summary": r.get("summary") or "",
                    "created_at": r.get("created_at"),
                    "confidence": r.get("confidence"),
                    "review_required": r.get("review_required"),
                }
            )

    if isinstance(wf_data, list):
        for w in wf_data:
            ok = isinstance(w, dict)
            if not ok:
                continue
            lst.append(
                {
                    "id": w.get("id"),
                    "source": "agent-orchestrator",
                    "workflow_type": w.get("workflow_type"),
                    "patient_id": w.get("patient_id"),
                    "conversation_id": w.get("conversation_id"),
                    "requested_by": w.get("requested_by"),
                    "user_input": w.get("user_input") or "",
                    "summary": w.get("summary") or "",
                    "created_at": w.get("created_at"),
                    "confidence": w.get("confidence"),
                    "review_required": w.get("review_required"),
                }
            )

    if isinstance(doc_data, list):
        for d in doc_data:
            ok = isinstance(d, dict)
            if not ok:
                continue
            tpl = ""
            sf = d.get("structured_fields")
            if isinstance(sf, dict):
                tpl = str(sf.get("template_name") or "")
            txt = str(d.get("draft_text") or "")
            txt = txt.replace("\n", " ").strip()
            short = txt[:180]
            if len(txt) > 180:
                short = short + "..."
            lst.append(
                {
                    "id": d.get("id"),
                    "source": "document-service",
                    "workflow_type": "document_generation",
                    "patient_id": d.get("patient_id"),
                    "conversation_id": None,
                    "requested_by": d.get("created_by"),
                    "user_input": tpl,
                    "summary": short,
                    "created_at": d.get("updated_at") or d.get("created_at"),
                    "confidence": None,
                    "review_required": True,
                }
            )

    if isinstance(ho_data, list):
        for h in ho_data:
            ok = isinstance(h, dict)
            if not ok:
                continue
            sd = h.get("shift_date")
            st = h.get("shift_type")
            lst.append(
                {
                    "id": h.get("id"),
                    "source": "handover-service",
                    "workflow_type": "handover_generate",
                    "patient_id": h.get("patient_id"),
                    "conversation_id": None,
                    "requested_by": h.get("generated_by"),
                    "user_input": f"{sd} {st}",
                    "summary": h.get("summary") or "",
                    "created_at": h.get("created_at"),
                    "confidence": None,
                    "review_required": True,
                }
            )

    if isinstance(col_data, list):
        for c in col_data:
            ok = isinstance(c, dict)
            if not ok:
                continue
            thr = c.get("thread")
            msg = c.get("latest_message")
            if not isinstance(thr, dict):
                continue
            cnt = ""
            ts = thr.get("updated_at") or thr.get("created_at")
            if isinstance(msg, dict):
                cnt = str(msg.get("content") or "")
                ts = msg.get("created_at") or ts
            lst.append(
                {
                    "id": thr.get("id"),
                    "source": "collaboration-service",
                    "workflow_type": "collaboration",
                    "patient_id": thr.get("patient_id"),
                    "conversation_id": None,
                    "requested_by": thr.get("created_by"),
                    "user_input": thr.get("title") or "",
                    "summary": cnt or "会话已创建，暂无消息",
                    "created_at": ts,
                    "confidence": None,
                    "review_required": False,
                }
            )

    if cid:
        flt = []
        for x in lst:
            cv = x.get("conversation_id")
            if str(cv or "") == cid:
                flt.append(x)
        lst = flt

    lst.sort(key=_time_key, reverse=True)
    return lst[:lim]


async def _get_json(url: str, params: dict[str, Any] | None = None) -> dict[str, Any] | list[Any] | None:
    async with httpx.AsyncClient(timeout=8, trust_env=False) as c:
        try:
            rsp = await c.get(url, params=params)
            code = rsp.status_code
            if code >= 400:
                return None
            return rsp.json()
        except Exception:
            return None


def _merge_admin_accounts(auth_users: Any, collab_accounts: Any) -> list[dict[str, Any]]:
    auth_list = auth_users if isinstance(auth_users, list) else []
    collab_list = collab_accounts if isinstance(collab_accounts, list) else []
    merged: dict[str, dict[str, Any]] = {}

    for item in auth_list:
        if not isinstance(item, dict):
            continue
        username = str(item.get("username") or "").strip()
        if not username:
            continue
        merged[username] = {
            "id": item.get("id"),
            "username": username,
            "account": username,
            "full_name": item.get("full_name") or username,
            "role_code": item.get("role_code") or "nurse",
            "phone": item.get("phone"),
            "email": item.get("email"),
            "department": item.get("department"),
            "title": item.get("title"),
            "status": item.get("status") or "active",
        }

    for item in collab_list:
        if not isinstance(item, dict):
            continue
        username = str(item.get("account") or item.get("username") or "").strip()
        if not username:
            continue
        row = merged.get(username, {"username": username, "account": username})
        row.update(
            {
                "id": item.get("id") or row.get("id"),
                "full_name": item.get("full_name") or row.get("full_name") or username,
                "role_code": item.get("role_code") or row.get("role_code") or "nurse",
                "department": item.get("department") if item.get("department") is not None else row.get("department"),
                "title": item.get("title") if item.get("title") is not None else row.get("title"),
                "phone": item.get("phone") if item.get("phone") is not None else row.get("phone"),
                "email": item.get("email") if item.get("email") is not None else row.get("email"),
                "status": item.get("status") or row.get("status") or "active",
            }
        )
        merged[username] = row

    rows = list(merged.values())
    rows.sort(key=lambda item: (str(item.get("role_code") or ""), str(item.get("full_name") or ""), str(item.get("username") or "")))
    return rows


@router.websocket("/ws/patient-context/{patient_id}")
async def ws_patient_context(websocket: WebSocket, patient_id: str) -> None:
    await websocket.accept()
    last_hash = ""
    try:
        while True:
            data = await _get_json(f"{settings.patient_context_service_url}/patients/{patient_id}/context")
            if data is not None:
                payload = {
                    "type": "patient_context_update",
                    "patient_id": patient_id,
                    "server_time": datetime.now(timezone.utc).isoformat(),
                    "data": data,
                }
                current_hash = hashlib.md5(
                    json.dumps(payload["data"], ensure_ascii=False, sort_keys=True).encode("utf-8")
                ).hexdigest()
                if current_hash != last_hash:
                    await websocket.send_json(payload)
                    last_hash = current_hash
                else:
                    await websocket.send_json(
                        {
                            "type": "heartbeat",
                            "patient_id": patient_id,
                            "server_time": datetime.now(timezone.utc).isoformat(),
                        }
                    )
            else:
                await websocket.send_json(
                    {
                        "type": "error",
                        "patient_id": patient_id,
                        "message": "patient_context_unavailable",
                        "server_time": datetime.now(timezone.utc).isoformat(),
                    }
                )
            await asyncio.sleep(3)
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await websocket.close()
        except Exception:
            return


@router.websocket("/ws/ward-beds/{department_id}")
async def ws_ward_beds(websocket: WebSocket, department_id: str) -> None:
    await websocket.accept()
    last_hash = ""
    try:
        while True:
            data = await _get_json(f"{settings.patient_context_service_url}/wards/{department_id}/beds")
            if data is not None:
                payload = {
                    "type": "ward_beds_update",
                    "department_id": department_id,
                    "server_time": datetime.now(timezone.utc).isoformat(),
                    "data": data,
                }
                current_hash = hashlib.md5(
                    json.dumps(payload["data"], ensure_ascii=False, sort_keys=True).encode("utf-8")
                ).hexdigest()
                if current_hash != last_hash:
                    await websocket.send_json(payload)
                    last_hash = current_hash
                else:
                    await websocket.send_json(
                        {
                            "type": "heartbeat",
                            "department_id": department_id,
                            "server_time": datetime.now(timezone.utc).isoformat(),
                        }
                    )
            else:
                await websocket.send_json(
                    {
                        "type": "error",
                        "department_id": department_id,
                        "message": "ward_data_unavailable",
                        "server_time": datetime.now(timezone.utc).isoformat(),
                    }
                )
            await asyncio.sleep(3)
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await websocket.close()
        except Exception:
            return
