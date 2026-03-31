from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import settings
from app.schemas.patient import (
    BedOverview,
    OrderRequestCreateRequest,
    OrderListOut,
    OrderOut,
    PatientBase,
    PatientContextOut,
)
from app.services.mock_data import (
    MOCK_BEDS,
    MOCK_DEPARTMENT_ID,
    MOCK_PATIENTS,
    get_active_orders_for_patient,
    get_dynamic_beds,
    get_dynamic_context,
    get_order_history_for_patient,
    get_order_stats,
    mark_order_checked,
    mark_order_exception,
    mark_order_executed,
    create_order_request,
)

logger = logging.getLogger(__name__)


class PatientContextRepository:
    def __init__(self) -> None:
        self._engine: AsyncEngine | None = None
        self._db_disabled_until: datetime | None = None

    def _db_enabled(self) -> bool:
        if settings.mock_mode:
            return False
        if self._db_disabled_until and datetime.now(timezone.utc) < self._db_disabled_until:
            return False
        return True

    def _mark_db_unavailable(self, reason: str, cooldown_sec: int = 60) -> None:
        self._db_disabled_until = datetime.now(timezone.utc) + timedelta(seconds=max(5, cooldown_sec))
        logger.warning(
            "db_unavailable_fallback cooldown_sec=%s reason=%s",
            cooldown_sec,
            reason,
        )

    @staticmethod
    def _mock_fallback_enabled() -> bool:
        return bool(settings.mock_mode or settings.db_error_fallback_to_mock)

    @staticmethod
    def _mock_beds_by_department(department_id: str) -> list[BedOverview]:
        if department_id == MOCK_DEPARTMENT_ID:
            source_beds = get_dynamic_beds(department_id)
        else:
            source_beds = [item for item in MOCK_BEDS if item.department_id == department_id]
        return [bed.model_copy(deep=True) for bed in source_beds]

    @staticmethod
    def _mock_all_beds() -> list[BedOverview]:
        return [bed.model_copy(deep=True) for bed in MOCK_BEDS]

    @staticmethod
    def _bed_sort_key(bed_no: str | None) -> tuple[int, str]:
        raw = str(bed_no or "").strip()
        if raw.isdigit():
            return (0, f"{int(raw):03d}")
        return (1, raw)

    @staticmethod
    def _virtual_range() -> tuple[int, int]:
        start = int(settings.virtual_bed_no_start or 1)
        end = int(settings.virtual_bed_no_end or 40)
        if start > end:
            start, end = end, start
        start = max(1, start)
        end = max(start, end)
        return start, end

    @classmethod
    def _virtual_range_contains(cls, bed_no: str) -> bool:
        if not settings.include_virtual_empty_beds:
            return False
        raw = str(bed_no or "").strip()
        if not raw.isdigit():
            return False
        value = int(raw)
        start, end = cls._virtual_range()
        return start <= value <= end

    @classmethod
    def _augment_with_virtual_beds(
        cls,
        beds: list[BedOverview],
        *,
        department_id: str,
    ) -> list[BedOverview]:
        if not settings.include_virtual_empty_beds:
            return beds
        start, end = cls._virtual_range()
        existing = {str(item.bed_no).strip() for item in beds if str(item.bed_no).strip()}
        for num in range(start, end + 1):
            bed_no = str(num)
            if bed_no in existing:
                continue
            beds.append(
                BedOverview(
                    id=f"virtual-{department_id}-{bed_no}",
                    department_id=department_id,
                    bed_no=bed_no,
                    room_no=f"{600 + num}",
                    status="vacant",
                    current_patient_id=None,
                    patient_name=None,
                    pending_tasks=[],
                    risk_tags=[],
                )
            )
        beds.sort(key=lambda item: cls._bed_sort_key(item.bed_no))
        return beds

    @staticmethod
    def _build_empty_bed_context(bed_no: str) -> PatientContextOut:
        value = str(bed_no or "").strip() or "未知"
        return PatientContextOut(
            patient_id=f"bed-vacant-{value}",
            patient_name=None,
            bed_no=value,
            encounter_id=None,
            diagnoses=[],
            risk_tags=[],
            pending_tasks=["当前床位暂无在床患者，请核对床号或直接查询病区重点患者。"],
            latest_observations=[],
            updated_at=datetime.now(timezone.utc),
        )

    def _engine_or_none(self) -> AsyncEngine | None:
        if not self._db_enabled():
            return None
        if self._engine is None:
            self._engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
        return self._engine

    @staticmethod
    def _mock_patient_context_or_none(patient_id: str) -> PatientContextOut | None:
        context = get_dynamic_context(patient_id)
        if context is None:
            return None
        return context.model_copy(deep=True)

    @staticmethod
    def _doc_status_label(status: str) -> str:
        mapping = {
            "draft": "草稿",
            "reviewed": "已审核",
            "submitted": "已提交",
            "saved": "已保存",
        }
        return mapping.get(status, status or "未知")

    @staticmethod
    def _format_doc_sync(status: str, updated_at: str | None) -> str:
        label = PatientContextRepository._doc_status_label(status)
        if not updated_at:
            return f"文书状态：{label}"
        short_time = updated_at.replace("T", " ").replace("Z", "")
        if len(short_time) >= 19:
            short_time = short_time[5:19]
        return f"文书状态：{label}（{short_time}）"
    async def _latest_document_hint(self, patient_id: str | None, requested_by: str | None = None) -> dict[str, Any] | None:
        if not patient_id:
            return None
        try:
            params: dict[str, Any] = {}
            owner = (requested_by or "").strip()
            if owner:
                params["requested_by"] = owner
            async with httpx.AsyncClient(timeout=4, trust_env=False) as client:
                response = await client.get(f"{settings.document_service_url}/document/drafts/{patient_id}", params=params or None)
            if response.status_code >= 400:
                return None
            drafts = response.json()
            if not isinstance(drafts, list) or not drafts:
                return None
            latest = drafts[0]
            status = str(latest.get("status", "draft"))
            updated_at = latest.get("updated_at")
            document_type = latest.get("document_type")
            draft_text = str(latest.get("draft_text", "")).replace("\n", " ").strip()
            excerpt = draft_text[:70] + ("..." if len(draft_text) > 70 else "")
            sync_text = self._format_doc_sync(status, updated_at)
            return {
                "sync_text": sync_text,
                "status": status,
                "updated_at": updated_at,
                "document_type": document_type,
                "excerpt": excerpt,
            }
        except Exception:
            return None

    def _merge_document_hint_to_context(
        self,
        context: PatientContextOut,
        document_hint: dict[str, Any] | None,
    ) -> PatientContextOut:
        if not document_hint:
            return context
        sync_text = document_hint.get("sync_text")
        if sync_text and sync_text not in context.pending_tasks:
            context.pending_tasks = [sync_text, *context.pending_tasks]
        context.latest_document_sync = sync_text
        context.latest_document_status = document_hint.get("status")
        context.latest_document_type = document_hint.get("document_type")
        context.latest_document_excerpt = document_hint.get("excerpt")
        raw_updated_at = document_hint.get("updated_at")
        if isinstance(raw_updated_at, str):
            try:
                context.latest_document_updated_at = datetime.fromisoformat(raw_updated_at.replace("Z", "+00:00"))
            except Exception:
                context.latest_document_updated_at = None
        return context

    async def get_ward_beds(self, department_id: str) -> list[BedOverview]:
        if not self._db_enabled():
            if self._mock_fallback_enabled():
                beds = self._mock_beds_by_department(department_id)
                return self._augment_with_virtual_beds(beds, department_id=department_id)
            return []

        engine = self._engine_or_none()
        if engine is None:
            if self._mock_fallback_enabled():
                beds = self._mock_beds_by_department(department_id)
                return self._augment_with_virtual_beds(beds, department_id=department_id)
            return []

        query = text(
            """
            SELECT
                b.id::text AS id,
                b.department_id::text AS department_id,
                b.bed_no,
                b.room_no,
                b.status,
                b.current_patient_id::text AS current_patient_id,
                p.full_name AS patient_name
            FROM beds b
            JOIN departments d ON d.id = b.department_id
            LEFT JOIN patients p ON p.id = b.current_patient_id
            WHERE b.department_id::text = :department_id
               OR d.code = :department_id
            ORDER BY b.bed_no
            """
        )

        try:
            async with engine.connect() as conn:
                rows = (await conn.execute(query, {"department_id": department_id})).mappings().all()
        except Exception as exc:
            self._mark_db_unavailable(f"get_ward_beds:{exc}")
            if self._mock_fallback_enabled():
                beds = self._mock_beds_by_department(department_id)
                return self._augment_with_virtual_beds(beds, department_id=department_id)
            return []

        beds: list[BedOverview] = []
        for row in rows:
            current_patient_id = row["current_patient_id"]
            pending_tasks = await self._pending_tasks_for_patient(current_patient_id)
            risk_tags = await self._risk_tags_for_patient(current_patient_id)
            beds.append(
                BedOverview(
                    id=row["id"],
                    department_id=row["department_id"],
                    bed_no=row["bed_no"],
                    room_no=row["room_no"],
                    status=row["status"],
                    current_patient_id=current_patient_id,
                    patient_name=row["patient_name"],
                    pending_tasks=pending_tasks,
                    risk_tags=risk_tags,
                )
            )
        return self._augment_with_virtual_beds(beds, department_id=department_id)

    async def get_all_beds(self) -> list[BedOverview]:
        if not self._db_enabled():
            if self._mock_fallback_enabled():
                beds = self._mock_all_beds()
                return self._augment_with_virtual_beds(beds, department_id=MOCK_DEPARTMENT_ID)
            return []

        engine = self._engine_or_none()
        if engine is None:
            if self._mock_fallback_enabled():
                beds = self._mock_all_beds()
                return self._augment_with_virtual_beds(beds, department_id=MOCK_DEPARTMENT_ID)
            return []

        query = text(
            """
            SELECT
                b.id::text AS id,
                b.department_id::text AS department_id,
                b.bed_no,
                b.room_no,
                b.status,
                b.current_patient_id::text AS current_patient_id,
                p.full_name AS patient_name
            FROM beds b
            LEFT JOIN patients p ON p.id = b.current_patient_id
            ORDER BY b.bed_no
            """
        )

        try:
            async with engine.connect() as conn:
                rows = (await conn.execute(query)).mappings().all()
        except Exception as exc:
            self._mark_db_unavailable(f"get_all_beds:{exc}")
            if self._mock_fallback_enabled():
                beds = self._mock_all_beds()
                return self._augment_with_virtual_beds(beds, department_id=MOCK_DEPARTMENT_ID)
            return []

        beds: list[BedOverview] = []
        for row in rows:
            current_patient_id = row["current_patient_id"]
            pending_tasks = await self._pending_tasks_for_patient(current_patient_id)
            risk_tags = await self._risk_tags_for_patient(current_patient_id)
            beds.append(
                BedOverview(
                    id=row["id"],
                    department_id=row["department_id"],
                    bed_no=row["bed_no"],
                    room_no=row["room_no"],
                    status=row["status"],
                    current_patient_id=current_patient_id,
                    patient_name=row["patient_name"],
                    pending_tasks=pending_tasks,
                    risk_tags=risk_tags,
                )
            )
        return self._augment_with_virtual_beds(beds, department_id=MOCK_DEPARTMENT_ID)

    async def get_patient(self, patient_id: str) -> PatientBase | None:
        if not self._db_enabled():
            if self._mock_fallback_enabled():
                return MOCK_PATIENTS.get(patient_id)
            return None

        engine = self._engine_or_none()
        if engine is None:
            return None

        query = text(
            """
            SELECT
                id::text AS id,
                mrn,
                inpatient_no,
                full_name,
                gender,
                age,
                blood_type,
                allergy_info,
                current_status
            FROM patients
            WHERE id::text = :patient_id
            """
        )
        try:
            async with engine.connect() as conn:
                row = (await conn.execute(query, {"patient_id": patient_id})).mappings().first()
        except Exception as exc:
            self._mark_db_unavailable(f"get_patient:{exc}")
            if self._mock_fallback_enabled():
                return MOCK_PATIENTS.get(patient_id)
            return None
        return PatientBase(**row) if row else None

    async def get_patient_context(self, patient_id: str, requested_by: str | None = None) -> PatientContextOut | None:
        if not self._db_enabled():
            if not self._mock_fallback_enabled():
                return None
            ctx = self._mock_patient_context_or_none(patient_id)
            if ctx is None:
                return None
            document_hint = await self._latest_document_hint(patient_id, requested_by=requested_by)
            return self._merge_document_hint_to_context(ctx, document_hint)

        engine = self._engine_or_none()
        if engine is None:
            return None

        encounter_query = text(
            """
            SELECT id::text AS encounter_id
            FROM encounters
            WHERE patient_id::text = :patient_id AND status = 'active'
            ORDER BY admission_at DESC NULLS LAST
            LIMIT 1
            """
        )
        patient_query = text(
            """
            SELECT full_name
            FROM patients
            WHERE id::text = :patient_id
            LIMIT 1
            """
        )
        bed_query = text(
            """
            SELECT bed_no
            FROM beds
            WHERE current_patient_id::text = :patient_id
            LIMIT 1
            """
        )
        diagnosis_query = text(
            """
            SELECT d.diagnosis_name
            FROM patient_diagnoses d
            JOIN encounters e ON e.id = d.encounter_id
            WHERE e.patient_id::text = :patient_id AND d.status = 'active'
            ORDER BY d.created_at DESC
            LIMIT 8
            """
        )
        obs_query = text(
            """
            SELECT name, value_num, value_text, unit, abnormal_flag, observed_at
            FROM observations
            WHERE patient_id::text = :patient_id
            ORDER BY observed_at DESC
            LIMIT 8
            """
        )

        try:
            async with engine.connect() as conn:
                encounter_row = (await conn.execute(encounter_query, {"patient_id": patient_id})).mappings().first()
                patient_row = (await conn.execute(patient_query, {"patient_id": patient_id})).mappings().first()
                bed_row = (await conn.execute(bed_query, {"patient_id": patient_id})).mappings().first()
                diagnosis_rows = (await conn.execute(diagnosis_query, {"patient_id": patient_id})).mappings().all()
                obs_rows = (await conn.execute(obs_query, {"patient_id": patient_id})).mappings().all()
        except Exception as exc:
            self._mark_db_unavailable(f"get_patient_context:{exc}")
            if not self._mock_fallback_enabled():
                return None
            fallback_ctx = self._mock_patient_context_or_none(patient_id)
            if fallback_ctx is None:
                return None
            document_hint = await self._latest_document_hint(patient_id, requested_by=requested_by)
            return self._merge_document_hint_to_context(fallback_ctx, document_hint)

        pending_tasks = await self._pending_tasks_for_patient(patient_id)
        risk_tags = await self._risk_tags_for_patient(patient_id)

        observations: list[dict[str, Any]] = []
        for row in obs_rows:
            if row["value_text"]:
                value = row["value_text"]
            elif row["value_num"] is not None:
                value = f"{row['value_num']} {row['unit'] or ''}".strip()
            else:
                value = None
            observations.append(
                {
                    "name": row["name"],
                    "value": value,
                    "abnormal_flag": row["abnormal_flag"],
                    "observed_at": row["observed_at"],
                }
            )

        context = PatientContextOut(
            patient_id=patient_id,
            patient_name=patient_row["full_name"] if patient_row else None,
            bed_no=bed_row["bed_no"] if bed_row else None,
            encounter_id=encounter_row["encounter_id"] if encounter_row else None,
            diagnoses=[item["diagnosis_name"] for item in diagnosis_rows],
            risk_tags=risk_tags,
            pending_tasks=pending_tasks,
            latest_observations=observations,
            updated_at=datetime.now(timezone.utc),
        )
        document_hint = await self._latest_document_hint(patient_id, requested_by=requested_by)
        return self._merge_document_hint_to_context(context, document_hint)

    async def find_context_by_bed(
        self,
        bed_no: str,
        department_id: str | None = None,
        requested_by: str | None = None,
    ) -> PatientContextOut | None:
        if not self._db_enabled():
            if not self._mock_fallback_enabled():
                return None
            mock_source = self._mock_beds_by_department(department_id or MOCK_DEPARTMENT_ID) if department_id else [item.model_copy(deep=True) for item in MOCK_BEDS]
            for bed in mock_source:
                if bed.bed_no != bed_no:
                    continue
                if bed.current_patient_id:
                    return await self.get_patient_context(bed.current_patient_id, requested_by=requested_by)
            return None

        engine = self._engine_or_none()
        if engine is None:
            return None

        if department_id:
            query = text(
                """
                SELECT bed_no, status, current_patient_id::text AS patient_id
                FROM beds
                JOIN departments d ON d.id = beds.department_id
                WHERE bed_no = :bed_no
                  AND (
                      department_id::text = :department_id
                      OR d.code = :department_id
                  )
                LIMIT 1
                """
            )
            params = {"bed_no": bed_no, "department_id": department_id}
        else:
            query = text(
                """
                SELECT bed_no, status, current_patient_id::text AS patient_id
                FROM beds
                WHERE bed_no = :bed_no
                LIMIT 1
                """
            )
            params = {"bed_no": bed_no}

        try:
            async with engine.connect() as conn:
                row = (await conn.execute(query, params)).mappings().first()
        except Exception as exc:
            self._mark_db_unavailable(f"find_context_by_bed:{exc}")
            if not self._mock_fallback_enabled():
                return None
            mock_source = self._mock_beds_by_department(department_id or MOCK_DEPARTMENT_ID) if department_id else [item.model_copy(deep=True) for item in MOCK_BEDS]
            for bed in mock_source:
                if bed.bed_no == bed_no and bed.current_patient_id:
                    return await self.get_patient_context(bed.current_patient_id, requested_by=requested_by)
            return None
        if not row:
            if self._virtual_range_contains(bed_no):
                return self._build_empty_bed_context(bed_no)
            return None
        patient_id = str(row.get("patient_id") or "").strip()
        if not patient_id:
            return self._build_empty_bed_context(str(row.get("bed_no") or bed_no))
        return await self.get_patient_context(row["patient_id"], requested_by=requested_by)

    async def get_patient_orders(self, patient_id: str) -> OrderListOut:
        # 当前迭代先走 mock 闭环，确保手机端可完整演示医嘱核对-执行-留痕流程。
        orders = get_active_orders_for_patient(patient_id)
        stats = get_order_stats(patient_id)
        return OrderListOut(
            patient_id=patient_id,
            stats=stats,
            orders=orders,
        )

    async def get_patient_order_history(self, patient_id: str, limit: int = 50) -> list[OrderOut]:
        history = get_order_history_for_patient(patient_id)
        return history[:limit]

    async def double_check_order(self, order_id: str, checked_by: str, note: str | None = None) -> OrderOut | None:
        return mark_order_checked(order_id=order_id, checked_by=checked_by, note=note)

    async def execute_order(self, order_id: str, executed_by: str, note: str | None = None) -> OrderOut | None:
        return mark_order_executed(order_id=order_id, executed_by=executed_by, note=note)

    async def report_order_exception(self, order_id: str, reported_by: str, reason: str) -> OrderOut | None:
        return mark_order_exception(order_id=order_id, reported_by=reported_by, reason=reason)

    async def create_order_request(
        self,
        *,
        patient_id: str,
        requested_by: str,
        title: str,
        details: str,
        priority: str = "P2",
    ) -> OrderOut:
        return create_order_request(
            patient_id=patient_id,
            requested_by=requested_by,
            title=title,
            details=details,
            priority=priority,
        )

    async def _pending_tasks_for_patient(self, patient_id: str | None) -> list[str]:
        if not patient_id:
            return []
        if not self._db_enabled():
            if not self._mock_fallback_enabled():
                return []
            context = self._mock_patient_context_or_none(patient_id)
            base_tasks = context.pending_tasks if context else []
            stats = get_order_stats(patient_id)
            order_hint: list[str] = []
            if stats.get("pending", 0) > 0:
                order_hint.append(f"医嘱待执行 {stats['pending']} 项")
            if stats.get("due_30m", 0) > 0:
                order_hint.append(f"30分钟内到时医嘱 {stats['due_30m']} 项")
            if stats.get("overdue", 0) > 0:
                order_hint.append(f"超时医嘱 {stats['overdue']} 项")
            return [*order_hint, *base_tasks]

        engine = self._engine_or_none()
        if engine is None:
            return []

        query = text(
            """
            SELECT title
            FROM care_tasks
            WHERE patient_id::text = :patient_id
              AND status IN ('pending', 'in_progress')
            ORDER BY priority ASC, created_at DESC
            LIMIT 8
            """
        )
        try:
            async with engine.connect() as conn:
                rows = (await conn.execute(query, {"patient_id": patient_id})).mappings().all()
        except Exception as exc:
            self._mark_db_unavailable(f"_pending_tasks_for_patient:{exc}")
            if not self._mock_fallback_enabled():
                return []
            context = self._mock_patient_context_or_none(patient_id)
            base_tasks = context.pending_tasks if context else []
            stats = get_order_stats(patient_id)
            order_hint: list[str] = []
            if stats.get("pending", 0) > 0:
                order_hint.append(f"医嘱待执行 {stats['pending']} 项")
            if stats.get("due_30m", 0) > 0:
                order_hint.append(f"30分钟内到时医嘱 {stats['due_30m']} 项")
            if stats.get("overdue", 0) > 0:
                order_hint.append(f"超时医嘱 {stats['overdue']} 项")
            return [*order_hint, *base_tasks]
        return [row["title"] for row in rows]

    async def _risk_tags_for_patient(self, patient_id: str | None) -> list[str]:
        if not patient_id:
            return []
        if not self._db_enabled():
            if not self._mock_fallback_enabled():
                return []
            context = self._mock_patient_context_or_none(patient_id)
            return context.risk_tags if context else []

        engine = self._engine_or_none()
        if engine is None:
            return []

        query = text(
            """
            SELECT DISTINCT name, abnormal_flag
            FROM observations
            WHERE patient_id::text = :patient_id
              AND abnormal_flag IN ('high', 'low', 'critical')
              AND observed_at >= NOW() - INTERVAL '24 hours'
            ORDER BY name
            LIMIT 8
            """
        )
        try:
            async with engine.connect() as conn:
                rows = (await conn.execute(query, {"patient_id": patient_id})).mappings().all()
        except Exception as exc:
            self._mark_db_unavailable(f"_risk_tags_for_patient:{exc}")
            if not self._mock_fallback_enabled():
                return []
            context = self._mock_patient_context_or_none(patient_id)
            return context.risk_tags if context else []
        return [f"{row['name']}({row['abnormal_flag']})" for row in rows]


repository = PatientContextRepository()

