from datetime import datetime, timedelta, timezone
from typing import Any

from app.schemas.patient import BedOverview, OrderExecutionTrail, OrderOut, PatientBase, PatientContextOut


MOCK_DEPARTMENT_ID = "dep-card-01"

_CASE_SEEDS = [
    {
        "patient_id": "pat-001",
        "mrn": "MRN-0001",
        "inpatient_no": "IP-2026-0001",
        "full_name": "张晓明",
        "gender": "男",
        "age": 45,
        "blood_type": "A+",
        "allergy_info": "青霉素过敏",
        "bed_no": "12",
        "room_no": "612",
        "encounter_id": "enc-001",
        "diagnoses": ["慢性心衰急性加重"],
        "risk_tags": ["低血压风险", "液体管理风险"],
        "pending_tasks": ["复测血压", "记录尿量"],
        "latest_observations": [
            {"name": "收缩压", "value": "88 mmHg", "abnormal_flag": "low"},
            {"name": "4小时尿量", "value": "85 ml", "abnormal_flag": "low"},
        ],
    },
    {
        "patient_id": "pat-002",
        "mrn": "MRN-0002",
        "inpatient_no": "IP-2026-0002",
        "full_name": "王丽",
        "gender": "女",
        "age": 48,
        "blood_type": "B+",
        "allergy_info": None,
        "bed_no": "15",
        "room_no": "615",
        "encounter_id": "enc-002",
        "diagnoses": ["肺部感染恢复期"],
        "risk_tags": ["呼吸频率波动"],
        "pending_tasks": ["监测SpO2"],
        "latest_observations": [
            {"name": "SpO2", "value": "93%", "abnormal_flag": "low"},
            {"name": "呼吸频率", "value": "24 次/分", "abnormal_flag": "high"},
        ],
    },
    {
        "patient_id": "pat-003",
        "mrn": "MRN-0003",
        "inpatient_no": "IP-2026-0003",
        "full_name": "李建国",
        "gender": "男",
        "age": 62,
        "blood_type": "O+",
        "allergy_info": "头孢过敏",
        "bed_no": "16",
        "room_no": "616",
        "encounter_id": "enc-003",
        "diagnoses": ["2型糖尿病", "下肢感染"],
        "risk_tags": ["血糖波动风险", "感染扩散风险"],
        "pending_tasks": ["复测血糖", "评估创面"],
        "latest_observations": [
            {"name": "随机血糖", "value": "16.2 mmol/L", "abnormal_flag": "high"},
            {"name": "体温", "value": "37.8°C", "abnormal_flag": "high"},
        ],
    },
    {
        "patient_id": "pat-004",
        "mrn": "MRN-0004",
        "inpatient_no": "IP-2026-0004",
        "full_name": "赵敏",
        "gender": "女",
        "age": 36,
        "blood_type": "AB+",
        "allergy_info": None,
        "bed_no": "17",
        "room_no": "617",
        "encounter_id": "enc-004",
        "diagnoses": ["术后恢复期"],
        "risk_tags": ["疼痛管理风险", "切口感染风险"],
        "pending_tasks": ["疼痛评分", "换药观察"],
        "latest_observations": [
            {"name": "疼痛评分", "value": "7/10", "abnormal_flag": "high"},
            {"name": "体温", "value": "37.4°C", "abnormal_flag": "normal"},
        ],
    },
    {
        "patient_id": "pat-005",
        "mrn": "MRN-0005",
        "inpatient_no": "IP-2026-0005",
        "full_name": "陈伟",
        "gender": "男",
        "age": 71,
        "blood_type": "A-",
        "allergy_info": "阿司匹林过敏",
        "bed_no": "18",
        "room_no": "618",
        "encounter_id": "enc-005",
        "diagnoses": ["慢阻肺急性加重"],
        "risk_tags": ["低氧风险", "二氧化碳潴留风险"],
        "pending_tasks": ["监测血氧", "评估吸氧效果"],
        "latest_observations": [
            {"name": "SpO2", "value": "89%", "abnormal_flag": "critical"},
            {"name": "呼吸频率", "value": "28 次/分", "abnormal_flag": "high"},
        ],
    },
    {
        "patient_id": "pat-006",
        "mrn": "MRN-0006",
        "inpatient_no": "IP-2026-0006",
        "full_name": "周芳",
        "gender": "女",
        "age": 54,
        "blood_type": "O-",
        "allergy_info": None,
        "bed_no": "19",
        "room_no": "619",
        "encounter_id": "enc-006",
        "diagnoses": ["高血压病3级"],
        "risk_tags": ["血压波动风险", "卒中风险"],
        "pending_tasks": ["每小时测压", "神经评估"],
        "latest_observations": [
            {"name": "收缩压", "value": "176 mmHg", "abnormal_flag": "high"},
            {"name": "舒张压", "value": "104 mmHg", "abnormal_flag": "high"},
        ],
    },
    {
        "patient_id": "pat-007",
        "mrn": "MRN-0007",
        "inpatient_no": "IP-2026-0007",
        "full_name": "孙强",
        "gender": "男",
        "age": 59,
        "blood_type": "B-",
        "allergy_info": None,
        "bed_no": "20",
        "room_no": "620",
        "encounter_id": "enc-007",
        "diagnoses": ["急性胰腺炎"],
        "risk_tags": ["腹痛加重风险", "液体丢失风险"],
        "pending_tasks": ["监测腹痛", "评估补液平衡"],
        "latest_observations": [
            {"name": "疼痛评分", "value": "8/10", "abnormal_flag": "high"},
            {"name": "心率", "value": "110 次/分", "abnormal_flag": "high"},
        ],
    },
    {
        "patient_id": "pat-008",
        "mrn": "MRN-0008",
        "inpatient_no": "IP-2026-0008",
        "full_name": "何静",
        "gender": "女",
        "age": 67,
        "blood_type": "A+",
        "allergy_info": "磺胺类过敏",
        "bed_no": "21",
        "room_no": "621",
        "encounter_id": "enc-008",
        "diagnoses": ["慢性肾病", "贫血"],
        "risk_tags": ["容量负荷风险", "高钾风险"],
        "pending_tasks": ["评估出入量", "复测电解质"],
        "latest_observations": [
            {"name": "血钾", "value": "5.9 mmol/L", "abnormal_flag": "high"},
            {"name": "24小时尿量", "value": "680 ml", "abnormal_flag": "low"},
        ],
    },
    {
        "patient_id": "pat-009",
        "mrn": "MRN-0009",
        "inpatient_no": "IP-2026-0009",
        "full_name": "郭林",
        "gender": "男",
        "age": 41,
        "blood_type": "O+",
        "allergy_info": None,
        "bed_no": "22",
        "room_no": "622",
        "encounter_id": "enc-009",
        "diagnoses": ["脑出血术后"],
        "risk_tags": ["意识波动风险", "再出血风险"],
        "pending_tasks": ["神经评分", "瞳孔监测"],
        "latest_observations": [
            {"name": "GCS", "value": "12 分", "abnormal_flag": "low"},
            {"name": "收缩压", "value": "152 mmHg", "abnormal_flag": "high"},
        ],
    },
    {
        "patient_id": "pat-010",
        "mrn": "MRN-0010",
        "inpatient_no": "IP-2026-0010",
        "full_name": "刘娜",
        "gender": "女",
        "age": 29,
        "blood_type": "B+",
        "allergy_info": None,
        "bed_no": "23",
        "room_no": "623",
        "encounter_id": "enc-010",
        "diagnoses": ["产后出血恢复期"],
        "risk_tags": ["贫血风险", "感染风险"],
        "pending_tasks": ["观察恶露", "监测体温与心率"],
        "latest_observations": [
            {"name": "血红蛋白", "value": "88 g/L", "abnormal_flag": "low"},
            {"name": "心率", "value": "104 次/分", "abnormal_flag": "high"},
        ],
    },
]


MOCK_PATIENTS: dict[str, PatientBase] = {
    item["patient_id"]: PatientBase(
        id=item["patient_id"],
        mrn=item["mrn"],
        inpatient_no=item["inpatient_no"],
        full_name=item["full_name"],
        gender=item["gender"],
        age=item["age"],
        blood_type=item["blood_type"],
        allergy_info=item["allergy_info"],
        current_status="admitted",
    )
    for item in _CASE_SEEDS
}

MOCK_BEDS: list[BedOverview] = [
    BedOverview(
        id=f"bed-{item['bed_no']}",
        department_id=MOCK_DEPARTMENT_ID,
        bed_no=item["bed_no"],
        room_no=item["room_no"],
        status="occupied",
        current_patient_id=item["patient_id"],
        patient_name=item["full_name"],
        risk_tags=list(item["risk_tags"]),
        pending_tasks=list(item["pending_tasks"]),
    )
    for item in _CASE_SEEDS
]

MOCK_CONTEXTS: dict[str, PatientContextOut] = {
    item["patient_id"]: PatientContextOut(
        patient_id=item["patient_id"],
        bed_no=item["bed_no"],
        encounter_id=item["encounter_id"],
        diagnoses=list(item["diagnoses"]),
        risk_tags=list(item["risk_tags"]),
        pending_tasks=list(item["pending_tasks"]),
        latest_observations=[dict(obs) for obs in item["latest_observations"]],
        updated_at=datetime.now(timezone.utc),
    )
    for item in _CASE_SEEDS
}


def _rolling_stage() -> int:
    return int(datetime.now(timezone.utc).timestamp() // 20) % 3


def _patient_stage(patient_id: str) -> int:
    offset = sum(ord(ch) for ch in patient_id) % 3
    return (_rolling_stage() + offset) % 3


def _evolve_context(ctx: PatientContextOut, stage: int) -> None:
    if stage == 0:
        return

    if stage == 1:
        if ctx.latest_observations:
            first = ctx.latest_observations[0]
            first["abnormal_flag"] = "normal"
        if ctx.risk_tags:
            ctx.risk_tags = ctx.risk_tags[:2]
        if ctx.pending_tasks:
            ctx.pending_tasks = [ctx.pending_tasks[0], "继续趋势观察"]
        return

    if ctx.latest_observations:
        first = ctx.latest_observations[0]
        first["abnormal_flag"] = "critical"
        first["value"] = f"{first.get('value', '-') } (波动)"

    if "病情波动风险" not in ctx.risk_tags:
        ctx.risk_tags = [*ctx.risk_tags, "病情波动风险"]

    urgent = "立即复核生命体征并通知医生"
    if urgent not in ctx.pending_tasks:
        ctx.pending_tasks = [urgent, *ctx.pending_tasks]


def get_dynamic_context(patient_id: str) -> PatientContextOut | None:
    base = MOCK_CONTEXTS.get(patient_id)
    if base is None:
        return None

    ctx = base.model_copy(deep=True)
    stage = _patient_stage(patient_id)
    _evolve_context(ctx, stage)
    ctx.updated_at = datetime.now(timezone.utc)
    return ctx


def get_dynamic_beds(department_id: str) -> list[BedOverview]:
    if department_id != MOCK_DEPARTMENT_ID:
        return []

    result: list[BedOverview] = []
    for bed in MOCK_BEDS:
        bed_copy = bed.model_copy(deep=True)
        if bed_copy.current_patient_id:
            context = get_dynamic_context(bed_copy.current_patient_id)
            if context is not None:
                bed_copy.risk_tags = context.risk_tags
                bed_copy.pending_tasks = context.pending_tasks
        result.append(bed_copy)
    return result



def _mock_order_rows(patient_id: str, encounter_id: str, index: int) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    base_no = 1000 + index * 10
    return [
        {
            "id": f"ord-{patient_id}-01",
            "patient_id": patient_id,
            "encounter_id": encounter_id,
            "order_no": f"YZZL-{base_no + 1}",
            "order_type": "medication",
            "title": "去甲肾上腺素微量泵入",
            "instruction": "维持MAP>65 mmHg，按血压滴定速度",
            "route": "静脉泵入",
            "dosage": "4mg/50ml",
            "frequency": "持续",
            "priority": "P1",
            "status": "pending",
            "ordered_by": "dr_wang",
            "ordered_at": now - timedelta(hours=2),
            "due_at": now + timedelta(minutes=10),
            "requires_double_check": True,
            "risk_hints": ["血管活性药", "需双人核对", "注意外渗风险"],
        },
        {
            "id": f"ord-{patient_id}-02",
            "patient_id": patient_id,
            "encounter_id": encounter_id,
            "order_no": f"YZZL-{base_no + 2}",
            "order_type": "lab",
            "title": "复查电解质 + 血气分析",
            "instruction": "采血后30分钟内送检，重点关注K+与乳酸",
            "route": "静脉采血",
            "dosage": None,
            "frequency": "q6h",
            "priority": "P1",
            "status": "pending",
            "ordered_by": "dr_wang",
            "ordered_at": now - timedelta(hours=1, minutes=20),
            "due_at": now + timedelta(minutes=40),
            "requires_double_check": False,
            "risk_hints": ["检验时效要求高", "关系液体与升压策略调整"],
        },
        {
            "id": f"ord-{patient_id}-03",
            "patient_id": patient_id,
            "encounter_id": encounter_id,
            "order_no": f"YZZL-{base_no + 3}",
            "order_type": "nursing",
            "title": "严格记录出入量",
            "instruction": "每小时登记尿量、补液量，班末汇总并复核",
            "route": "护理记录",
            "dosage": None,
            "frequency": "q1h",
            "priority": "P2",
            "status": "checked",
            "ordered_by": "dr_li",
            "ordered_at": now - timedelta(hours=5),
            "due_at": now + timedelta(minutes=25),
            "requires_double_check": False,
            "check_by": "u_nurse_01",
            "check_at": now - timedelta(hours=1, minutes=10),
            "risk_hints": ["容量管理核心指标"],
        },
    ]


def _build_orders() -> tuple[dict[str, list[OrderOut]], dict[str, OrderOut], dict[str, list[OrderOut]]]:
    by_patient: dict[str, list[OrderOut]] = {}
    by_id: dict[str, OrderOut] = {}
    history_by_patient: dict[str, list[OrderOut]] = {}

    for idx, item in enumerate(_CASE_SEEDS):
        patient_id = item["patient_id"]
        encounter_id = item["encounter_id"]
        rows = _mock_order_rows(patient_id, encounter_id, idx + 1)
        orders: list[OrderOut] = []
        for row in rows:
            order = OrderOut(
                **row,
                audit_trail=[
                    OrderExecutionTrail(
                        action="created",
                        actor=row.get("ordered_by") or "system",
                        note="医嘱已下达",
                        created_at=row.get("ordered_at") or datetime.now(timezone.utc),
                    )
                ],
            )
            orders.append(order)
            by_id[order.id] = order
        by_patient[patient_id] = orders
        history_by_patient[patient_id] = []
    return by_patient, by_id, history_by_patient


MOCK_ORDERS_BY_PATIENT, MOCK_ORDERS_BY_ID, MOCK_ORDER_HISTORY = _build_orders()


def _touch_order(order: OrderOut, action: str, actor: str, note: str | None = None) -> None:
    order.audit_trail = [
        *order.audit_trail,
        OrderExecutionTrail(
            action=action,
            actor=actor,
            note=note,
            created_at=datetime.now(timezone.utc),
        ),
    ]


def get_active_orders_for_patient(patient_id: str) -> list[OrderOut]:
    orders = MOCK_ORDERS_BY_PATIENT.get(patient_id, [])
    return [item.model_copy(deep=True) for item in orders]


def get_order_history_for_patient(patient_id: str) -> list[OrderOut]:
    history = MOCK_ORDER_HISTORY.get(patient_id, [])
    return [item.model_copy(deep=True) for item in history]


def mark_order_checked(order_id: str, checked_by: str, note: str | None = None) -> OrderOut | None:
    order = MOCK_ORDERS_BY_ID.get(order_id)
    if order is None:
        return None
    if order.status in {"executed", "exception", "cancelled"}:
        return order.model_copy(deep=True)

    order.status = "checked"
    order.check_by = checked_by
    order.check_at = datetime.now(timezone.utc)
    _touch_order(order, action="double_checked", actor=checked_by, note=note)
    return order.model_copy(deep=True)


def mark_order_executed(order_id: str, executed_by: str, note: str | None = None) -> OrderOut | None:
    order = MOCK_ORDERS_BY_ID.get(order_id)
    if order is None:
        return None
    if order.status in {"executed", "cancelled"}:
        return order.model_copy(deep=True)

    order.status = "executed"
    order.executed_by = executed_by
    order.executed_at = datetime.now(timezone.utc)
    order.execution_note = note
    _touch_order(order, action="executed", actor=executed_by, note=note)

    patient_orders = MOCK_ORDERS_BY_PATIENT.get(order.patient_id, [])
    MOCK_ORDERS_BY_PATIENT[order.patient_id] = [item for item in patient_orders if item.id != order_id]
    MOCK_ORDER_HISTORY.setdefault(order.patient_id, []).insert(0, order.model_copy(deep=True))
    return order.model_copy(deep=True)


def mark_order_exception(order_id: str, reported_by: str, reason: str) -> OrderOut | None:
    order = MOCK_ORDERS_BY_ID.get(order_id)
    if order is None:
        return None
    order.status = "exception"
    order.exception_reason = reason
    _touch_order(order, action="exception_reported", actor=reported_by, note=reason)

    patient_orders = MOCK_ORDERS_BY_PATIENT.get(order.patient_id, [])
    MOCK_ORDERS_BY_PATIENT[order.patient_id] = [item for item in patient_orders if item.id != order_id]
    MOCK_ORDER_HISTORY.setdefault(order.patient_id, []).insert(0, order.model_copy(deep=True))
    return order.model_copy(deep=True)


def get_order_stats(patient_id: str) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    orders = MOCK_ORDERS_BY_PATIENT.get(patient_id, [])
    pending = 0
    due_30m = 0
    overdue = 0
    high_alert = 0

    for order in orders:
        if order.status in {"pending", "checked"}:
            pending += 1
        if order.requires_double_check or order.priority == "P1":
            high_alert += 1
        if order.due_at:
            if order.due_at < now:
                overdue += 1
            elif (order.due_at - now).total_seconds() <= 30 * 60:
                due_30m += 1

    return {
        "pending": pending,
        "due_30m": due_30m,
        "overdue": overdue,
        "high_alert": high_alert,
    }


def create_order_request(
    *,
    patient_id: str,
    requested_by: str,
    title: str,
    details: str,
    priority: str = "P2",
) -> OrderOut:
    now = datetime.now(timezone.utc)
    new_id = f"ord-{patient_id}-req-{int(now.timestamp())}"
    order = OrderOut(
        id=new_id,
        patient_id=patient_id,
        encounter_id=None,
        order_no=f"REQ-{int(now.timestamp())}",
        order_type="doctor_review_request",
        title=title,
        instruction=details,
        route="会诊请求",
        dosage=None,
        frequency="once",
        priority=priority or "P2",
        status="pending",
        ordered_by=requested_by,
        ordered_at=now,
        due_at=now + timedelta(minutes=30),
        requires_double_check=False,
        risk_hints=["AI生成请求", "需医生确认后执行"],
        audit_trail=[
            OrderExecutionTrail(
                action="request_created",
                actor=requested_by,
                note="AI助手已生成医嘱请求",
                created_at=now,
            )
        ],
    )
    MOCK_ORDERS_BY_PATIENT.setdefault(patient_id, []).insert(0, order)
    MOCK_ORDERS_BY_ID[order.id] = order
    return order.model_copy(deep=True)


