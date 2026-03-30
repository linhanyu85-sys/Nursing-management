from datetime import date

from fastapi import APIRouter, HTTPException, Query, status

from app.core.config import settings
from app.schemas.handover import (
    HandoverBatchRequest,
    HandoverGenerateRequest,
    HandoverRecord,
    HandoverReviewRequest,
)
from app.services.client import fetch_patient_context, fetch_ward_beds, write_audit_log
from app.services.db_store import handover_db_store
from app.services.generator import build_handover_from_context
from app.services.store import handover_store

router = APIRouter()


def _normalize_user_id(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return "u_linmeili"
    if raw.startswith("u_"):
        return raw
    return f"u_{raw}"


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


@router.post("/handover/generate", response_model=HandoverRecord)
async def generate_handover(payload: HandoverGenerateRequest) -> HandoverRecord:
    context = await fetch_patient_context(payload.patient_id)
    if context is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="patient_context_not_found")

    record = build_handover_from_context(
        patient_id=payload.patient_id,
        context=context,
        shift_date=payload.shift_date or date.today(),
        shift_type=payload.shift_type,
        generated_by=_normalize_user_id(payload.generated_by),
    )
    db_record = await handover_db_store.create_from_record(record)
    if db_record is not None:
        record = db_record
    else:
        record = handover_store.add(record)
    await write_audit_log(
        action="handover.generate",
        resource_type="handover",
        resource_id=record.id,
        detail={"patient_id": payload.patient_id, "shift_type": payload.shift_type},
        user_id=_normalize_user_id(payload.generated_by),
    )
    return record


@router.post("/handover/batch-generate", response_model=list[HandoverRecord])
async def batch_generate(payload: HandoverBatchRequest) -> list[HandoverRecord]:
    beds = await fetch_ward_beds(payload.department_id)
    results: list[HandoverRecord] = []
    for bed in beds:
        patient_id = bed.get("current_patient_id")
        if not patient_id:
            continue
        context = await fetch_patient_context(patient_id)
        if context is None:
            continue
        record = build_handover_from_context(
            patient_id=patient_id,
            context=context,
            shift_date=payload.shift_date or date.today(),
            shift_type=payload.shift_type,
            generated_by=_normalize_user_id(payload.generated_by),
        )
        db_record = await handover_db_store.create_from_record(record)
        if db_record is not None:
            record = db_record
        else:
            record = handover_store.add(record)
        results.append(record)

    await write_audit_log(
        action="handover.batch_generate",
        resource_type="handover_batch",
        resource_id=None,
        detail={"department_id": payload.department_id, "count": len(results)},
        user_id=_normalize_user_id(payload.generated_by),
    )
    return results


@router.get("/handover/{patient_id}/latest", response_model=HandoverRecord)
async def latest_handover(patient_id: str, generated_by: str | None = Query(default=None)) -> HandoverRecord:
    owner = _normalize_user_id(generated_by) if generated_by else None
    item = await handover_db_store.latest_by_patient(patient_id, generated_by=owner)
    if item is None:
        item = handover_store.latest_by_patient_for_user(patient_id, generated_by=owner)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="handover_not_found")
    return item


@router.get("/handover/{patient_id}/history", response_model=list[HandoverRecord])
async def handover_history(
    patient_id: str,
    generated_by: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[HandoverRecord]:
    owner = _normalize_user_id(generated_by) if generated_by else None
    db_items = await handover_db_store.list_by_patient(patient_id, generated_by=owner, limit=limit)
    if db_items is not None:
        return db_items
    if owner:
        return handover_store.list_by_user(owner, patient_id=patient_id, limit=limit)
    return handover_store.list_by_patient(patient_id, limit)


@router.get("/handover/inbox/{generated_by}", response_model=list[HandoverRecord])
async def handover_inbox(
    generated_by: str,
    patient_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[HandoverRecord]:
    owner = _normalize_user_id(generated_by)
    db_items = await handover_db_store.list_by_user(owner, patient_id=patient_id, limit=limit)
    if db_items is not None:
        return db_items
    return handover_store.list_by_user(owner, patient_id=patient_id, limit=limit)


@router.post("/handover/{record_id}/review", response_model=HandoverRecord)
async def review_handover(record_id: str, payload: HandoverReviewRequest) -> HandoverRecord:
    reviewer = _normalize_user_id(payload.reviewed_by)
    item = await handover_db_store.review(record_id, reviewer)
    if item is None:
        item = handover_store.review(record_id, reviewer)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="handover_not_found")
    await write_audit_log(
        action="handover.review",
        resource_type="handover",
        resource_id=record_id,
        detail={"review_note": payload.review_note},
        user_id=reviewer,
    )
    return item
