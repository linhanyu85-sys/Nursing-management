from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import settings
from app.schemas.document import DocumentDraft

logger = logging.getLogger(__name__)


class DocumentDraftDbStore:
    def __init__(self) -> None:
        self._engine: AsyncEngine | None = None
        self._db_disabled_until: datetime | None = None

    def _db_enabled(self) -> bool:
        if settings.mock_mode:
            return False
        if not settings.document_use_postgres:
            return False
        if self._db_disabled_until and datetime.now(timezone.utc) < self._db_disabled_until:
            return False
        return True

    def _mark_db_unavailable(self, reason: str, cooldown_sec: int = 60) -> None:
        self._db_disabled_until = datetime.now(timezone.utc) + timedelta(seconds=max(8, cooldown_sec))
        logger.warning("document_db_unavailable cooldown_sec=%s reason=%s", cooldown_sec, reason)

    def _engine_or_none(self) -> AsyncEngine | None:
        if not self._db_enabled():
            return None
        if self._engine is None:
            self._engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
        return self._engine

    @staticmethod
    def _normalize_owner(owner: str | None) -> str:
        raw = (owner or "").strip()
        if not raw:
            return ""
        return raw

    @staticmethod
    def _owner_username(owner: str) -> str:
        if owner.startswith("u_"):
            return owner[2:]
        return owner

    async def _resolve_user_uuid(self, owner: str | None) -> str | None:
        normalized_owner = self._normalize_owner(owner)
        if not normalized_owner:
            return None
        engine = self._engine_or_none()
        if engine is None:
            return None
        username = self._owner_username(normalized_owner)
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
                row = (await conn.execute(query, {"owner": normalized_owner, "username": username})).mappings().first()
            return str(row["id"]) if row else None
        except Exception as exc:
            self._mark_db_unavailable(f"resolve_user:{exc}", cooldown_sec=40)
            return None

    @staticmethod
    def _row_to_draft(row: dict[str, Any]) -> DocumentDraft:
        created_username = str(row.get("created_by_username") or "").strip()
        reviewed_username = str(row.get("reviewed_by_username") or "").strip()
        created_by = f"u_{created_username}" if created_username else str(row.get("created_by") or "").strip() or None
        reviewed_by = f"u_{reviewed_username}" if reviewed_username else str(row.get("reviewed_by") or "").strip() or None
        raw_structured = row.get("structured_fields")
        if isinstance(raw_structured, dict):
            structured_fields = raw_structured
        elif isinstance(raw_structured, str):
            try:
                structured_fields = json.loads(raw_structured)
                if not isinstance(structured_fields, dict):
                    structured_fields = {}
            except Exception:
                structured_fields = {}
        else:
            structured_fields = {}
        return DocumentDraft(
            id=str(row.get("id")),
            patient_id=str(row.get("patient_id")),
            encounter_id=str(row.get("encounter_id") or "").strip() or None,
            document_type=str(row.get("document_type") or "nursing_note"),
            draft_text=str(row.get("draft_text") or ""),
            structured_fields=structured_fields,
            source_type=str(row.get("source_type") or "ai"),
            status=str(row.get("status") or "draft"),
            reviewed_by=reviewed_by,
            reviewed_at=row.get("reviewed_at"),
            created_by=created_by,
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    async def create(
        self,
        *,
        patient_id: str,
        encounter_id: str | None,
        document_type: str,
        draft_text: str,
        structured_fields: dict[str, Any],
        created_by: str | None,
    ) -> DocumentDraft | None:
        engine = self._engine_or_none()
        if engine is None:
            return None
        created_by_uuid = await self._resolve_user_uuid(created_by)
        query = text(
            """
            INSERT INTO document_drafts (
                patient_id,
                encounter_id,
                document_type,
                draft_text,
                structured_fields,
                source_type,
                status,
                created_by
            )
            VALUES (
                CAST(:patient_id AS uuid),
                CAST(NULLIF(:encounter_id, '') AS uuid),
                :document_type,
                :draft_text,
                CAST(:structured_fields AS jsonb),
                'ai',
                'draft',
                CAST(NULLIF(:created_by_uuid, '') AS uuid)
            )
            RETURNING
                id::text AS id,
                patient_id::text AS patient_id,
                encounter_id::text AS encounter_id,
                document_type,
                draft_text,
                structured_fields,
                source_type,
                status,
                reviewed_by::text AS reviewed_by,
                reviewed_at,
                created_by::text AS created_by,
                created_at,
                updated_at
            """
        )
        try:
            async with engine.begin() as conn:
                row = (
                    await conn.execute(
                        query,
                        {
                            "patient_id": patient_id,
                            "encounter_id": (encounter_id or "").strip(),
                            "document_type": document_type,
                            "draft_text": draft_text,
                            "structured_fields": json.dumps(structured_fields or {}, ensure_ascii=False),
                            "created_by_uuid": created_by_uuid or "",
                        },
                    )
                ).mappings().first()
            if not row:
                return None
            row_dict = dict(row)
            if created_by_uuid:
                row_dict["created_by"] = created_by_uuid
                row_dict["created_by_username"] = self._owner_username(created_by or "")
            return self._row_to_draft(row_dict)
        except Exception as exc:
            self._mark_db_unavailable(f"create_draft:{exc}")
            return None

    async def list_by_patient(self, patient_id: str, *, requested_by: str | None = None) -> list[DocumentDraft] | None:
        engine = self._engine_or_none()
        if engine is None:
            return None
        owner_uuid = await self._resolve_user_uuid(requested_by)
        query = text(
            """
            SELECT
                d.id::text AS id,
                d.patient_id::text AS patient_id,
                d.encounter_id::text AS encounter_id,
                d.document_type,
                d.draft_text,
                d.structured_fields,
                d.source_type,
                d.status,
                d.reviewed_by::text AS reviewed_by,
                d.reviewed_at,
                d.created_by::text AS created_by,
                d.created_at,
                d.updated_at,
                cu.username AS created_by_username,
                ru.username AS reviewed_by_username
            FROM document_drafts d
            LEFT JOIN users cu ON cu.id = d.created_by
            LEFT JOIN users ru ON ru.id = d.reviewed_by
            WHERE d.patient_id::text = :patient_id
              AND (:owner_uuid = '' OR d.created_by = CAST(:owner_uuid AS uuid))
            ORDER BY d.updated_at DESC
            LIMIT 200
            """
        )
        try:
            async with engine.connect() as conn:
                rows = (
                    await conn.execute(
                        query,
                        {
                            "patient_id": patient_id,
                            "owner_uuid": owner_uuid or "",
                        },
                    )
                ).mappings().all()
            return [self._row_to_draft(dict(row)) for row in rows]
        except Exception as exc:
            self._mark_db_unavailable(f"list_by_patient:{exc}")
            return None

    async def list_history(
        self,
        *,
        patient_id: str | None = None,
        requested_by: str | None = None,
        limit: int = 50,
    ) -> list[DocumentDraft] | None:
        engine = self._engine_or_none()
        if engine is None:
            return None
        owner_uuid = await self._resolve_user_uuid(requested_by)
        query = text(
            """
            SELECT
                d.id::text AS id,
                d.patient_id::text AS patient_id,
                d.encounter_id::text AS encounter_id,
                d.document_type,
                d.draft_text,
                d.structured_fields,
                d.source_type,
                d.status,
                d.reviewed_by::text AS reviewed_by,
                d.reviewed_at,
                d.created_by::text AS created_by,
                d.created_at,
                d.updated_at,
                cu.username AS created_by_username,
                ru.username AS reviewed_by_username
            FROM document_drafts d
            LEFT JOIN users cu ON cu.id = d.created_by
            LEFT JOIN users ru ON ru.id = d.reviewed_by
            WHERE (:patient_id = '' OR d.patient_id::text = :patient_id)
              AND (:owner_uuid = '' OR d.created_by = CAST(:owner_uuid AS uuid))
            ORDER BY d.updated_at DESC
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
                            "owner_uuid": owner_uuid or "",
                            "limit": max(int(limit), 1),
                        },
                    )
                ).mappings().all()
            return [self._row_to_draft(dict(row)) for row in rows]
        except Exception as exc:
            self._mark_db_unavailable(f"list_history:{exc}")
            return None

    async def review(self, draft_id: str, reviewed_by: str) -> DocumentDraft | None:
        engine = self._engine_or_none()
        if engine is None:
            return None
        reviewed_by_uuid = await self._resolve_user_uuid(reviewed_by)
        query = text(
            """
            UPDATE document_drafts d
            SET
                status = 'reviewed',
                reviewed_by = CAST(NULLIF(:reviewed_by_uuid, '') AS uuid),
                reviewed_at = NOW(),
                updated_at = NOW()
            WHERE d.id::text = :draft_id
            RETURNING
                d.id::text AS id,
                d.patient_id::text AS patient_id,
                d.encounter_id::text AS encounter_id,
                d.document_type,
                d.draft_text,
                d.structured_fields,
                d.source_type,
                d.status,
                d.reviewed_by::text AS reviewed_by,
                d.reviewed_at,
                d.created_by::text AS created_by,
                d.created_at,
                d.updated_at
            """
        )
        try:
            async with engine.begin() as conn:
                row = (
                    await conn.execute(
                        query,
                        {
                            "draft_id": draft_id,
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
            return self._row_to_draft(row_dict)
        except Exception as exc:
            self._mark_db_unavailable(f"review:{exc}")
            return None

    async def submit(self, draft_id: str) -> DocumentDraft | None:
        engine = self._engine_or_none()
        if engine is None:
            return None
        query = text(
            """
            UPDATE document_drafts d
            SET
                status = 'submitted',
                updated_at = NOW()
            WHERE d.id::text = :draft_id
            RETURNING
                d.id::text AS id,
                d.patient_id::text AS patient_id,
                d.encounter_id::text AS encounter_id,
                d.document_type,
                d.draft_text,
                d.structured_fields,
                d.source_type,
                d.status,
                d.reviewed_by::text AS reviewed_by,
                d.reviewed_at,
                d.created_by::text AS created_by,
                d.created_at,
                d.updated_at
            """
        )
        try:
            async with engine.begin() as conn:
                row = (await conn.execute(query, {"draft_id": draft_id})).mappings().first()
            if not row:
                return None
            return self._row_to_draft(dict(row))
        except Exception as exc:
            self._mark_db_unavailable(f"submit:{exc}")
            return None

    async def edit(self, draft_id: str, draft_text: str, edited_by: str | None = None) -> DocumentDraft | None:
        engine = self._engine_or_none()
        if engine is None:
            return None
        edited_by_uuid = await self._resolve_user_uuid(edited_by)
        query = text(
            """
            UPDATE document_drafts d
            SET
                draft_text = :draft_text,
                status = 'draft',
                structured_fields = COALESCE(d.structured_fields, '{}'::jsonb) || CAST(:structured_patch AS jsonb),
                created_by = COALESCE(CAST(NULLIF(:edited_by_uuid, '') AS uuid), d.created_by),
                updated_at = NOW()
            WHERE d.id::text = :draft_id
            RETURNING
                d.id::text AS id,
                d.patient_id::text AS patient_id,
                d.encounter_id::text AS encounter_id,
                d.document_type,
                d.draft_text,
                d.structured_fields,
                d.source_type,
                d.status,
                d.reviewed_by::text AS reviewed_by,
                d.reviewed_at,
                d.created_by::text AS created_by,
                d.created_at,
                d.updated_at
            """
        )
        structured_patch = {
            "manual_edited": True,
            "edited_by": edited_by,
            "edited_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            async with engine.begin() as conn:
                row = (
                    await conn.execute(
                        query,
                        {
                            "draft_id": draft_id,
                            "draft_text": draft_text,
                            "structured_patch": json.dumps(structured_patch, ensure_ascii=False),
                            "edited_by_uuid": edited_by_uuid or "",
                        },
                    )
                ).mappings().first()
            if not row:
                return None
            row_dict = dict(row)
            if edited_by_uuid and edited_by:
                row_dict["created_by"] = edited_by_uuid
                row_dict["created_by_username"] = self._owner_username(edited_by)
            return self._row_to_draft(row_dict)
        except Exception as exc:
            self._mark_db_unavailable(f"edit:{exc}")
            return None


document_db_store = DocumentDraftDbStore()
