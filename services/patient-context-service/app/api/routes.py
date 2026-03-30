from fastapi import APIRouter, HTTPException, Query, status

from app.core.config import settings
from app.schemas.patient import (
    AdminPatientCaseRowOut,
    BedOverview,
    DepartmentOptionOut,
    OrderCheckRequest,
    OrderExceptionRequest,
    OrderExecuteRequest,
    OrderRequestCreateRequest,
    OrderListOut,
    OrderOut,
    PatientBase,
    PatientCaseBundleOut,
    PatientCaseUpsertRequest,
    PatientContextOut,
    WardAnalyticsOut,
)
from app.services.repository import repository

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


@router.get("/wards/{department_id}/beds", response_model=list[BedOverview])
async def ward_beds(department_id: str) -> list[BedOverview]:
    return await repository.get_ward_beds(department_id)


@router.get("/wards/all-beds", response_model=list[BedOverview])
@router.get("/wards/_all_beds", response_model=list[BedOverview])
async def ward_beds_all() -> list[BedOverview]:
    return await repository.get_all_beds()


@router.get("/admin/departments", response_model=list[DepartmentOptionOut])
async def admin_departments() -> list[DepartmentOptionOut]:
    return await repository.list_departments()


@router.get("/admin/patient-cases", response_model=list[AdminPatientCaseRowOut])
async def admin_patient_cases(
    department_id: str | None = Query(default=None),
    query: str = Query(default=""),
    current_status: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
) -> list[AdminPatientCaseRowOut]:
    return await repository.list_admin_patient_cases(
        department_id=department_id,
        query=query,
        current_status=current_status,
        limit=limit,
    )


@router.get("/admin/patient-cases/{patient_id}", response_model=PatientCaseBundleOut)
async def admin_patient_case(patient_id: str) -> PatientCaseBundleOut:
    case_bundle = await repository.get_patient_case(patient_id)
    if case_bundle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="patient_case_not_found")
    return case_bundle


@router.get("/admin/ward-analytics", response_model=WardAnalyticsOut)
async def admin_ward_analytics(department_id: str | None = Query(default=None)) -> WardAnalyticsOut:
    return await repository.get_ward_analytics(department_id=department_id)


@router.get("/patients/{patient_id}", response_model=PatientBase)
async def patient_detail(patient_id: str) -> PatientBase:
    patient = await repository.get_patient(patient_id)
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="patient_not_found")
    return patient


@router.get("/patients/{patient_id}/context", response_model=PatientContextOut)
async def patient_context(patient_id: str, requested_by: str | None = Query(default=None)) -> PatientContextOut:
    context = await repository.get_patient_context(patient_id, requested_by=requested_by)
    if context is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="patient_context_not_found")
    return context


@router.get("/patients/{patient_id}/case", response_model=PatientCaseBundleOut)
async def patient_case(patient_id: str) -> PatientCaseBundleOut:
    try:
        case_bundle = await repository.get_patient_case(patient_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    if case_bundle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="patient_case_not_found")
    return case_bundle


@router.post("/cases/upsert", response_model=PatientCaseBundleOut)
async def patient_case_upsert(payload: PatientCaseUpsertRequest) -> PatientCaseBundleOut:
    try:
        return await repository.upsert_patient_case(payload)
    except ValueError as exc:
        detail = str(exc)
        if detail == "bed_already_occupied":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc


@router.get("/beds/{bed_no}/context", response_model=PatientContextOut)
async def context_by_bed(
    bed_no: str,
    department_id: str | None = Query(default=None),
    requested_by: str | None = Query(default=None),
) -> PatientContextOut:
    context = await repository.find_context_by_bed(bed_no=bed_no, department_id=department_id, requested_by=requested_by)
    if context is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bed_context_not_found")
    return context


@router.get("/patients/{patient_id}/orders", response_model=OrderListOut)
async def patient_orders(patient_id: str) -> OrderListOut:
    return await repository.get_patient_orders(patient_id)


@router.get("/patients/{patient_id}/orders/history", response_model=list[OrderOut])
async def patient_order_history(patient_id: str, limit: int = Query(default=50, ge=1, le=200)) -> list[OrderOut]:
    return await repository.get_patient_order_history(patient_id, limit=limit)


@router.post("/orders/{order_id}/double-check", response_model=OrderOut)
async def order_double_check(order_id: str, payload: OrderCheckRequest) -> OrderOut:
    order = await repository.double_check_order(order_id=order_id, checked_by=payload.checked_by, note=payload.note)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="order_not_found")
    return order


@router.post("/orders/{order_id}/execute", response_model=OrderOut)
async def order_execute(order_id: str, payload: OrderExecuteRequest) -> OrderOut:
    order = await repository.execute_order(order_id=order_id, executed_by=payload.executed_by, note=payload.note)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="order_not_found")
    return order


@router.post("/orders/{order_id}/exception", response_model=OrderOut)
async def order_exception(order_id: str, payload: OrderExceptionRequest) -> OrderOut:
    order = await repository.report_order_exception(
        order_id=order_id,
        reported_by=payload.reported_by,
        reason=payload.reason,
    )
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="order_not_found")
    return order


@router.post("/orders/request", response_model=OrderOut)
async def order_request_create(payload: OrderRequestCreateRequest) -> OrderOut:
    return await repository.create_order_request(
        patient_id=payload.patient_id,
        requested_by=payload.requested_by,
        title=payload.title,
        details=payload.details,
        priority=payload.priority,
    )
