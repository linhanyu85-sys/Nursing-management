from fastapi import APIRouter, Query

from app.core.config import settings
from app.schemas.audit import AuditLogCreate, AuditLogOut
from app.services.db_store import audit_db_store
from app.services.store import audit_store

router = APIRouter()


@router.get('/health')
def health() -> dict:
    return {'status': 'ok', 'service': settings.service_name}


@router.get('/ready')
def ready() -> dict:
    return {'status': 'ready', 'service': settings.service_name}


@router.get('/version')
def version() -> dict:
    return {
        'service': settings.service_name,
        'version': settings.app_version,
        'env': settings.app_env,
        'mock_mode': settings.mock_mode,
        'audit_use_postgres': settings.audit_use_postgres,
    }


@router.post('/audit/log', response_model=AuditLogOut)
async def write_log(payload: AuditLogCreate) -> AuditLogOut:
    db_item = await audit_db_store.add(payload)
    if db_item is not None:
        return db_item
    return audit_store.add(payload)


@router.get('/audit/{resource_type}/{resource_id}', response_model=list[AuditLogOut])
async def read_logs(resource_type: str, resource_id: str, limit: int = Query(default=50, ge=1, le=200)) -> list[AuditLogOut]:
    db_items = await audit_db_store.list_by_resource(resource_type, resource_id, limit)
    if db_items is not None:
        return db_items
    return audit_store.list_by_resource(resource_type, resource_id, limit)


@router.get('/audit/history', response_model=list[AuditLogOut])
async def read_history(
    requested_by: str | None = Query(default=None),
    action: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AuditLogOut]:
    db_items = await audit_db_store.list_history(requested_by=requested_by, action=action, limit=limit)
    if db_items is not None:
        return db_items
    return audit_store.list_recent(limit=limit, action=action, user_id=requested_by)
