from __future__ import annotations

from datetime import date
from typing import Any

from app.schemas.handover import HandoverRecord
from app.services.store import handover_store


def build_handover_from_context(
    *,
    patient_id: str,
    context: dict[str, Any],
    shift_date: date,
    shift_type: str,
    generated_by: str | None = None,
) -> HandoverRecord:
    risk_tags = context.get("risk_tags", [])
    pending_tasks = context.get("pending_tasks", [])
    observations = context.get("latest_observations", [])
    diagnoses = context.get("diagnoses", [])
    patient_name = str(context.get("patient_name") or context.get("full_name") or "").strip()
    bed_no = str(context.get("bed_no") or "").strip()
    patient_label = f"{bed_no}床{patient_name}".strip()
    if not patient_label:
        patient_label = patient_id

    summary = (
        f"患者 {patient_label} 本班次重点："
        f"诊断 {('、'.join(diagnoses) if diagnoses else '待补充')}；"
        f"风险 {('、'.join(risk_tags) if risk_tags else '暂无')}；"
        f"需优先处理 {('、'.join(pending_tasks[:2]) if pending_tasks else '暂无')}。"
    )

    new_changes = [{"type": "observation", "value": item} for item in observations[:3]]
    worsening_points = [f"{tag} 需持续监测" for tag in risk_tags[:2]]
    improved_points: list[str] = []
    pending_closures = pending_tasks
    next_shift_priorities = pending_tasks[:3] or ["继续评估病情变化并复核生命体征"]

    return handover_store.create(
        patient_id=patient_id,
        encounter_id=context.get("encounter_id"),
        shift_date=shift_date,
        shift_type=shift_type,
        generated_by=generated_by,
        summary=summary,
        new_changes=new_changes,
        worsening_points=worsening_points,
        improved_points=improved_points,
        pending_closures=pending_closures,
        next_shift_priorities=next_shift_priorities,
    )
