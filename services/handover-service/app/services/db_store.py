from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import settings
from app.schemas.handover import HandoverRecord

logger = logging.getLogger(__name__)


class HandoverDbStore:
    def __init__(self) -> None:
        self._engine: AsyncEngine | None = None
        self._db_disabled_until: datetime | None = None

    def _db_enabled(self) -> bool:
        if settings.mock_mode:
            return False
        if not settings.handover_use_postgres:
            return False
        if self._db_disabled_until and datetime.now(timezone.utc) < self._db_disabled_until:
            return False
        return True

    def _mark_db_unavailable(self, reason: str, cooldown_sec: int = 60) -> None:
        self._db_disabled_until = datetime.now(timezone.utc) + timedelta(seconds=max(8, cooldown_sec))
        logger.warning("handover_db_unavailable cooldown_sec=%s reason=%s", cooldown_sec, reason)

    def _engine_or_none(self) -> AsyncEngine | None:
        if not self._db_enabled():
            return None
        if self._engine is None:
            self._engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
        return self._engine

    @staticmethod
    def _owner_username(owner: str | None) -> str:
        raw = (owner or "").strip()
        if not raw:
            return ""
        if raw.startswith("u_"):
            return raw[2:]
        return raw

    @staticmethod
    def _normalize_json_list(raw: Any) -> list[Any]:
        if isinstance(raw, list):
            return raw
        if isinstance(raw, str):
            try:
                data = json.loads(raw)
                if isinstance(data, list):
                    return data
            except Exception:
                return []
        return []

    async def _resolve_user_uuid(self, owner: str | None) -> str | None:
        engine = self._engine_or_none()
        if engine is None:
            return None
        username = self._owner_username(owner)
        if not username:
            return None
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
                row = (await conn.execute(query, {"owner": (owner or "").strip(), "username": username})).mappings().first()
            return str(row["id"]) if row else None
        except Exception as exc:
            self._mark_db_unavailable(f"resolve_user:{exc}", cooldown_sec=40)
            return None

    @classmethod
    def _row_to_record(cls, row: dict[str, Any]) -> HandoverRecord:
        generated_username = str(row.get("generated_by_username") or "").strip()
        reviewed_username = str(row.get("reviewed_by_username") or "").strip()
        generated_by = f"u_{generated_username}" if generated_username else str(row.get("generated_by") or "").strip() or None
        reviewed_by = f"u_{reviewed_username}" if reviewed_username else str(row.get("reviewed_by") or "").strip() or None
        return HandoverRecord(
            id=str(row.get("id")),
            patient_id=str(row.get("patient_id")),
            encounter_id=str(row.get("encounter_id") or "").strip() or None,
            shift_date=row.get("shift_date"),
            shift_type=str(row.get("shift_type") or "day"),
            source_type=str(row.get("source_type") or "ai"),
            summary=str(row.get("summary") or ""),
            new_changes=cls._normalize_json_list(row.get("new_changes")),
            worsening_points=[str(x) for x in cls._normalize_json_list(row.get("worsening_points"))],
            improved_points=[str(x) for x in cls._normalize_json_list(row.get("improved_points"))],
            pending_closures=[str(x) for x in cls._normalize_json_list(row.get("pending_closures"))],
            next_shift_priorities=[str(x) for x in cls._normalize_json_list(row.get("next_shift_priorities"))],
            generated_by=generated_by,
            reviewed_by=reviewed_by,
            reviewed_at=row.get("reviewed_at"),
            created_at=row.get("created_at"),
        )

    async def create_from_record(self, record: HandoverRecord) -> HandoverRecord | None:
        engine = self._engine_or_none()
        if engine is None:
            return None
        generated_by_uuid = await self._resolve_user_uuid(record.generated_by)
        query = text(
            """
            INSERT INTO handover_records (
                patient_id,
                encounter_id,
                shift_date,
                shift_type,
                generated_by,
                source_type,
                summary,
                new_changes,
                worsening_points,
                improved_points,
                pending_closures,
                next_shift_priorities
            )
            VALUES (
                CAST(:patient_id AS uuid),
                CAST(NULLIF(:encounter_id, '') AS uuid),
                :shift_date,
                :shift_type,
                CAST(NULLIF(:generated_by_uuid, '') AS uuid),
                :source_type,
                :summary,
                CAST(:new_changes AS jsonb),
                CAST(:worsening_points AS jsonb),
                CAST(:improved_points AS jsonb),
                CAST(:pending_closures AS jsonb),
                CAST(:next_shift_priorities AS jsonb)
            )
            RETURNING
                id::text AS id,
                patient_id::text AS patient_id,
                encounter_id::text AS encounter_id,
                shift_date,
                shift_type,
                source_type,
                summary,
                new_changes,
                worsening_points,
                improved_points,
                pending_closures,
                next_shift_priorities,
                generated_by::text AS generated_by,
                reviewed_by::text AS reviewed_by,
                reviewed_at,
                created_at
            """
        )
        try:
            async with engine.begin() as conn:
                row = (
                    await conn.execute(
                        query,
                        {
                            "patient_id": record.patient_id,
                            "encounter_id": (record.encounter_id or "").strip(),
                            "shift_date": record.shift_date,
                            "shift_type": record.shift_type,
                            "generated_by_uuid": generated_by_uuid or "",
                            "source_type": record.source_type,
                            "summary": record.summary,
                            "new_changes": json.dumps(record.new_changes or [], ensure_ascii=False),
                            "worsening_points": json.dumps(record.worsening_points or [], ensure_ascii=False),
                            "improved_points": json.dumps(record.improved_points or [], ensure_ascii=False),
                            "pending_closures": json.dumps(record.pending_closures or [], ensure_ascii=False),
                            "next_shift_priorities": json.dumps(record.next_shift_priorities or [], ensure_ascii=False),
                        },
                    )
                ).mappings().first()
            if not row:
                return None
            row_dict = dict(row)
            if generated_by_uuid:
                row_dict["generated_by"] = generated_by_uuid
                row_dict["generated_by_username"] = self._owner_username(record.generated_by)
            return self._row_to_record(row_dict)
        except Exception as exc:
            self._mark_db_unavailable(f"create:{exc}")
            return None

    async def _query_records(
        self,
        *,
        patient_id: str | None = None,
        generated_by: str | None = None,
        limit: int = 50,
    ) -> list[HandoverRecord] | None:
        engine = self._engine_or_none()
        if engine is None:
            return None
        generated_by_uuid = await self._resolve_user_uuid(generated_by)
        query = text(
            """
            SELECT
                h.id::text AS id,
                h.patient_id::text AS patient_id,
                h.encounter_id::text AS encounter_id,
                h.shift_date,
                h.shift_type,
                h.source_type,
                h.summary,
                h.new_changes,
                h.worsening_points,
                h.improved_points,
                h.pending_closures,
                h.next_shift_priorities,
                h.generated_by::text AS generated_by,
                h.reviewed_by::text AS reviewed_by,
                h.reviewed_at,
                h.created_at,
                gu.username AS generated_by_username,
                ru.username AS reviewed_by_username
            FROM handover_records h
            LEFT JOIN users gu ON gu.id = h.generated_by
            LEFT JOIN users ru ON ru.id = h.reviewed_by
            WHERE (:patient_id = '' OR h.patient_id::text = :patient_id)
              AND (:generated_by_uuid = '' OR h.generated_by = CAST(:generated_by_uuid AS uuid))
            ORDER BY h.created_at DESC
            LIMIT :limit
            """
        )
        try:
            async with engine.connect() as conn:
                rows = (
                    await conn.execute(
                        query,
                        {
                            "patient_id": (patient_id or "").strip(),
                            "generated_by_uuid": generated_by_uuid or "",
                            "limit": max(1, int(limit)),
                        },
                    )
                ).mappings().all()
            return [self._row_to_record(dict(row)) for row in rows]
        except Exception as exc:
            self._mark_db_unavailable(f"list:{exc}")
            return None

    async def latest_by_patient(self, patient_id: str, generated_by: str | None = None) -> HandoverRecord | None:
        rows = await self._query_records(patient_id=patient_id, generated_by=generated_by, limit=1)
        if not rows:
            return None
        return rows[0]

    async def list_by_patient(self, patient_id: str, generated_by: str | None = None, limit: int = 50) -> list[HandoverRecord] | None:
        return await self._query_records(patient_id=patient_id, generated_by=generated_by, limit=limit)

    async def list_by_user(self, generated_by: str, patient_id: str | None = None, limit: int = 50) -> list[HandoverRecord] | None:
        return await self._query_records(patient_id=patient_id, generated_by=generated_by, limit=limit)

    async def review(self, record_id: str, reviewed_by: str) -> HandoverRecord | None:
        engine = self._engine_or_none()
        if engine is None:
            return None
        reviewed_by_uuid = await self._resolve_user_uuid(reviewed_by)
        query = text(
            """
            UPDATE handover_records h
            SET
                reviewed_by = CAST(NULLIF(:reviewed_by_uuid, '') AS uuid),
                reviewed_at = NOW()
            WHERE h.id::text = :record_id
            RETURNING
                h.id::text AS id,
                h.patient_id::text AS patient_id,
                h.encounter_id::text AS encounter_id,
                h.shift_date,
                h.shift_type,
                h.source_type,
                h.summary,
                h.new_changes,
                h.worsening_points,
                h.improved_points,
                h.pending_closures,
                h.next_shift_priorities,
                h.generated_by::text AS generated_by,
                h.reviewed_by::text AS reviewed_by,
                h.reviewed_at,
                h.created_at
            """
        )
        try:
            async with engine.begin() as conn:
                row = (
                    await conn.execute(
                        query,
                        {
                            "record_id": record_id,
                            "reviewed_by_uuid": reviewed_by_uuid or "",
                        },
                    )
                ).mappings().first()
            if not row:
                return None
            row_dict = dict(row)
            if reviewed_by_uuid:
                row_dict["reviewed_by"] = reviewed_by_uuid
                row_dict["reviewed_by_username"] = self._owner_username(reviewed_by)
            return self._row_to_record(row_dict)
        except Exception as exc:
            self._mark_db_unavailable(f"review:{exc}")
            return None


handover_db_store = HandoverDbStore()

