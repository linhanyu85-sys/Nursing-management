from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings


async def fetch_patient_context(patient_id: str) -> dict[str, Any] | None:
    should_local_mock = settings.mock_mode and not settings.llm_force_enable
    if should_local_mock:
        return {
            "patient_id": patient_id,
            "bed_no": "12",
            "encounter_id": "enc-001",
            "diagnoses": ["慢性心衰急性加重"],
            "risk_tags": ["低血压风险", "液体管理风险"],
            "pending_tasks": ["复测血压", "记录尿量"],
        }

    url = f"{settings.patient_context_service_url}/patients/{patient_id}/context"
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        response = await client.get(url)
    if response.status_code >= 400:
        return None
    return response.json()


async def write_audit_log(
    action: str,
    resource_type: str,
    resource_id: str | None,
    detail: dict[str, Any],
    user_id: str | None = None,
) -> None:
    payload = {
        "user_id": user_id,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "detail": detail,
    }
    async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
        try:
            await client.post(f"{settings.audit_service_url}/audit/log", json=payload)
        except Exception:
            return
