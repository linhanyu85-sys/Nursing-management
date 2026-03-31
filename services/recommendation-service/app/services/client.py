from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings


async def fetch_patient_context(patient_id: str) -> dict[str, Any] | None:
    url = f"{settings.patient_context_service_url}/patients/{patient_id}/context"
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        try:
            response = await client.get(url)
        except Exception:
            response = None
    if response is not None and response.status_code < 400:
        return response.json()

    should_local_mock = settings.mock_mode and not settings.llm_force_enable
    if should_local_mock:
        return {
            "patient_id": patient_id,
            "bed_no": "",
            "encounter_id": None,
            "diagnoses": ["当前为离线模拟上下文"],
            "risk_tags": ["需人工复核"],
            "pending_tasks": ["补充床号或重新同步患者数据"],
            "latest_observations": [],
        }
    return None


async def fetch_patient_context_by_bed(bed_no: str, department_id: str | None = None) -> dict[str, Any] | None:
    params: dict[str, Any] | None = None
    if department_id:
        params = {"department_id": department_id}

    url = f"{settings.patient_context_service_url}/beds/{bed_no}/context"
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        try:
            response = await client.get(url, params=params)
        except Exception:
            response = None
    if response is not None and response.status_code < 400:
        return response.json()

    should_local_mock = settings.mock_mode and not settings.llm_force_enable
    if should_local_mock:
        return {
            "patient_id": f"bed-{bed_no}",
            "bed_no": str(bed_no),
            "encounter_id": None,
            "diagnoses": ["当前为离线模拟上下文"],
            "risk_tags": ["需人工复核"],
            "pending_tasks": [f"请核对{bed_no}床患者信息"],
            "latest_observations": [],
        }
    return None


async def analyze_multimodal(patient_id: str, input_refs: list[str], question: str) -> dict[str, Any] | None:
    if not input_refs:
        return None

    payload = {
        "patient_id": patient_id,
        "input_refs": input_refs,
        "question": question,
    }
    async with httpx.AsyncClient(timeout=25, trust_env=False) as client:
        response = await client.post(f"{settings.multimodal_service_url}/multimodal/analyze", json=payload)
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
