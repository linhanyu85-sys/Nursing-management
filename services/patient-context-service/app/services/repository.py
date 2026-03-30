from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import settings
from app.schemas.patient import (
    AdminPatientCaseRowOut,
    AnalyticsKpiOut,
    BedOverview,
    DepartmentOptionOut,
    DistributionItemOut,
    OrderRequestCreateRequest,
    OrderListOut,
    OrderOut,
    PatientBase,
    PatientCaseBundleOut,
    PatientCaseUpsertRequest,
    PatientContextOut,
    WardAnalyticsOut,
    WardHotspotOut,
)
from app.services.mock_data import (
    MOCK_BEDS,
    MOCK_DEPARTMENT_ID,
    MOCK_PATIENTS,
    get_patient_case_bundle,
    get_active_orders_for_patient,
    get_dynamic_beds,
    get_dynamic_context,
    get_order_history_for_patient,
    get_order_stats,
    mark_order_checked,
    mark_order_exception,
    mark_order_executed,
    create_order_request,
    upsert_patient_case,
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
    def _normalize_uuid(value: str | None) -> str | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            return str(UUID(raw))
        except Exception:
            return None

    @staticmethod
    def _auto_mrn(full_name: str) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        safe_name = "".join(ch for ch in full_name if ch.isalnum())[:6] or "CASE"
        return f"{safe_name}-{ts}"

    async def _ensure_default_department(self, conn: Any) -> str:
        row = (
            await conn.execute(
                text(
                    """
                    SELECT id::text AS id
                    FROM departments
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                )
            )
        ).mappings().first()
        if row:
            return row["id"]
        created = (
            await conn.execute(
                text(
                    """
                    INSERT INTO departments (code, name, ward_type, location)
                    VALUES ('ai-demo-ward', 'AI护理演示病区', 'inpatient', '云端演示病区')
                    ON CONFLICT (code)
                    DO UPDATE SET name = EXCLUDED.name
                    RETURNING id::text AS id
                    """
                )
            )
        ).mappings().first()
        return created["id"]

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

    @staticmethod
    def _default_departments() -> list[DepartmentOptionOut]:
        return [
            DepartmentOptionOut(
                id=MOCK_DEPARTMENT_ID,
                code="CARD-01",
                name="心内一病区",
                ward_type="inpatient",
                location="A栋6层",
            )
        ]

    @staticmethod
    def _format_latest_observation(
        *,
        name: str | None,
        value_text: str | None,
        value_num: Any,
        unit: str | None,
        abnormal_flag: str | None,
        observed_at: datetime | str | None,
    ) -> str | None:
        label = (name or "").strip()
        if not label:
            return None
        if value_text:
            value = str(value_text).strip()
        elif value_num is not None:
            value = f"{value_num} {unit or ''}".strip()
        else:
            value = ""
        observed = ""
        if isinstance(observed_at, datetime):
            observed = observed_at.astimezone(timezone.utc).strftime("%m-%d %H:%M")
        elif isinstance(observed_at, str) and observed_at.strip():
            observed = observed_at.replace("T", " ").replace("Z", "")[5:16]
        parts = [label]
        if value:
            parts.append(value)
        if abnormal_flag:
            parts.append(str(abnormal_flag))
        if observed:
            parts.append(observed)
        return " / ".join(parts)

    async def list_departments(self) -> list[DepartmentOptionOut]:
        if not self._db_enabled():
            return self._default_departments() if self._mock_fallback_enabled() else []

        engine = self._engine_or_none()
        if engine is None:
            return self._default_departments() if self._mock_fallback_enabled() else []

        query = text(
            """
            SELECT
                id::text AS id,
                code,
                name,
                ward_type,
                location
            FROM departments
            ORDER BY name ASC
            """
        )
        try:
            async with engine.connect() as conn:
                rows = (await conn.execute(query)).mappings().all()
        except Exception as exc:
            self._mark_db_unavailable(f"list_departments:{exc}")
            return self._default_departments() if self._mock_fallback_enabled() else []
        return [DepartmentOptionOut(**row) for row in rows]

    async def list_admin_patient_cases(
        self,
        *,
        department_id: str | None = None,
        query: str = "",
        current_status: str | None = None,
        limit: int = 200,
    ) -> list[AdminPatientCaseRowOut]:
        if not self._db_enabled():
            if not self._mock_fallback_enabled():
                return []
            rows: list[AdminPatientCaseRowOut] = []
            for bed in self._mock_beds_by_department(department_id or MOCK_DEPARTMENT_ID):
                if not bed.current_patient_id:
                    continue
                patient = MOCK_PATIENTS.get(bed.current_patient_id)
                context = self._mock_patient_context_or_none(bed.current_patient_id)
                rows.append(
                    AdminPatientCaseRowOut(
                        patient_id=bed.current_patient_id,
                        full_name=patient.full_name if patient else (bed.patient_name or "未命名患者"),
                        mrn=patient.mrn if patient else bed.current_patient_id,
                        inpatient_no=patient.inpatient_no if patient else None,
                        gender=patient.gender if patient else None,
                        age=patient.age if patient else None,
                        current_status=patient.current_status if patient else "admitted",
                        department_id=bed.department_id,
                        department_name="心内一病区",
                        bed_no=bed.bed_no,
                        room_no=bed.room_no,
                        risk_tags=context.risk_tags if context else [],
                        pending_tasks=context.pending_tasks if context else [],
                        latest_observation=(context.latest_observations[0].get("name") if context and context.latest_observations else None),
                        updated_at=datetime.now(timezone.utc),
                    )
                )
            return rows[:limit]

        engine = self._engine_or_none()
        if engine is None:
            return []

        normalized_query = (query or "").strip().lower()
        filters = {
            "department_id": (department_id or "").strip(),
            "current_status": (current_status or "").strip(),
            "query_like": f"%{normalized_query}%" if normalized_query else "",
            "limit": max(1, min(int(limit), 500)),
        }
        sql = text(
            """
            WITH latest_obs AS (
                SELECT DISTINCT ON (o.patient_id)
                    o.patient_id::text AS patient_id,
                    o.name,
                    o.value_text,
                    o.value_num,
                    o.unit,
                    o.abnormal_flag,
                    o.observed_at
                FROM observations o
                ORDER BY o.patient_id, o.observed_at DESC
            )
            SELECT
                p.id::text AS patient_id,
                p.full_name,
                p.mrn,
                p.inpatient_no,
                p.gender,
                p.age,
                p.current_status,
                p.updated_at,
                d.id::text AS department_id,
                d.name AS department_name,
                b.bed_no,
                b.room_no,
                obs.name AS obs_name,
                obs.value_text,
                obs.value_num,
                obs.unit,
                obs.abnormal_flag,
                obs.observed_at
            FROM patients p
            LEFT JOIN beds b ON b.current_patient_id = p.id
            LEFT JOIN departments d ON d.id = b.department_id
            LEFT JOIN latest_obs obs ON obs.patient_id = p.id::text
            WHERE (:department_id = '' OR d.id::text = :department_id OR d.code = :department_id)
              AND (:current_status = '' OR p.current_status = :current_status)
              AND (
                    :query_like = ''
                    OR LOWER(
                        CONCAT_WS(' ',
                            COALESCE(p.full_name, ''),
                            COALESCE(p.mrn, ''),
                            COALESCE(p.inpatient_no, ''),
                            COALESCE(b.bed_no, ''),
                            COALESCE(d.name, '')
                        )
                    ) LIKE :query_like
                )
            ORDER BY
                CASE WHEN COALESCE(b.bed_no, '') ~ '^[0-9]+$' THEN LPAD(b.bed_no, 4, '0') ELSE COALESCE(b.bed_no, '9999') END,
                p.updated_at DESC
            LIMIT :limit
            """
        )
        try:
            async with engine.connect() as conn:
                raw_rows = (await conn.execute(sql, filters)).mappings().all()
        except Exception as exc:
            self._mark_db_unavailable(f"list_admin_patient_cases:{exc}")
            return []

        rows: list[AdminPatientCaseRowOut] = []
        for row in raw_rows:
            patient_id = str(row["patient_id"])
            pending_tasks = await self._pending_tasks_for_patient(patient_id)
            risk_tags = await self._risk_tags_for_patient(patient_id)
            rows.append(
                AdminPatientCaseRowOut(
                    patient_id=patient_id,
                    full_name=row["full_name"],
                    mrn=row["mrn"],
                    inpatient_no=row["inpatient_no"],
                    gender=row["gender"],
                    age=row["age"],
                    current_status=row["current_status"],
                    department_id=row["department_id"],
                    department_name=row["department_name"],
                    bed_no=row["bed_no"],
                    room_no=row["room_no"],
                    risk_tags=risk_tags,
                    pending_tasks=pending_tasks,
                    latest_observation=self._format_latest_observation(
                        name=row["obs_name"],
                        value_text=row["value_text"],
                        value_num=row["value_num"],
                        unit=row["unit"],
                        abnormal_flag=row["abnormal_flag"],
                        observed_at=row["observed_at"],
                    ),
                    updated_at=row["updated_at"],
                )
            )
        return rows

    async def get_ward_analytics(self, *, department_id: str | None = None) -> WardAnalyticsOut:
        if not self._db_enabled():
            mock_rows = await self.list_admin_patient_cases(department_id=department_id, limit=200)
            total_patients = len(mock_rows)
            occupied_beds = len([row for row in mock_rows if row.bed_no])
            pending = sum(len(row.pending_tasks) for row in mock_rows)
            high_risk = len([row for row in mock_rows if row.risk_tags])
            return WardAnalyticsOut(
                department_id=department_id or MOCK_DEPARTMENT_ID,
                department_name="心内一病区",
                generated_at=datetime.now(timezone.utc),
                kpis=[
                    AnalyticsKpiOut(key="patients", label="在床患者", value=total_patients, hint="当前病区占床患者"),
                    AnalyticsKpiOut(key="beds", label="占用床位", value=occupied_beds, hint="当前已占用床位"),
                    AnalyticsKpiOut(key="high_risk", label="高风险患者", value=high_risk, hint="存在风险标签的患者"),
                    AnalyticsKpiOut(key="tasks", label="待处理任务", value=pending, hint="待办护理任务总数"),
                ],
                status_distribution=[
                    DistributionItemOut(label="admitted", value=total_patients),
                ],
                risk_distribution=[
                    DistributionItemOut(label="risk_tag", value=high_risk),
                ],
                task_distribution=[
                    DistributionItemOut(label="pending", value=pending),
                ],
                hotspots=[
                    WardHotspotOut(
                        bed_no=row.bed_no or "-",
                        patient_name=row.full_name,
                        score=len(row.risk_tags) + len(row.pending_tasks),
                        reasons=[*row.risk_tags[:2], *row.pending_tasks[:2]],
                        latest_observation=row.latest_observation,
                    )
                    for row in mock_rows[:6]
                ],
            )

        engine = self._engine_or_none()
        if engine is None:
            raise RuntimeError("ward_analytics_not_supported")

        dep_value = (department_id or "").strip()
        department_query = text(
            """
            SELECT id::text AS id, code, name
            FROM departments
            WHERE (:department_id <> '' AND (id::text = :department_id OR code = :department_id))
            ORDER BY name
            LIMIT 1
            """
        )
        kpi_query = text(
            """
            SELECT
                COUNT(DISTINCT CASE WHEN p.current_status = 'admitted' THEN p.id END) AS total_patients,
                COUNT(DISTINCT CASE WHEN b.current_patient_id IS NOT NULL THEN b.id END) AS occupied_beds,
                COUNT(DISTINCT CASE WHEN t.status IN ('pending', 'in_progress') THEN t.id END) AS pending_tasks,
                COUNT(DISTINCT CASE WHEN (
                    (o.abnormal_flag IN ('critical', 'high', 'low') AND o.observed_at >= NOW() - INTERVAL '24 hours')
                    OR (t.task_type = 'risk_tag' AND t.status IN ('pending', 'in_progress'))
                ) THEN p.id END) AS high_risk_patients,
                COUNT(DISTINCT CASE WHEN r.review_required = TRUE AND r.status = 'draft' THEN r.id END) AS review_queue
            FROM patients p
            LEFT JOIN beds b ON b.current_patient_id = p.id
            LEFT JOIN departments d ON d.id = b.department_id
            LEFT JOIN care_tasks t ON t.patient_id = p.id
            LEFT JOIN observations o ON o.patient_id = p.id
            LEFT JOIN ai_recommendations r ON r.patient_id = p.id
            WHERE (:department_id = '' OR d.id::text = :department_id OR d.code = :department_id)
            """
        )
        status_query = text(
            """
            SELECT p.current_status AS label, COUNT(*)::int AS value
            FROM patients p
            LEFT JOIN beds b ON b.current_patient_id = p.id
            LEFT JOIN departments d ON d.id = b.department_id
            WHERE (:department_id = '' OR d.id::text = :department_id OR d.code = :department_id)
            GROUP BY p.current_status
            ORDER BY COUNT(*) DESC
            """
        )
        risk_query = text(
            """
            SELECT abnormal_flag AS label, COUNT(*)::int AS value
            FROM observations o
            JOIN patients p ON p.id = o.patient_id
            LEFT JOIN beds b ON b.current_patient_id = p.id
            LEFT JOIN departments d ON d.id = b.department_id
            WHERE o.abnormal_flag IN ('critical', 'high', 'low')
              AND o.observed_at >= NOW() - INTERVAL '24 hours'
              AND (:department_id = '' OR d.id::text = :department_id OR d.code = :department_id)
            GROUP BY abnormal_flag
            ORDER BY COUNT(*) DESC
            """
        )
        task_query = text(
            """
            SELECT status AS label, COUNT(*)::int AS value
            FROM care_tasks t
            JOIN patients p ON p.id = t.patient_id
            LEFT JOIN beds b ON b.current_patient_id = p.id
            LEFT JOIN departments d ON d.id = b.department_id
            WHERE (:department_id = '' OR d.id::text = :department_id OR d.code = :department_id)
            GROUP BY status
            ORDER BY COUNT(*) DESC
            """
        )
        hotspot_query = text(
            """
            WITH recent_obs AS (
                SELECT DISTINCT ON (o.patient_id)
                    o.patient_id,
                    o.name,
                    o.value_text,
                    o.value_num,
                    o.unit,
                    o.abnormal_flag,
                    o.observed_at
                FROM observations o
                ORDER BY o.patient_id, o.observed_at DESC
            )
            SELECT
                COALESCE(b.bed_no, '-') AS bed_no,
                p.full_name,
                COUNT(DISTINCT CASE WHEN t.status IN ('pending', 'in_progress') THEN t.id END)::int AS pending_count,
                COUNT(DISTINCT CASE WHEN (
                    o.abnormal_flag IN ('critical', 'high', 'low')
                    AND o.observed_at >= NOW() - INTERVAL '24 hours'
                ) THEN o.id END)::int AS abnormal_count,
                recent.name AS obs_name,
                recent.value_text,
                recent.value_num,
                recent.unit,
                recent.abnormal_flag AS obs_flag,
                recent.observed_at AS obs_at
            FROM beds b
            LEFT JOIN patients p ON p.id = b.current_patient_id
            LEFT JOIN departments d ON d.id = b.department_id
            LEFT JOIN care_tasks t ON t.patient_id = p.id
            LEFT JOIN observations o ON o.patient_id = p.id
            LEFT JOIN recent_obs recent ON recent.patient_id = p.id
            WHERE p.id IS NOT NULL
              AND (:department_id = '' OR d.id::text = :department_id OR d.code = :department_id)
            GROUP BY b.bed_no, p.full_name, recent.name, recent.value_text, recent.value_num, recent.unit, recent.abnormal_flag, recent.observed_at
            ORDER BY abnormal_count DESC, pending_count DESC, b.bed_no
            LIMIT 8
            """
        )
        try:
            async with engine.connect() as conn:
                dep_row = None
                if dep_value:
                    dep_row = (await conn.execute(department_query, {"department_id": dep_value})).mappings().first()
                kpi_row = (await conn.execute(kpi_query, {"department_id": dep_value})).mappings().first()
                status_rows = (await conn.execute(status_query, {"department_id": dep_value})).mappings().all()
                risk_rows = (await conn.execute(risk_query, {"department_id": dep_value})).mappings().all()
                task_rows = (await conn.execute(task_query, {"department_id": dep_value})).mappings().all()
                hotspot_rows = (await conn.execute(hotspot_query, {"department_id": dep_value})).mappings().all()
        except Exception as exc:
            self._mark_db_unavailable(f"get_ward_analytics:{exc}")
            raise RuntimeError("ward_analytics_not_supported") from exc

        kpi_row = kpi_row or {}
        hotspots: list[WardHotspotOut] = []
        for row in hotspot_rows:
            reasons: list[str] = []
            if int(row["abnormal_count"] or 0) > 0:
                reasons.append(f"异常观测 {int(row['abnormal_count'])} 条")
            if int(row["pending_count"] or 0) > 0:
                reasons.append(f"待办任务 {int(row['pending_count'])} 项")
            hotspots.append(
                WardHotspotOut(
                    bed_no=str(row["bed_no"] or "-"),
                    patient_name=row["full_name"],
                    score=int(row["abnormal_count"] or 0) * 2 + int(row["pending_count"] or 0),
                    reasons=reasons,
                    latest_observation=self._format_latest_observation(
                        name=row["obs_name"],
                        value_text=row["value_text"],
                        value_num=row["value_num"],
                        unit=row["unit"],
                        abnormal_flag=row["obs_flag"],
                        observed_at=row["obs_at"],
                    ),
                )
            )

        return WardAnalyticsOut(
            department_id=dep_row["id"] if dep_row else (dep_value or None),
            department_name=dep_row["name"] if dep_row else "全部病区",
            generated_at=datetime.now(timezone.utc),
            kpis=[
                AnalyticsKpiOut(key="patients", label="在床患者", value=int(kpi_row.get("total_patients") or 0), hint="当前病区在床患者数"),
                AnalyticsKpiOut(key="beds", label="占用床位", value=int(kpi_row.get("occupied_beds") or 0), hint="已有患者占用的床位"),
                AnalyticsKpiOut(key="high_risk", label="高风险患者", value=int(kpi_row.get("high_risk_patients") or 0), hint="24小时异常或风险标签"),
                AnalyticsKpiOut(key="tasks", label="待处理任务", value=int(kpi_row.get("pending_tasks") or 0), hint="待办与处理中任务"),
                AnalyticsKpiOut(key="review", label="待复核推荐", value=int(kpi_row.get("review_queue") or 0), hint="仍需人工复核的 AI 结果"),
            ],
            status_distribution=[DistributionItemOut(label=str(row["label"] or "unknown"), value=int(row["value"] or 0)) for row in status_rows],
            risk_distribution=[DistributionItemOut(label=str(row["label"] or "unknown"), value=int(row["value"] or 0)) for row in risk_rows],
            task_distribution=[DistributionItemOut(label=str(row["label"] or "unknown"), value=int(row["value"] or 0)) for row in task_rows],
            hotspots=hotspots,
        )

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
                patient = MOCK_PATIENTS.get(patient_id)
                return patient.model_copy(deep=True) if patient else None
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
                patient = MOCK_PATIENTS.get(patient_id)
                return patient.model_copy(deep=True) if patient else None
            return None
        return PatientBase(**row) if row else None

    async def get_patient_case(self, patient_id: str) -> PatientCaseBundleOut | None:
        if not self._db_enabled():
            if self._mock_fallback_enabled():
                return get_patient_case_bundle(patient_id)
            return None
        patient = await self.get_patient(patient_id)
        if patient is None:
            return None
        context = await self.get_patient_context(patient_id)
        if context is None:
            return None

        engine = self._engine_or_none()
        if engine is None:
            return None

        bed_query = text(
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
            WHERE b.current_patient_id::text = :patient_id
            ORDER BY b.updated_at DESC, b.created_at DESC
            LIMIT 1
            """
        )
        try:
            async with engine.connect() as conn:
                bed_row = (await conn.execute(bed_query, {"patient_id": patient_id})).mappings().first()
        except Exception as exc:
            self._mark_db_unavailable(f"get_patient_case:{exc}")
            if self._mock_fallback_enabled():
                return get_patient_case_bundle(patient_id)
            return None

        risk_tags = await self._risk_tags_for_patient(patient_id)
        pending_tasks = await self._pending_tasks_for_patient(patient_id)
        bed = BedOverview(
            id=bed_row["id"] if bed_row else f"bed-unassigned-{patient_id}",
            department_id=bed_row["department_id"] if bed_row else MOCK_DEPARTMENT_ID,
            bed_no=bed_row["bed_no"] if bed_row else (context.bed_no or "未分配"),
            room_no=bed_row["room_no"] if bed_row else None,
            status=bed_row["status"] if bed_row else "empty",
            current_patient_id=bed_row["current_patient_id"] if bed_row else patient_id,
            patient_name=bed_row["patient_name"] if bed_row else patient.full_name,
            risk_tags=risk_tags,
            pending_tasks=pending_tasks,
            latest_document_sync=context.latest_document_sync,
        )
        return PatientCaseBundleOut(created=False, patient=patient, context=context, bed=bed)

    async def upsert_patient_case(self, payload: PatientCaseUpsertRequest) -> PatientCaseBundleOut:
        if not self._db_enabled():
            if self._mock_fallback_enabled():
                return upsert_patient_case(payload)
            raise RuntimeError("patient_case_upsert_not_supported")
        engine = self._engine_or_none()
        if engine is None:
            if self._mock_fallback_enabled():
                return upsert_patient_case(payload)
            raise RuntimeError("patient_case_upsert_not_supported")

        patient_uuid = self._normalize_uuid(payload.patient_id)
        encounter_uuid = self._normalize_uuid(payload.encounter_id)
        created = False
        mrn = (payload.mrn or "").strip() or self._auto_mrn(payload.full_name)
        inpatient_no = (payload.inpatient_no or "").strip() or f"IP-{datetime.now(timezone.utc).strftime('%m%d%H%M%S')}"
        room_no = (payload.room_no or "").strip() or None

        try:
            async with engine.begin() as conn:
                department_row = None
                if patient_uuid:
                    department_row = (
                        await conn.execute(
                            text(
                                """
                                SELECT b.department_id::text AS department_id
                                FROM beds b
                                WHERE b.current_patient_id::text = :patient_id
                                LIMIT 1
                                """
                            ),
                            {"patient_id": patient_uuid},
                        )
                    ).mappings().first()

                target_bed_row = (
                    await conn.execute(
                        text(
                            """
                            SELECT
                                id::text AS id,
                                department_id::text AS department_id,
                                bed_no,
                                room_no,
                                status,
                                current_patient_id::text AS current_patient_id
                            FROM beds
                            WHERE bed_no = :bed_no
                            ORDER BY updated_at DESC, created_at DESC
                            LIMIT 1
                            """
                        ),
                        {"bed_no": payload.bed_no},
                    )
                ).mappings().first()

                if department_row is None and target_bed_row is not None:
                    department_row = {"department_id": target_bed_row["department_id"]}

                department_id = department_row["department_id"] if department_row else await self._ensure_default_department(conn)

                if target_bed_row and target_bed_row["current_patient_id"]:
                    occupied_by = str(target_bed_row["current_patient_id"])
                    if occupied_by != (patient_uuid or ""):
                        raise ValueError("bed_already_occupied")

                if patient_uuid:
                    existing_patient = (
                        await conn.execute(
                            text("SELECT id::text AS id FROM patients WHERE id::text = :patient_id LIMIT 1"),
                            {"patient_id": patient_uuid},
                        )
                    ).mappings().first()
                    if existing_patient:
                        patient_row = (
                            await conn.execute(
                                text(
                                    """
                                    UPDATE patients
                                    SET mrn = :mrn,
                                        inpatient_no = :inpatient_no,
                                        full_name = :full_name,
                                        gender = :gender,
                                        age = :age,
                                        blood_type = :blood_type,
                                        allergy_info = :allergy_info,
                                        current_status = :current_status,
                                        updated_at = NOW()
                                    WHERE id::text = :patient_id
                                    RETURNING id::text AS id
                                    """
                                ),
                                {
                                    "patient_id": patient_uuid,
                                    "mrn": mrn,
                                    "inpatient_no": inpatient_no,
                                    "full_name": payload.full_name,
                                    "gender": payload.gender,
                                    "age": payload.age,
                                    "blood_type": payload.blood_type,
                                    "allergy_info": payload.allergy_info,
                                    "current_status": payload.current_status,
                                },
                            )
                        ).mappings().first()
                    else:
                        patient_row = (
                            await conn.execute(
                                text(
                                    """
                                    INSERT INTO patients (
                                        id, mrn, inpatient_no, full_name, gender, age, blood_type, allergy_info, current_status
                                    )
                                    VALUES (
                                        CAST(:patient_id AS uuid), :mrn, :inpatient_no, :full_name, :gender, :age, :blood_type, :allergy_info, :current_status
                                    )
                                    RETURNING id::text AS id
                                    """
                                ),
                                {
                                    "patient_id": patient_uuid,
                                    "mrn": mrn,
                                    "inpatient_no": inpatient_no,
                                    "full_name": payload.full_name,
                                    "gender": payload.gender,
                                    "age": payload.age,
                                    "blood_type": payload.blood_type,
                                    "allergy_info": payload.allergy_info,
                                    "current_status": payload.current_status,
                                },
                            )
                        ).mappings().first()
                        created = True
                else:
                    patient_row = (
                        await conn.execute(
                            text(
                                """
                                INSERT INTO patients (
                                    mrn, inpatient_no, full_name, gender, age, blood_type, allergy_info, current_status
                                )
                                VALUES (
                                    :mrn, :inpatient_no, :full_name, :gender, :age, :blood_type, :allergy_info, :current_status
                                )
                                RETURNING id::text AS id
                                """
                            ),
                            {
                                "mrn": mrn,
                                "inpatient_no": inpatient_no,
                                "full_name": payload.full_name,
                                "gender": payload.gender,
                                "age": payload.age,
                                "blood_type": payload.blood_type,
                                "allergy_info": payload.allergy_info,
                                "current_status": payload.current_status,
                            },
                        )
                    ).mappings().first()
                    created = True

                patient_uuid = patient_row["id"]

                previous_beds = (
                    await conn.execute(
                        text(
                            """
                            SELECT id::text AS id
                            FROM beds
                            WHERE current_patient_id::text = :patient_id
                            """
                        ),
                        {"patient_id": patient_uuid},
                    )
                ).mappings().all()
                for previous_bed in previous_beds:
                    if not target_bed_row or previous_bed["id"] != target_bed_row["id"]:
                        await conn.execute(
                            text(
                                """
                                UPDATE beds
                                SET current_patient_id = NULL,
                                    status = 'empty',
                                    updated_at = NOW()
                                WHERE id::text = :bed_id
                                """
                            ),
                            {"bed_id": previous_bed["id"]},
                        )

                if target_bed_row:
                    await conn.execute(
                        text(
                            """
                            UPDATE beds
                            SET department_id = CAST(:department_id AS uuid),
                                room_no = COALESCE(:room_no, room_no),
                                current_patient_id = CAST(:patient_id AS uuid),
                                status = 'occupied',
                                updated_at = NOW()
                            WHERE id::text = :bed_id
                            """
                        ),
                        {
                            "bed_id": target_bed_row["id"],
                            "department_id": department_id,
                            "room_no": room_no,
                            "patient_id": patient_uuid,
                        },
                    )
                else:
                    inserted_bed = (
                        await conn.execute(
                            text(
                                """
                                INSERT INTO beds (department_id, bed_no, room_no, status, current_patient_id)
                                VALUES (CAST(:department_id AS uuid), :bed_no, :room_no, 'occupied', CAST(:patient_id AS uuid))
                                RETURNING id::text AS id
                                """
                            ),
                            {
                                "department_id": department_id,
                                "bed_no": payload.bed_no,
                                "room_no": room_no,
                                "patient_id": patient_uuid,
                            },
                        )
                    ).mappings().first()
                    target_bed_row = {
                        "id": inserted_bed["id"],
                        "department_id": department_id,
                    }

                encounter_row = None
                if encounter_uuid:
                    encounter_row = (
                        await conn.execute(
                            text(
                                """
                                SELECT id::text AS id
                                FROM encounters
                                WHERE id::text = :encounter_id
                                LIMIT 1
                                """
                            ),
                            {"encounter_id": encounter_uuid},
                        )
                    ).mappings().first()
                if encounter_row is None:
                    encounter_row = (
                        await conn.execute(
                            text(
                                """
                                SELECT id::text AS id
                                FROM encounters
                                WHERE patient_id::text = :patient_id
                                  AND status = 'active'
                                ORDER BY admission_at DESC NULLS LAST, created_at DESC
                                LIMIT 1
                                """
                            ),
                            {"patient_id": patient_uuid},
                        )
                    ).mappings().first()
                if encounter_row:
                    encounter_uuid = encounter_row["id"]
                    await conn.execute(
                        text(
                            """
                            UPDATE encounters
                            SET department_id = CAST(:department_id AS uuid),
                                encounter_type = 'inpatient',
                                status = 'active',
                                admission_diagnosis = :admission_diagnosis,
                                updated_at = NOW()
                            WHERE id::text = :encounter_id
                            """
                        ),
                        {
                            "department_id": department_id,
                            "admission_diagnosis": payload.diagnoses[0] if payload.diagnoses else None,
                            "encounter_id": encounter_uuid,
                        },
                    )
                else:
                    encounter_row = (
                        await conn.execute(
                            text(
                                """
                                INSERT INTO encounters (
                                    patient_id, encounter_type, department_id, admission_at, status, chief_complaint, admission_diagnosis
                                )
                                VALUES (
                                    CAST(:patient_id AS uuid), 'inpatient', CAST(:department_id AS uuid), NOW(), 'active', :chief_complaint, :admission_diagnosis
                                )
                                RETURNING id::text AS id
                                """
                            ),
                            {
                                "patient_id": patient_uuid,
                                "department_id": department_id,
                                "chief_complaint": payload.pending_tasks[0] if payload.pending_tasks else None,
                                "admission_diagnosis": payload.diagnoses[0] if payload.diagnoses else None,
                            },
                        )
                    ).mappings().first()
                    encounter_uuid = encounter_row["id"]

                await conn.execute(
                    text("DELETE FROM patient_diagnoses WHERE encounter_id::text = :encounter_id"),
                    {"encounter_id": encounter_uuid},
                )
                for index, diagnosis in enumerate(payload.diagnoses):
                    name = str(diagnosis or "").strip()
                    if not name:
                        continue
                    await conn.execute(
                        text(
                            """
                            INSERT INTO patient_diagnoses (
                                encounter_id, diagnosis_name, diagnosis_type, status, diagnosed_at
                            )
                            VALUES (
                                CAST(:encounter_id AS uuid), :diagnosis_name, :diagnosis_type, 'active', NOW()
                            )
                            """
                        ),
                        {
                            "encounter_id": encounter_uuid,
                            "diagnosis_name": name,
                            "diagnosis_type": "primary" if index == 0 else "secondary",
                        },
                    )

                await conn.execute(
                    text(
                        """
                        DELETE FROM care_tasks
                        WHERE patient_id::text = :patient_id
                          AND source_type = 'manual'
                          AND task_type IN ('case_seed', 'risk_tag')
                          AND status IN ('pending', 'in_progress')
                        """
                    ),
                    {"patient_id": patient_uuid},
                )
                for task in payload.pending_tasks:
                    title = str(task or "").strip()
                    if not title:
                        continue
                    await conn.execute(
                        text(
                            """
                            INSERT INTO care_tasks (
                                patient_id, encounter_id, source_type, task_type, title, priority, status, review_required
                            )
                            VALUES (
                                CAST(:patient_id AS uuid), CAST(:encounter_id AS uuid), 'manual', 'case_seed', :title, 2, 'pending', FALSE
                            )
                            """
                        ),
                        {
                            "patient_id": patient_uuid,
                            "encounter_id": encounter_uuid,
                            "title": title,
                        },
                    )
                for risk_tag in payload.risk_tags:
                    title = str(risk_tag or "").strip()
                    if not title:
                        continue
                    await conn.execute(
                        text(
                            """
                            INSERT INTO care_tasks (
                                patient_id, encounter_id, source_type, task_type, title, priority, status, review_required
                            )
                            VALUES (
                                CAST(:patient_id AS uuid), CAST(:encounter_id AS uuid), 'manual', 'risk_tag', :title, 1, 'pending', FALSE
                            )
                            """
                        ),
                        {
                            "patient_id": patient_uuid,
                            "encounter_id": encounter_uuid,
                            "title": title,
                        },
                    )

                for observation in payload.latest_observations:
                    name = str(observation.name or "").strip()
                    value = str(observation.value or "").strip()
                    if not name:
                        continue
                    await conn.execute(
                        text(
                            """
                            INSERT INTO observations (
                                patient_id, encounter_id, category, name, value_text, abnormal_flag, observed_at, source
                            )
                            VALUES (
                                CAST(:patient_id AS uuid), CAST(:encounter_id AS uuid), 'nursing', :name, :value_text, :abnormal_flag, NOW(), 'manual'
                            )
                            """
                        ),
                        {
                            "patient_id": patient_uuid,
                            "encounter_id": encounter_uuid,
                            "name": name,
                            "value_text": value,
                            "abnormal_flag": observation.abnormal_flag,
                        },
                    )
        except ValueError:
            raise
        except Exception as exc:
            self._mark_db_unavailable(f"upsert_patient_case:{exc}", cooldown_sec=20)
            if self._mock_fallback_enabled():
                return upsert_patient_case(payload)
            raise RuntimeError("patient_case_upsert_not_supported") from exc

        bundle = await self.get_patient_case(patient_uuid)
        if bundle is None:
            raise RuntimeError("patient_case_upsert_not_supported")
        return PatientCaseBundleOut(
            created=created,
            patient=bundle.patient,
            context=bundle.context,
            bed=bundle.bed,
        )

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
              AND COALESCE(task_type, '') <> 'risk_tag'
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

        obs_query = text(
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
        task_query = text(
            """
            SELECT DISTINCT title
            FROM care_tasks
            WHERE patient_id::text = :patient_id
              AND task_type = 'risk_tag'
              AND status IN ('pending', 'in_progress')
            ORDER BY title
            LIMIT 8
            """
        )
        try:
            async with engine.connect() as conn:
                obs_rows = (await conn.execute(obs_query, {"patient_id": patient_id})).mappings().all()
                task_rows = (await conn.execute(task_query, {"patient_id": patient_id})).mappings().all()
        except Exception as exc:
            self._mark_db_unavailable(f"_risk_tags_for_patient:{exc}")
            if not self._mock_fallback_enabled():
                return []
            context = self._mock_patient_context_or_none(patient_id)
            return context.risk_tags if context else []
        merged: list[str] = [f"{row['name']}({row['abnormal_flag']})" for row in obs_rows]
        merged.extend(str(row["title"]) for row in task_rows if str(row["title"]).strip())
        return list(dict.fromkeys(merged))


repository = PatientContextRepository()

