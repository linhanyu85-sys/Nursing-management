from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import settings
from app.schemas.recommendation import RecommendationItem, RecommendationOutput

logger = logging.getLogger(__name__)


class RecommendationDbStore:
    def __init__(self) -> None:
        self._engine: AsyncEngine | None = None
        self._db_disabled_until: datetime | None = None

    def _db_enabled(self) -> bool:
        if settings.mock_mode:
            return False
        if not settings.recommendation_use_postgres:
            return False
        if self._db_disabled_until and datetime.now(timezone.utc) < self._db_disabled_until:
            return False
        return True

    def _mark_db_unavailable(self, reason: str, cooldown_sec: int = 60) -> None:
        self._db_disabled_until = datetime.now(timezone.utc) + timedelta(seconds=max(8, cooldown_sec))
        logger.warning("recommendation_db_unavailable cooldown_sec=%s reason=%s", cooldown_sec, reason)

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
        if raw.startswith("u_"):
            return raw
        return f"u_{raw}"

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
    def _normalize_str_list(raw: Any) -> list[str]:
        if isinstance(raw, list):
            return [str(item).strip() for item in raw if str(item).strip()]
        if isinstance(raw, str):
            raw = raw.strip()
            if not raw:
                return []
            try:
                payload = json.loads(raw)
                if isinstance(payload, list):
                    return [str(item).strip() for item in payload if str(item).strip()]
            except Exception:
                return [raw]
        return []

    @staticmethod
    def _normalize_recommendation_items(raw: Any) -> list[RecommendationItem]:
        data: list[Any]
        if isinstance(raw, list):
            data = raw
        elif isinstance(raw, str):
            try:
                loaded = json.loads(raw)
                data = loaded if isinstance(loaded, list) else []
            except Exception:
                data = [raw]
        else:
            data = []

        items: list[RecommendationItem] = []
        for entry in data:
            if isinstance(entry, RecommendationItem):
                items.append(entry)
                continue
            if isinstance(entry, dict):
                title = str(entry.get("title") or "").strip()
                if not title:
                    continue
                items.append(
                    RecommendationItem(
                        title=title,
                        priority=max(1, int(entry.get("priority", 2) or 2)),
                        rationale=(str(entry.get("rationale") or "").strip() or None),
                    )
                )
                continue
            text_value = str(entry).strip()
            if text_value:
                items.append(RecommendationItem(title=text_value, priority=2))
        return items

    @staticmethod
    def _parse_input_summary(raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            text_value = raw.strip()
            if not text_value:
                return {}
            try:
                payload = json.loads(text_value)
                if isinstance(payload, dict):
                    return payload
            except Exception:
                return {"raw_input_summary": text_value}
        return {}

    @staticmethod
    def _owner_pattern(owner: str | None) -> str:
        normalized = RecommendationDbStore._normalize_owner(owner)
        if not normalized:
            return ""
        return f"%\"requested_by\":\"{normalized}\"%"

    @classmethod
    def _row_to_output(cls, row: dict[str, Any]) -> RecommendationOutput:
        input_meta = cls._parse_input_summary(row.get("input_summary"))
        requested_by = str(input_meta.get("requested_by") or "").strip() or None
        metadata: dict[str, Any] = {
            "source": "postgres",
            "input_summary": input_meta,
        }
        if requested_by:
            metadata["requested_by"] = requested_by
        if input_meta.get("question"):
            metadata["question"] = input_meta["question"]
        if input_meta.get("effective_question"):
            metadata["effective_question"] = input_meta["effective_question"]
        if input_meta.get("resolved_bed_no"):
            metadata["resolved_bed_no"] = input_meta["resolved_bed_no"]
        if input_meta.get("resolved_patient_id"):
            metadata["resolved_patient_id"] = input_meta["resolved_patient_id"]

        return RecommendationOutput(
            id=str(row.get("id")),
            patient_id=str(row.get("patient_id")),
            summary=str(row.get("summary") or ""),
            findings=cls._normalize_str_list(row.get("findings")),
            recommendations=cls._normalize_recommendation_items(row.get("recommendations")),
            confidence=float(row.get("confidence") or 0.0),
            review_required=bool(row.get("review_required", True)),
            escalation_rules=cls._normalize_str_list(row.get("escalation_rules")),
            status=str(row.get("status") or "draft"),
            created_at=row.get("created_at"),
            metadata=metadata,
        )

    async def create(
        self,
        *,
        patient_id: str,
        encounter_id: str | None,
        summary: str,
        findings: list[str],
        recommendations: list[RecommendationItem] | list[dict[str, Any]] | list[str],
        confidence: float,
        review_required: bool,
        escalation_rules: list[str],
        metadata: dict[str, Any],
    ) -> RecommendationOutput | None:
        engine = self._engine_or_none()
        if engine is None:
            return None

        requested_by = self._normalize_owner(str((metadata or {}).get("requested_by") or ""))
        input_summary = json.dumps(
            {
                "question": str((metadata or {}).get("question") or ""),
                "effective_question": str((metadata or {}).get("effective_question") or ""),
                "requested_by": requested_by,
                "resolved_patient_id": str((metadata or {}).get("resolved_patient_id") or patient_id),
                "resolved_bed_no": str((metadata or {}).get("resolved_bed_no") or ""),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        rec_dicts = [item.model_dump() if isinstance(item, RecommendationItem) else item for item in recommendations]

        query = text(
            """
            INSERT INTO ai_recommendations (
                patient_id,
                encounter_id,
                scenario,
                input_summary,
                summary,
                findings,
                recommendations,
                escalation_rules,
                confidence,
                review_required,
                status
            )
            VALUES (
                CAST(:patient_id AS uuid),
                CAST(NULLIF(:encounter_id, '') AS uuid),
                'recommendation',
                :input_summary,
                :summary,
                CAST(:findings AS jsonb),
                CAST(:recommendations AS jsonb),
                CAST(:escalation_rules AS jsonb),
                :confidence,
                :review_required,
                'draft'
            )
            RETURNING
                id::text AS id,
                patient_id::text AS patient_id,
                encounter_id::text AS encounter_id,
                scenario,
                input_summary,
                summary,
                findings,
                recommendations,
                escalation_rules,
                confidence,
                review_required,
                status,
                created_at
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
                            "input_summary": input_summary,
                            "summary": summary,
                            "findings": json.dumps(findings or [], ensure_ascii=False),
                            "recommendations": json.dumps(rec_dicts or [], ensure_ascii=False),
                            "escalation_rules": json.dumps(escalation_rules or [], ensure_ascii=False),
                            "confidence": max(0.0, min(float(confidence or 0.0), 1.0)),
                            "review_required": bool(review_required),
                        },
                    )
                ).mappings().first()
            if not row:
                return None
            return self._row_to_output(dict(row))
        except Exception as exc:
            self._mark_db_unavailable(f"create:{exc}")
            return None

    async def _query_items(
        self,
        *,
        patient_id: str | None = None,
        requested_by: str | None = None,
        limit: int = 50,
    ) -> list[RecommendationOutput] | None:
        engine = self._engine_or_none()
        if engine is None:
            return None
        query = text(
            """
            SELECT
                r.id::text AS id,
                r.patient_id::text AS patient_id,
                r.encounter_id::text AS encounter_id,
                r.scenario,
                r.input_summary,
                r.summary,
                r.findings,
                r.recommendations,
                r.escalation_rules,
                r.confidence,
                r.review_required,
                r.status,
                r.created_at
            FROM ai_recommendations r
            WHERE (:patient_id = '' OR r.patient_id::text = :patient_id)
              AND (:owner_pattern = '' OR COALESCE(r.input_summary, '') LIKE :owner_pattern)
            ORDER BY r.created_at DESC
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
                            "owner_pattern": self._owner_pattern(requested_by),
                            "limit": max(1, int(limit)),
                        },
                    )
                ).mappings().all()
            return [self._row_to_output(dict(row)) for row in rows]
        except Exception as exc:
            self._mark_db_unavailable(f"list:{exc}")
            return None

    async def latest_by_patient_for_user(
        self,
        patient_id: str,
        *,
        requested_by: str | None = None,
    ) -> RecommendationOutput | None:
        rows = await self._query_items(patient_id=patient_id, requested_by=requested_by, limit=1)
        if not rows:
            return None
        return rows[0]

    async def list_by_patient_for_user(
        self,
        patient_id: str,
        *,
        requested_by: str | None = None,
        limit: int = 50,
    ) -> list[RecommendationOutput] | None:
        return await self._query_items(patient_id=patient_id, requested_by=requested_by, limit=limit)

    async def list_by_user(
        self,
        requested_by: str,
        *,
        patient_id: str | None = None,
        limit: int = 50,
    ) -> list[RecommendationOutput] | None:
        return await self._query_items(patient_id=patient_id, requested_by=requested_by, limit=limit)

    async def get_last_question(self, patient_id: str, *, requested_by: str | None = None) -> str | None:
        item = await self.latest_by_patient_for_user(patient_id, requested_by=requested_by)
        if item is None:
            return None
        metadata = item.metadata or {}
        input_summary = metadata.get("input_summary")
        if isinstance(input_summary, dict):
            for key in ("question", "effective_question"):
                value = str(input_summary.get(key) or "").strip()
                if value:
                    return value
        for key in ("question", "effective_question"):
            value = str(metadata.get(key) or "").strip()
            if value:
                return value
        return None


recommendation_db_store = RecommendationDbStore()

