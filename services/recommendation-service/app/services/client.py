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


async def fetch_patient_context_by_bed(bed_no: str, department_id: str | None = None) -> dict[str, Any] | None:
    should_local_mock = settings.mock_mode and not settings.llm_force_enable
    if should_local_mock:
        if str(bed_no) == "23":
            return {
                "patient_id": "pat-010",
                "bed_no": "23",
                "encounter_id": "enc-010",
                "diagnoses": ["产后出血恢复期"],
                "risk_tags": ["贫血风险", "感染风险"],
                "pending_tasks": ["观察恶露", "监测体温与心率"],
                "latest_observations": [
                    {"name": "血红蛋白", "value": "88 g/L", "abnormal_flag": "low"},
                    {"name": "心率", "value": "104 次/分", "abnormal_flag": "high"},
                ],
            }
        return None

    params: dict[str, Any] | None = None
    if department_id:
        params = {"department_id": department_id}

    url = f"{settings.patient_context_service_url}/beds/{bed_no}/context"
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        response = await client.get(url, params=params)
    if response.status_code >= 400:
        return None
    return response.json()


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
