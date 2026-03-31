from fastapi import APIRouter, HTTPException, Query, status

from app.core.config import settings
from app.schemas.document import (
    DocumentDraft,
    DocumentTemplate,
    DraftEditRequest,
    DraftRequest,
    DraftReviewRequest,
    DraftSubmitRequest,
    TemplateImportRequest,
)
from app.services.client import fetch_patient_context, write_audit_log
from app.services.db_store import document_db_store
from app.services.generator import build_document_draft
from app.services.store import document_store
from app.services.template_parser import parse_template_import

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
        "local_only_mode": settings.local_only_mode,
    }


@router.post("/document/draft", response_model=DocumentDraft)
async def create_draft(payload: DraftRequest) -> DocumentDraft:
    context = await fetch_patient_context(payload.patient_id)
    if context is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="patient_context_not_found")
    template_text: str | None = payload.template_text
    template_name: str | None = payload.template_name
    if payload.template_id:
        template = document_store.get_template(payload.template_id)
        if template is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="template_not_found")
        template_text = template.template_text
        template_name = template.name

    draft_text, structured_fields = await build_document_draft(
        document_type=payload.document_type,
        spoken_text=payload.spoken_text,
        context=context,
        template_text=template_text,
        template_name=template_name,
    )
    owner = _normalize_user_id(payload.requested_by)
    item = await document_db_store.create(
        patient_id=payload.patient_id,
        encounter_id=context.get("encounter_id"),
        document_type=payload.document_type,
        draft_text=draft_text,
        structured_fields=structured_fields,
        created_by=owner,
    )
    if item is None:
        item = document_store.create(
            patient_id=payload.patient_id,
            encounter_id=context.get("encounter_id"),
            document_type=payload.document_type,
            draft_text=draft_text,
            structured_fields=structured_fields,
            created_by=owner,
        )
    await write_audit_log(
        action="document.draft.create",
        resource_type="document_draft",
        resource_id=item.id,
        detail={
            "patient_id": payload.patient_id,
            "document_type": payload.document_type,
            "template_id": payload.template_id,
            "template_name": template_name,
        },
        user_id=owner,
    )
    return item


@router.post("/document/template/import", response_model=DocumentTemplate)
async def import_template(payload: TemplateImportRequest) -> DocumentTemplate:
    try:
        name, template_text = parse_template_import(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    item = document_store.create_template(
        name=name,
        template_text=template_text,
        source_type="import",
        created_by=_normalize_user_id(payload.requested_by),
    )
    await write_audit_log(
        action="document.template.import",
        resource_type="document_template",
        resource_id=item.id,
        detail={"name": item.name, "length": len(item.template_text)},
        user_id=_normalize_user_id(payload.requested_by),
    )
    return item


@router.get("/document/templates", response_model=list[DocumentTemplate])
async def list_templates() -> list[DocumentTemplate]:
    return document_store.list_templates()


@router.get("/document/drafts/{patient_id}", response_model=list[DocumentDraft])
async def list_drafts(patient_id: str, requested_by: str | None = Query(default=None)) -> list[DocumentDraft]:
    owner = _normalize_user_id(requested_by) if requested_by else None
    db_items = await document_db_store.list_by_patient(patient_id, requested_by=owner)
    if db_items is not None:
        return db_items
    return document_store.list_by_patient(patient_id, requested_by=owner)


@router.get("/document/history", response_model=list[DocumentDraft])
async def document_history(
    patient_id: str | None = Query(default=None),
    requested_by: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[DocumentDraft]:
    owner = _normalize_user_id(requested_by) if requested_by else None
    db_items = await document_db_store.list_history(patient_id=patient_id, requested_by=owner, limit=limit)
    if db_items is not None:
        return db_items
    return document_store.list_history(patient_id=patient_id, requested_by=owner, limit=limit)


@router.get("/document/inbox/{requested_by}", response_model=list[DocumentDraft])
async def document_inbox(
    requested_by: str,
    patient_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[DocumentDraft]:
    owner = _normalize_user_id(requested_by)
    db_items = await document_db_store.list_history(patient_id=patient_id, requested_by=owner, limit=limit)
    if db_items is not None:
        return db_items
    return document_store.list_history(patient_id=patient_id, requested_by=owner, limit=limit)


@router.post("/document/{draft_id}/review", response_model=DocumentDraft)
async def review_draft(draft_id: str, payload: DraftReviewRequest) -> DocumentDraft:
    owner = _normalize_user_id(payload.reviewed_by)
    item = await document_db_store.review(draft_id, owner)
    if item is None:
        item = document_store.review(draft_id, owner)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="draft_not_found")
    await write_audit_log(
        action="document.draft.review",
        resource_type="document_draft",
        resource_id=draft_id,
        detail={"review_note": payload.review_note},
        user_id=owner,
    )
    return item


@router.post("/document/{draft_id}/submit", response_model=DocumentDraft)
async def submit_draft(draft_id: str, payload: DraftSubmitRequest) -> DocumentDraft:
    item = await document_db_store.submit(draft_id)
    if item is None:
        item = document_store.submit(draft_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="draft_not_found")
    await write_audit_log(
        action="document.draft.submit",
        resource_type="document_draft",
        resource_id=draft_id,
        detail={"status": item.status},
        user_id=_normalize_user_id(payload.submitted_by),
    )
    return item


@router.post("/document/{draft_id}/edit", response_model=DocumentDraft)
async def edit_draft(draft_id: str, payload: DraftEditRequest) -> DocumentDraft:
    edited_by = _normalize_user_id(payload.edited_by) if payload.edited_by else None
    item = await document_db_store.edit(draft_id, payload.draft_text, edited_by=edited_by)
    if item is None:
        item = document_store.edit(draft_id, payload.draft_text, edited_by)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="draft_not_found")
    await write_audit_log(
        action="document.draft.edit",
        resource_type="document_draft",
        resource_id=draft_id,
        detail={"edited_by": edited_by, "length": len(payload.draft_text)},
        user_id=edited_by,
    )
    return item
