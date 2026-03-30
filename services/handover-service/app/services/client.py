from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings


async def fetch_patient_context(patient_id: str) -> dict[str, Any] | None:
    if settings.mock_mode:
        return {
            "patient_id": patient_id,
            "bed_no": "12",
            "encounter_id": "enc-001",
            "diagnoses": ["慢性心衰急性加重"],
            "risk_tags": ["低血压风险", "液体管理风险"],
            "pending_tasks": ["复测血压", "记录尿量"],
            "latest_observations": [
                {"name": "收缩压", "value": "88 mmHg", "abnormal_flag": "low"},
                {"name": "4小时尿量", "value": "85 ml", "abnormal_flag": "low"},
            ],
        }

    url = f"{settings.patient_context_service_url}/patients/{patient_id}/context"
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        response = await client.get(url)
    if response.status_code >= 400:
        return None
    return response.json()


async def fetch_ward_beds(department_id: str) -> list[dict[str, Any]]:
    if settings.mock_mode:
        return [
            {"bed_no": "12", "current_patient_id": "pat-001"},
            {"bed_no": "15", "current_patient_id": "pat-002"},
        ]

    url = f"{settings.patient_context_service_url}/wards/{department_id}/beds"
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        response = await client.get(url)
    if response.status_code >= 400:
        return []
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
