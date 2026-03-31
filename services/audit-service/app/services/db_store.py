from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import settings
from app.schemas.audit import AuditLogCreate, AuditLogOut

logger = logging.getLogger(__name__)

UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)


class AuditDbStore:
    def __init__(self) -> None:
        self._engine: AsyncEngine | None = None
        self._db_disabled_until: datetime | None = None

    def _db_enabled(self) -> bool:
        if settings.mock_mode:
            return False
        if not settings.audit_use_postgres:
            return False
        if self._db_disabled_until and datetime.now(timezone.utc) < self._db_disabled_until:
            return False
        return True

    def _mark_db_unavailable(self, reason: str, cooldown_sec: int = 60) -> None:
        sec = max(int(cooldown_sec), 8)
        self._db_disabled_until = datetime.now(timezone.utc) + timedelta(seconds=sec)
        logger.warning("audit_db_unavailable cooldown_sec=%s reason=%s", sec, reason)

    def _engine_or_none(self) -> AsyncEngine | None:
        if not self._db_enabled():
            return None
        if self._engine is None:
            self._engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
        return self._engine

    @staticmethod
    def _normalize_owner_username(value: str | None) -> str:
        raw = (value or "").strip()
        if not raw:
            return ""
        if raw.startswith("u_"):
            return raw[2:]
        return raw

    @staticmethod
    def _as_uuid_text(value: str | None) -> str:
        raw = (value or "").strip()
        if not raw:
            return ""
        return raw if UUID_RE.match(raw) else ""

    async def _resolve_user_uuid(self, user_id: str | None) -> str | None:
        engine = self._engine_or_none()
        if engine is None:
            return None
        raw = (user_id or "").strip()
        if not raw:
            return None
        username = self._normalize_owner_username(raw)
        query = text(
            """
            SELECT id::text AS id
            FROM users
            WHERE id::text = :owner
               OR username = :username
            LIMIT 1
            """
        )
        try:
            async with engine.connect() as conn:
                row = (await conn.execute(query, {"owner": raw, "username": username})).mappings().first()
            return str(row["id"]) if row else None
        except Exception as exc:
            self._mark_db_unavailable(f"resolve_user:{exc}", cooldown_sec=40)
            return None

    @staticmethod
    def _parse_detail(raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                return {}
        return {}

    @classmethod
    def _row_to_out(cls, row: dict[str, Any]) -> AuditLogOut:
        detail = cls._parse_detail(row.get("detail"))
        username = str(row.get("user_username") or "").strip()
        db_user_id = str(row.get("user_id") or "").strip()
        raw_user_id = str(detail.get("_user_id_raw") or "").strip()
        if username:
            user_id = f"u_{username}"
        elif db_user_id:
            user_id = db_user_id
        else:
            user_id = raw_user_id or None

        db_resource_id = str(row.get("resource_id") or "").strip()
        raw_resource_id = str(detail.get("_resource_id_raw") or "").strip()
        resource_id = db_resource_id or raw_resource_id or None

        return AuditLogOut(
            id=str(row.get("id")),
            user_id=user_id,
            action=str(row.get("action") or ""),
            resource_type=str(row.get("resource_type") or ""),
            resource_id=resource_id,
            request_id=str(row.get("request_id") or "").strip() or None,
            detail=detail,
            ip_address=str(row.get("ip_address") or "").strip() or None,
            device_info=str(row.get("device_info") or "").strip() or None,
            created_at=row.get("created_at"),
        )

    async def add(self, payload: AuditLogCreate) -> AuditLogOut | None:
        engine = self._engine_or_none()
        if engine is None:
            return None

        user_uuid = await self._resolve_user_uuid(payload.user_id)
        resource_uuid = self._as_uuid_text(payload.resource_id)
        detail = dict(payload.detail or {})
        if payload.user_id and not user_uuid:
            detail["_user_id_raw"] = payload.user_id
        if payload.resource_id and not resource_uuid:
            detail["_resource_id_raw"] = payload.resource_id

        query = text(
            """
            INSERT INTO audit_logs (
                user_id,
                action,
                resource_type,
                resource_id,
                request_id,
                detail,
                ip_address,
                device_info
            )
            VALUES (
                CAST(NULLIF(:user_uuid, '') AS uuid),
                :action,
                :resource_type,
                CAST(NULLIF(:resource_uuid, '') AS uuid),
                :request_id,
                CAST(:detail AS jsonb),
                :ip_address,
                :device_info
            )
            RETURNING
                id::text AS id,
                user_id::text AS user_id,
                action,
                resource_type,
                resource_id::text AS resource_id,
                request_id,
                detail,
                ip_address,
                device_info,
                created_at
            """
        )
        try:
            async with engine.begin() as conn:
                row = (
                    await conn.execute(
                        query,
                        {
                            "user_uuid": user_uuid or "",
                            "action": payload.action,
                            "resource_type": payload.resource_type,
                            "resource_uuid": resource_uuid,
                            "request_id": payload.request_id,
                            "detail": json.dumps(detail, ensure_ascii=False),
                            "ip_address": payload.ip_address,
                            "device_info": payload.device_info,
                        },
                    )
                ).mappings().first()
                if not row:
                    return None
                row_dict = dict(row)
                if user_uuid:
                    row_dict["user_username"] = self._normalize_owner_username(payload.user_id)
                return self._row_to_out(row_dict)
        except Exception as exc:
            self._mark_db_unavailable(f"add:{exc}")
            return None

    async def list_by_resource(self, resource_type: str, resource_id: str, limit: int = 50) -> list[AuditLogOut] | None:
        engine = self._engine_or_none()
        if engine is None:
            return None
        resource_uuid = self._as_uuid_text(resource_id)
        query = text(
            """
            SELECT
                a.id::text AS id,
                a.user_id::text AS user_id,
                a.action,
                a.resource_type,
                a.resource_id::text AS resource_id,
                a.request_id,
                a.detail,
                a.ip_address,
                a.device_info,
                a.created_at,
                u.username AS user_username
            FROM audit_logs a
            LEFT JOIN users u ON u.id = a.user_id
            WHERE a.resource_type = :resource_type
              AND (
                    (:resource_uuid <> '' AND a.resource_id = CAST(:resource_uuid AS uuid))
                 OR (:resource_uuid = '' AND a.detail ->> '_resource_id_raw' = :resource_id_raw)
              )
            ORDER BY a.created_at DESC
            LIMIT :limit
            """
        )
        try:
            async with engine.connect() as conn:
                rows = (
                    await conn.execute(
                        query,
                        {
                            "resource_type": resource_type,
                            "resource_uuid": resource_uuid,
                            "resource_id_raw": resource_id,
                            "limit": max(int(limit), 1),
                        },
                    )
                ).mappings().all()
            return [self._row_to_out(dict(row)) for row in rows]
        except Exception as exc:
            self._mark_db_unavailable(f"list_by_resource:{exc}")
            return None

    async def list_history(
        self,
        *,
        requested_by: str | None = None,
        action: str | None = None,
        limit: int = 100,
    ) -> list[AuditLogOut] | None:
        engine = self._engine_or_none()
        if engine is None:
            return None
        user_uuid = await self._resolve_user_uuid(requested_by)
        raw_user_id = (requested_by or "").strip()
        query = text(
            """
            SELECT
                a.id::text AS id,
                a.user_id::text AS user_id,
                a.action,
                a.resource_type,
                a.resource_id::text AS resource_id,
                a.request_id,
                a.detail,
                a.ip_address,
                a.device_info,
                a.created_at,
                u.username AS user_username
            FROM audit_logs a
            LEFT JOIN users u ON u.id = a.user_id
            WHERE (:action = '' OR a.action = :action)
              AND (
                    :raw_user_id = ''
                 OR (:user_uuid <> '' AND a.user_id = CAST(:user_uuid AS uuid))
                 OR (:user_uuid = '' AND a.detail ->> '_user_id_raw' = :raw_user_id)
              )
            ORDER BY a.created_at DESC
            LIMIT :limit
            """
        )
        try:
            async with engine.connect() as conn:
                rows = (
                    await conn.execute(
                        query,
                        {
                            "action": (action or "").strip(),
                            "raw_user_id": raw_user_id,
                            "user_uuid": user_uuid or "",
                            "limit": max(int(limit), 1),
                        },
                    )
                ).mappings().all()
            return [self._row_to_out(dict(row)) for row in rows]
        except Exception as exc:
            self._mark_db_unavailable(f"list_history:{exc}")
            return None


audit_db_store = AuditDbStore()

