from __future__ import annotations

from typing import Any

from app.schemas.recommendation import RecommendationItem
from app.services.llm_client import ask_bailian_structured


def _collect_findings(context: dict[str, Any], multimodal: dict[str, Any] | None) -> list[str]:
    findings: list[str] = []
    flag_label = {
        "low": "偏低",
        "high": "偏高",
        "critical": "危急",
        "normal": "正常",
    }

    for obs in context.get("latest_observations", [])[:4]:
        label = obs.get("name", "未知指标")
        value = obs.get("value", "-")
        flag = obs.get("abnormal_flag", "normal")
        findings.append(f"{label}: {value} ({flag_label.get(str(flag).lower(), str(flag))})")

    findings.extend(context.get("risk_tags", []))
    findings.extend(context.get("pending_tasks", []))

    if multimodal:
        mm_findings = multimodal.get("findings", [])
        if isinstance(mm_findings, list):
            findings.extend([str(item) for item in mm_findings])

    # 去重并保持顺序
    deduped: list[str] = []
    seen: set[str] = set()
    for item in findings:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _normalize_recommendations(items: list[dict[str, Any]]) -> list[RecommendationItem]:
    normalized: list[RecommendationItem] = []
    for item in items:
        title = str(item.get("title", "")).strip()
        if not title:
            continue

        priority = int(item.get("priority", 2))
        priority = max(1, min(3, priority))
        rationale = item.get("rationale")
        normalized.append(RecommendationItem(title=title, priority=priority, rationale=rationale))

    if not normalized:
        normalized = [
            RecommendationItem(title="立即复测生命体征", priority=1, rationale="先稳定再判断"),
            RecommendationItem(title="同步医生复核风险变化", priority=1, rationale="避免延迟升级"),
        ]
    return normalized


def _question_focus(question: str) -> tuple[list[str], list[RecommendationItem]]:
    q = (question or "").strip()
    if not q:
        return [], []

    if any(token in q for token in ("尿", "少尿", "排尿", "导尿")):
        return (
            ["关注点：尿量变化与导尿通畅情况"],
            [
                RecommendationItem(title="每小时记录尿量并评估导尿管通畅", priority=1, rationale="先排查机械性梗阻"),
                RecommendationItem(title="复测血压与脉搏，评估肾灌注", priority=1, rationale="少尿常提示灌注不足"),
                RecommendationItem(title="通知医生评估补液/升压策略", priority=2, rationale="达到升级阈值时及时处理"),
            ],
        )

    if any(token in q for token in ("发热", "体温", "感染", "寒战")):
        return (
            ["关注点：发热相关感染风险"],
            [
                RecommendationItem(title="复测体温并完善感染指标", priority=1, rationale="确认发热持续性与严重程度"),
                RecommendationItem(title="采样送检并执行抗感染医嘱", priority=1, rationale="尽早明确病原并干预"),
                RecommendationItem(title="观察循环/呼吸恶化并及时上报", priority=2, rationale="警惕脓毒症进展"),
            ],
        )

    if any(token in q for token in ("疼", "痛")):
        return (
            ["关注点：疼痛分级与并发症风险"],
            [
                RecommendationItem(title="评估疼痛评分与部位性质", priority=1, rationale="明确趋势与诱因"),
                RecommendationItem(title="执行镇痛医嘱并监测不良反应", priority=1, rationale="兼顾疗效与安全"),
                RecommendationItem(title="疼痛持续加重时升级评估", priority=2, rationale="排查急性并发症"),
            ],
        )

    if any(token in q for token in ("呼吸", "气促", "喘", "血氧", "SpO2", "氧")):
        return (
            ["关注点：呼吸循环稳定性"],
            [
                RecommendationItem(title="连续监测呼吸频率和血氧饱和度", priority=1, rationale="快速识别低氧风险"),
                RecommendationItem(title="按医嘱调整氧疗并评估效果", priority=1, rationale="维持目标氧合"),
                RecommendationItem(title="呼吸困难加重立即通知医生", priority=2, rationale="防止急性恶化"),
            ],
        )

    return [], []


def _merge_recommendations(primary: list[RecommendationItem], secondary: list[RecommendationItem]) -> list[RecommendationItem]:
    merged: list[RecommendationItem] = []
    seen: set[str] = set()

    for item in primary + secondary:
        key = item.title.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(item)

    return merged


def _build_fast_summary(context: dict[str, Any], question: str, findings: list[str]) -> str:
    bed_no = str(context.get("bed_no") or "-").strip()
    patient_name = str(context.get("patient_name") or "患者").strip()
    diagnoses = [str(item).strip() for item in context.get("diagnoses", [])[:2] if str(item).strip()]
    diagnosis_text = "、".join(diagnoses) if diagnoses else "暂无明确诊断信息"
    top_finding = findings[0] if findings else "暂无关键异常指标"
    if question:
        return f"{bed_no}床{patient_name}当前重点：{diagnosis_text}；首要异常：{top_finding}。建议先执行高优先级处置并持续复核。"
    return f"{bed_no}床{patient_name}当前重点：{diagnosis_text}；首要异常：{top_finding}。"


async def generate_recommendation(
    question: str,
    context: dict[str, Any],
    multimodal: dict[str, Any] | None,
    attachments: list[str],
    llm_question: str | None = None,
    fast_mode: bool = False,
) -> tuple[str, list[str], list[RecommendationItem], float, list[str], bool]:
    findings = _collect_findings(context, multimodal)
    focus_findings, focus_recommendations = _question_focus(question)
    if fast_mode:
        merged_findings = focus_findings + [item for item in findings if item not in focus_findings]
        quick_recommendations = focus_recommendations or [
            RecommendationItem(title="立即复测生命体征并复核趋势", priority=1, rationale="快速确认风险是否持续"),
            RecommendationItem(title="同步医生评估并准备升级处置", priority=1, rationale="避免处置延迟"),
        ]
        return (
            _build_fast_summary(context, question, merged_findings),
            merged_findings[:10],
            quick_recommendations[:5],
            0.74,
            ["生命体征持续恶化超过30分钟", "出现意识改变或呼吸困难", "关键指标触发危急值"],
            True,
        )

    ask_question = (llm_question or question or "").strip()
    llm = await ask_bailian_structured(
        question=ask_question,
        context=context,
        findings=findings,
        attachments=attachments,
    )

    summary = str(llm.get("summary", "")).strip() or f"已收到问题：{question}。请人工复核后执行。"

    llm_findings = llm.get("findings", findings)
    if not isinstance(llm_findings, list):
        llm_findings = findings
    llm_findings = [str(item) for item in llm_findings]

    recommendations = _normalize_recommendations(llm.get("recommendations", []))

    if focus_findings:
        llm_findings = focus_findings + [item for item in llm_findings if item not in focus_findings]
    if focus_recommendations:
        recommendations = _merge_recommendations(focus_recommendations, recommendations)

    confidence = float(llm.get("confidence", 0.7))
    confidence = max(0.0, min(1.0, confidence))

    escalation_rules = llm.get("escalation_rules", [])
    if not isinstance(escalation_rules, list):
        escalation_rules = []

    review_required = bool(llm.get("review_required", True))
    return summary, llm_findings, recommendations, confidence, escalation_rules, review_required
