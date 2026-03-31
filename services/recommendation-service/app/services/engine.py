from __future__ import annotations

from typing import Any

from app.schemas.recommendation import RecommendationItem
from app.services.llm_client import ask_bailian_structured


DEGRADED_SUMMARY_MARKERS = (
    "本地模型当前不可用",
    "禁止云端回退",
    "云端模型未配置",
    "模型调用失败",
    "离线模拟上下文",
)


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

    if any(token in q for token in ("高钾", "钾", "电解质")):
        return (
            ["关注点：高钾及电解质紊乱风险"],
            [
                RecommendationItem(title="复测电解质并持续心电监护", priority=1, rationale="先确认高钾是否持续并观察心律变化"),
                RecommendationItem(title="核对含钾输液和相关用药", priority=1, rationale="先排查可纠正诱因"),
                RecommendationItem(title="通知医生评估降钾及进一步处置", priority=2, rationale="高钾可能快速进展为危急情况"),
            ],
        )

    if any(token in q for token in ("休克", "低灌注", "低血容量", "灌注")):
        return (
            ["关注点：循环灌注不足与休克风险"],
            [
                RecommendationItem(title="立即复测血压、脉搏、尿量和意识状态", priority=1, rationale="先确认休克是否持续及严重程度"),
                RecommendationItem(title="梳理出血/脱水/容量丢失线索并保留升级依据", priority=1, rationale="有助于快速定位诱因"),
                RecommendationItem(title="同步医生并准备升级处置", priority=2, rationale="持续低灌注需尽早进入更高等级处理"),
            ],
        )

    if any(token in q for token in ("出血", "恶露", "产后")):
        return (
            ["关注点：出血与循环波动风险"],
            [
                RecommendationItem(title="观察出血量或恶露颜色、量和变化趋势", priority=1, rationale="先判断是否存在继续失血"),
                RecommendationItem(title="复测心率、血压和血红蛋白趋势", priority=1, rationale="快速评估循环代偿情况"),
                RecommendationItem(title="通知医生评估再出血及进一步处理", priority=2, rationale="避免延误止血或升级处置"),
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


def _context_based_recommendations(context: dict[str, Any], question: str) -> list[RecommendationItem]:
    q = (question or "").strip().lower()
    observations = context.get("latest_observations", []) if isinstance(context.get("latest_observations"), list) else []
    risk_tags = [str(item).strip() for item in context.get("risk_tags", []) if str(item).strip()]
    pending_tasks = [str(item).strip() for item in context.get("pending_tasks", []) if str(item).strip()]

    recs: list[RecommendationItem] = []

    def add(title: str, priority: int, rationale: str) -> None:
        recs.append(RecommendationItem(title=title, priority=priority, rationale=rationale))

    abnormal_text = " ".join(
        [
            f"{str(obs.get('name') or '')} {str(obs.get('value') or '')} {str(obs.get('abnormal_flag') or '')}".lower()
            for obs in observations
            if isinstance(obs, dict)
        ]
    )
    risk_text = " ".join(risk_tags).lower()
    combined = f"{q} {abnormal_text} {risk_text}"

    if any(token in combined for token in ("休克", "低血容量", "低血压", "灌注", "shock")):
        add("立即复测血压、脉搏、尿量和意识状态", 1, "先确认循环灌注是否持续恶化")
        add("复核容量丢失线索并整理升级信息", 1, "便于快速完成医生沟通与升级")
        add("同步医生并准备升级处置", 2, "持续低灌注需尽早进入更高等级处理")

    if any(token in combined for token in ("高钾", "钾", "电解质")):
        add("复测电解质并持续心电监护", 1, "先确认高钾及节律风险")
        add("核对含钾输液和相关用药", 1, "先排查可纠正诱因")
        add("通知医生评估降钾及进一步处置", 2, "高钾可能快速进展为危急情况")

    if any(token in combined for token in ("出血", "恶露", "产后", "血红蛋白")):
        add("观察出血量或恶露颜色、量和变化趋势", 1, "先判断是否存在继续失血")
        add("复测心率、血压和血红蛋白趋势", 1, "评估循环代偿和失血影响")
        add("通知医生评估再出血及进一步处理", 2, "避免延误止血或升级处置")

    if any(token in combined for token in ("呼吸", "气促", "喘", "血氧", "spo2", "低氧")):
        add("连续监测呼吸频率和血氧饱和度", 1, "快速识别低氧风险")
        add("按医嘱调整氧疗并评估效果", 1, "及时纠正低氧趋势")
        add("呼吸困难加重立即通知医生", 2, "防止急性恶化")

    if any(token in combined for token in ("发热", "感染", "寒战", "体温")):
        add("复测体温并完善感染指标", 1, "确认发热持续性与严重程度")
        add("采样送检并执行抗感染医嘱", 1, "尽早明确病原并干预")
        add("观察循环/呼吸恶化并及时上报", 2, "警惕脓毒症进展")

    if not recs:
        for index, task in enumerate(pending_tasks[:4], start=1):
            add(
                f"执行并复核：{task}",
                1 if index <= 2 else 2,
                "来自当前病例的实时待处理任务",
            )

    if not recs:
        add("先复核生命体征与关键异常指标", 1, "建立当前风险基线")
        add("结合病情变化决定是否升级沟通", 2, "避免遗漏高风险信号")

    return recs


def _build_contextual_summary(
    context: dict[str, Any],
    question: str,
    findings: list[str],
    recommendations: list[RecommendationItem],
) -> str:
    bed_no = str(context.get("bed_no") or "-").strip()
    patient_name = str(context.get("patient_name") or "患者").strip()
    diagnoses = [str(item).strip() for item in context.get("diagnoses", [])[:2] if str(item).strip()]
    diagnosis_text = "、".join(diagnoses) if diagnoses else "当前诊断信息待补充"
    top_findings = "；".join(findings[:2]) if findings else "暂无关键异常指标"
    first_actions = "；".join(item.title for item in recommendations[:2]) if recommendations else "继续人工复核"
    if question:
        return (
            f"{bed_no}床{patient_name}围绕“{question}”当前更需要先关注：{diagnosis_text}。"
            f"已识别的重点信号为：{top_findings}。"
            f"建议下一步先做：{first_actions}。"
        )
    return (
        f"{bed_no}床{patient_name}当前重点为：{diagnosis_text}。"
        f"已识别信号：{top_findings}。"
        f"建议先做：{first_actions}。"
    )


def _llm_result_is_degraded(summary: str, context: dict[str, Any]) -> bool:
    text = (summary or "").strip()
    if not text:
        return True
    if any(marker in text for marker in DEGRADED_SUMMARY_MARKERS):
        return True
    if "当前为离线模拟上下文" in " ".join(str(item) for item in context.get("diagnoses", [])):
        return True
    return False


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
    heuristic_recommendations = _merge_recommendations(
        focus_recommendations,
        _context_based_recommendations(context, question),
    )
    heuristic_findings = focus_findings + [item for item in findings if item not in focus_findings]
    heuristic_summary = _build_contextual_summary(context, question, heuristic_findings, heuristic_recommendations)
    if fast_mode:
        merged_findings = heuristic_findings
        quick_recommendations = heuristic_recommendations or [
            RecommendationItem(title="立即复测生命体征并复核趋势", priority=1, rationale="快速确认风险是否持续"),
            RecommendationItem(title="同步医生评估并准备升级处置", priority=1, rationale="避免处置延迟"),
        ]
        return (
            heuristic_summary or _build_fast_summary(context, question, merged_findings),
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

    summary = str(llm.get("summary", "")).strip() or heuristic_summary
    degraded = _llm_result_is_degraded(summary, context)
    if degraded:
        summary = heuristic_summary

    llm_findings = llm.get("findings", findings)
    if not isinstance(llm_findings, list):
        llm_findings = findings
    llm_findings = [str(item) for item in llm_findings]
    if degraded:
        llm_findings = heuristic_findings

    recommendations = _normalize_recommendations(llm.get("recommendations", []))
    if degraded:
        recommendations = heuristic_recommendations

    if focus_findings:
        llm_findings = focus_findings + [item for item in llm_findings if item not in focus_findings]
    if focus_recommendations:
        recommendations = _merge_recommendations(focus_recommendations, recommendations)

    confidence = float(llm.get("confidence", 0.7))
    confidence = max(0.0, min(1.0, confidence))
    if degraded:
        confidence = max(confidence, 0.72)

    escalation_rules = llm.get("escalation_rules", [])
    if not isinstance(escalation_rules, list):
        escalation_rules = []
    if degraded and not escalation_rules:
        escalation_rules = ["生命体征持续恶化超过30分钟", "出现意识改变或呼吸困难", "关键指标触发危急值"]

    review_required = bool(llm.get("review_required", True))
    return summary, llm_findings, recommendations, confidence, escalation_rules, review_required
