from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Query, status

from app.core.config import settings
from app.schemas.recommendation import RecommendationOutput, RecommendationRequest
from app.services.client import (
    analyze_multimodal,
    fetch_patient_context,
    fetch_patient_context_by_bed,
    write_audit_log,
)
from app.services.db_store import recommendation_db_store
from app.services.engine import generate_recommendation
from app.services.store import recommendation_store

router = APIRouter()


FOLLOWUP_HINTS = {"那怎么办", "怎么办", "然后呢", "怎么处理", "接下来呢", "需要上报吗", "要紧吗"}
MEDICAL_KEYWORDS = {
    "发热",
    "体温",
    "感染",
    "尿",
    "排尿",
    "导尿",
    "疼",
    "痛",
    "呼吸",
    "气促",
    "喘",
    "血氧",
    "血压",
    "心率",
    "胸闷",
    "胸痛",
    "意识",
    "抽搐",
    "过敏",
    "出血",
    "水肿",
}

def _normalize_user_id(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return "u_linmeili"
    if raw.startswith("u_"):
        return raw
    return f"u_{raw}"


def _extract_bed_no(question: str) -> str | None:
    q = question or ""
    for pattern in (r"(\d{1,3})\s*(?:床|号床|床位)", r"^\s*(\d{1,3})(?=\D|$)"):
        match = re.search(pattern, q)
        if match:
            return match.group(1)
    return None


def _is_short_followup(question: str) -> bool:
    q = (question or "").strip()
    compact = q.replace("？", "").replace("?", "").replace("！", "").replace("!", "")
    if not compact:
        return False
    if compact in FOLLOWUP_HINTS:
        return True
    if compact.startswith(("那", "然后", "接下来")) and len(compact) <= 10:
        return True
    if len(compact) <= 4 and not any(keyword in compact for keyword in MEDICAL_KEYWORDS):
        return True
    return False


def _attachment_brief(attachments: list[str]) -> list[str]:
    brief: list[str] = []
    for idx, item in enumerate(attachments[:8], start=1):
        if item.startswith("data:"):
            mime = item.split(";", 1)[0].replace("data:", "")
            brief.append(f"附件{idx}({mime or 'unknown'})")
        elif item.startswith("http://") or item.startswith("https://"):
            brief.append(f"附件{idx}(url)")
        else:
            text = item if len(item) <= 42 else f"{item[:39]}..."
            brief.append(f"附件{idx}({text})")
    return brief


def _build_effective_question(question: str, context: dict, last_question: str | None) -> str:
    q = (question or "").strip()
    if not _is_short_followup(q):
        return q
    if not last_question:
        return q

    risk_tags = context.get("risk_tags", [])[:4]
    pending = context.get("pending_tasks", [])[:4]
    diagnosis = context.get("diagnoses", [])[:2]
    background = "；".join(
        [
            f"上一问: {last_question or '无'}",
            f"当前诊断: {', '.join(diagnosis) if diagnosis else '未提供'}",
            f"当前风险: {', '.join(risk_tags) if risk_tags else '未提供'}",
            f"待处理任务: {', '.join(pending) if pending else '未提供'}",
            f"本次追问: {q}",
        ]
    )
    return f"这是护理追问场景。请基于背景给出可执行步骤。{background}"


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
        "local_only_mode": settings.local_only_mode,
    }


@router.post("/recommendation/run", response_model=RecommendationOutput)
async def run_recommendation(payload: RecommendationRequest) -> RecommendationOutput:
    resolved_bed_no = payload.bed_no or _extract_bed_no(payload.question)
    context = None
    if resolved_bed_no:
        context = await fetch_patient_context_by_bed(resolved_bed_no, payload.department_id)
    if context is None:
        context = await fetch_patient_context(payload.patient_id)
    if context is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="patient_context_not_found")

    target_patient_id = str(context.get("patient_id") or payload.patient_id)
    owner = _normalize_user_id(payload.requested_by)
    last_question = await recommendation_db_store.get_last_question(target_patient_id, requested_by=owner)
    if not last_question:
        last_question = recommendation_store.get_last_question(target_patient_id)
    effective_question = _build_effective_question(payload.question, context, last_question)
    multimodal = await analyze_multimodal(target_patient_id, payload.attachments, effective_question)

    summary, findings, recommendations, confidence, escalation_rules, review_required = await generate_recommendation(
        payload.question,
        context,
        multimodal,
        payload.attachments,
        llm_question=effective_question,
        fast_mode=bool(payload.fast_mode),
    )

    agent_trace = [
        {"agent": "Intent Router Agent", "status": "done", "note": "识别 recommendation_request"},
        {"agent": "Patient Context Agent", "status": "done", "note": "获取患者上下文"},
        {
            "agent": "Multimodal Medical Agent",
            "status": "done" if payload.attachments else "skipped",
            "note": "附件分析",
        },
        {"agent": "Recommendation Agent", "status": "done", "note": "生成结构化建议"},
        {"agent": "Audit Agent", "status": "done", "note": "写入审计日志"},
    ]

    rec_metadata = {
        "question": payload.question,
        "original_question": payload.question,
        "effective_question": effective_question,
        "resolved_patient_id": target_patient_id,
        "resolved_bed_no": context.get("bed_no"),
        "requested_by": owner,
        "attachment_count": len(payload.attachments),
        "attachments": _attachment_brief(payload.attachments),
        "multimodal": multimodal or {},
        "agent_trace": agent_trace,
    }
    item = await recommendation_db_store.create(
        patient_id=target_patient_id,
        encounter_id=context.get("encounter_id"),
        summary=summary,
        findings=findings,
        recommendations=recommendations,
        confidence=confidence,
        escalation_rules=escalation_rules,
        review_required=review_required,
        metadata=rec_metadata,
    )
    if item is None:
        item = recommendation_store.create(
            patient_id=target_patient_id,
            summary=summary,
            findings=findings,
            recommendations=recommendations,
            confidence=confidence,
            escalation_rules=escalation_rules,
            review_required=review_required,
            metadata=rec_metadata,
        )

    await write_audit_log(
        action="recommendation.run",
        resource_type="recommendation",
        resource_id=item.id,
        detail={
            "patient_id": target_patient_id,
            "question": payload.question,
            "effective_question": effective_question,
            "resolved_bed_no": context.get("bed_no"),
            "review_required": item.review_required,
        },
        user_id=owner,
    )
    return item


@router.get("/recommendation/{patient_id}/latest", response_model=RecommendationOutput)
async def latest_recommendation(patient_id: str, requested_by: str | None = Query(default=None)) -> RecommendationOutput:
    owner = _normalize_user_id(requested_by) if requested_by else None
    item = await recommendation_db_store.latest_by_patient_for_user(patient_id, requested_by=owner)
    if item is not None:
        return item
    items = recommendation_store.list_by_patient_for_user(patient_id, requested_by=owner)
    if not items:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="recommendation_not_found")
    return items[0]


@router.get("/recommendation/{patient_id}/history", response_model=list[RecommendationOutput])
async def recommendation_history(
    patient_id: str,
    requested_by: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[RecommendationOutput]:
    owner = _normalize_user_id(requested_by) if requested_by else None
    db_items = await recommendation_db_store.list_by_patient_for_user(patient_id, requested_by=owner, limit=limit)
    if db_items is not None:
        return db_items
    items = recommendation_store.list_by_patient_for_user(patient_id, requested_by=owner)
    return items[:limit]


@router.get("/recommendation/inbox/{requested_by}", response_model=list[RecommendationOutput])
async def recommendation_inbox(
    requested_by: str,
    patient_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[RecommendationOutput]:
    owner = _normalize_user_id(requested_by)
    db_items = await recommendation_db_store.list_by_user(owner, patient_id=patient_id, limit=limit)
    if db_items is not None:
        return db_items
    return recommendation_store.list_by_user(owner, patient_id=patient_id, limit=limit)
