from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.config import settings


DEFAULT_ESCALATION_RULES = [
    "生命体征持续恶化超过30分钟",
    "出现意识改变、持续低灌注或呼吸困难",
    "关键指标触发危急值",
]
SYSTEM_PROMPT = "你是临床护理推荐助手。输出中文、简洁、可执行。"


def _keyword_plan(question: str) -> list[dict[str, Any]]:
    q = (question or "").strip().lower()

    # 通用兜底
    plan = [
        {"title": "立即复测血压并复核趋势", "priority": 1, "rationale": "优先确认灌注状态"},
        {"title": "记录尿量并评估液体管理", "priority": 1, "rationale": "持续评估肾灌注风险"},
        {"title": "通知医生复核并准备升级评估", "priority": 2, "rationale": "达到升级阈值时及时处理"},
    ]

    if any(token in q for token in ("尿", "少尿", "排尿", "导尿")):
        plan = [
            {"title": "每小时记录尿量并检查导尿管通畅", "priority": 1, "rationale": "先排除机械性梗阻"},
            {"title": "复测血压与脉搏并评估循环灌注", "priority": 1, "rationale": "少尿常见于低灌注"},
            {"title": "通知医生评估补液/升压策略", "priority": 2, "rationale": "必要时升级处理"},
        ]
    elif any(token in q for token in ("发热", "体温", "感染", "寒战")):
        plan = [
            {"title": "复测体温并完善感染评估", "priority": 1, "rationale": "确认发热持续性与严重程度"},
            {"title": "按医嘱采样送检并执行抗感染策略", "priority": 1, "rationale": "尽早明确病原与干预"},
            {"title": "监测循环/呼吸恶化并及时上报", "priority": 2, "rationale": "警惕脓毒症进展"},
        ]
    elif any(token in q for token in ("疼", "痛")):
        plan = [
            {"title": "评估疼痛评分与部位性质", "priority": 1, "rationale": "明确疼痛变化趋势"},
            {"title": "执行镇痛医嘱并观察不良反应", "priority": 1, "rationale": "兼顾疗效与安全"},
            {"title": "疼痛加重或伴异常体征时升级评估", "priority": 2, "rationale": "排查急性并发症"},
        ]
    elif any(token in q for token in ("呼吸", "气促", "喘", "血氧", "spo2", "氧")):
        plan = [
            {"title": "持续监测呼吸频率与血氧饱和度", "priority": 1, "rationale": "快速识别低氧风险"},
            {"title": "按医嘱调整氧疗并评估效果", "priority": 1, "rationale": "维持目标氧合"},
            {"title": "呼吸困难加重时立即通知医生", "priority": 2, "rationale": "预防急性恶化"},
        ]

    return plan


def _fallback_payload(question: str, findings: list[str]) -> dict[str, Any]:
    recs = _keyword_plan(question)
    return {
        "summary": f"已收到问题：{question}。建议先执行高优先级护理动作，并保留人工复核。",
        "findings": findings,
        "recommendations": recs,
        "confidence": 0.78,
        "escalation_rules": DEFAULT_ESCALATION_RULES,
        "review_required": True,
    }


async def _openai_compatible_chat(
    *,
    base_url: str,
    model: str,
    prompt: str,
    api_key: str = "",
    timeout_sec: int = 30,
) -> str | None:
    endpoint = f"{base_url.rstrip('/')}/chat/completions"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    async with httpx.AsyncClient(timeout=timeout_sec, trust_env=False) as client:
        try:
            response = await client.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()
            content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
            result = str(content).strip()
            return result or None
        except Exception:
            return None


def _build_structured_prompt(
    *,
    question: str,
    context: dict[str, Any],
    findings: list[str],
    attachments: list[str],
) -> str:
    compact_context = {
        "patient_id": context.get("patient_id"),
        "bed_no": context.get("bed_no"),
        "department_id": context.get("department_id"),
        "patient_name": context.get("patient_name"),
        "diagnoses": (context.get("diagnoses") or [])[:4],
        "risk_tags": (context.get("risk_tags") or [])[:6],
        "pending_tasks": (context.get("pending_tasks") or [])[:6],
        "latest_observations": (context.get("latest_observations") or [])[:8],
        "recent_handover_summary": str(context.get("latest_handover_summary") or "")[:220],
        "document_status": str(context.get("latest_document_status") or "")[:120],
    }
    prompt = {
        "task": "生成临床护理推荐",
        "rules": {
            "language": "zh-CN",
            "must_include_review_required": True,
            "output_json_only": True,
        },
        "question": question,
        "context": compact_context,
        "findings": findings[:10],
        "attachments": attachments,
        "target_schema": {
            "summary": "string",
            "findings": ["string"],
            "recommendations": [{"title": "string", "priority": 1, "rationale": "string"}],
            "confidence": 0.0,
            "escalation_rules": ["string"],
            "review_required": True,
        },
    }
    return json.dumps(prompt, ensure_ascii=False)


def _parse_structured_or_none(content: str | None) -> dict[str, Any] | None:
    if not content:
        return None
    try:
        parsed = json.loads(content)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    if not parsed.get("summary"):
        return None
    return parsed


def _normalize_result(parsed: dict[str, Any], question: str, findings: list[str]) -> dict[str, Any]:
    recs = parsed.get("recommendations")
    if not isinstance(recs, list):
        # 容错常见拼写问题
        recs = parsed.get("recommendaations")
    if not isinstance(recs, list):
        recs = _keyword_plan(question)

    conf = parsed.get("confidence", 0.68)
    try:
        conf = float(conf)
    except Exception:
        conf = 0.68
    conf = max(0.0, min(1.0, conf))
    if conf < 0.01:
        conf = 0.68

    escalation_rules = parsed.get("escalation_rules")
    if not isinstance(escalation_rules, list):
        escalation_rules = parsed.get("escaltion_rules")
    if not isinstance(escalation_rules, list):
        escalation_rules = DEFAULT_ESCALATION_RULES

    out_findings = parsed.get("findings")
    if not isinstance(out_findings, list):
        out_findings = findings[:8]

    return {
        "summary": str(parsed.get("summary", "")).strip(),
        "findings": [str(x) for x in out_findings],
        "recommendations": recs,
        "confidence": conf,
        "escalation_rules": [str(x) for x in escalation_rules],
        "review_required": bool(parsed.get("review_required", True)),
    }


async def _local_structured(
    *,
    question: str,
    context: dict[str, Any],
    findings: list[str],
    attachments: list[str],
) -> dict[str, Any] | None:
    if not settings.local_llm_enabled:
        return None
    if settings.mock_mode and not settings.llm_force_enable:
        return None

    prompt = _build_structured_prompt(
        question=question,
        context=context,
        findings=findings,
        attachments=attachments,
    )
    models = [settings.local_llm_model_primary, settings.local_llm_model_fallback]
    models = [m for m in models if m]
    if not models:
        return None

    per_model_timeout = max(6, int(settings.local_llm_timeout_sec / max(1, len(models))))
    for model in models:
        content = await _openai_compatible_chat(
            base_url=settings.local_llm_base_url,
            model=model,
            prompt=prompt,
            api_key=settings.local_llm_api_key,
            timeout_sec=per_model_timeout,
        )
        parsed = _parse_structured_or_none(content)
        if parsed:
            return _normalize_result(parsed, question, findings)
        # 本地小模型经常返回纯文本，这里做容错封装，仍按结构化结果返回。
        if content:
            summary = content.strip()
            if len(summary) > 520:
                summary = summary[:520]
            return {
                "summary": summary,
                "findings": findings[:8],
                "recommendations": _keyword_plan(question),
                "confidence": 0.66,
                "escalation_rules": DEFAULT_ESCALATION_RULES,
                "review_required": True,
            }
    return None


async def ask_bailian_structured(
    *,
    question: str,
    context: dict[str, Any],
    findings: list[str],
    attachments: list[str],
) -> dict[str, Any]:
    should_mock = settings.mock_mode and not settings.llm_force_enable
    if should_mock:
        return _fallback_payload(question, findings)

    local_parsed = await _local_structured(
        question=question,
        context=context,
        findings=findings,
        attachments=attachments,
    )
    if local_parsed:
        return local_parsed

    if settings.local_only_mode:
        fallback = _fallback_payload(question, findings)
        fallback["summary"] = "本地模型当前不可用，已禁止云端回退。请先启动本地模型服务后重试。"
        return fallback

    if not settings.bailian_api_key:
        return _fallback_payload(question, findings)

    content = await _openai_compatible_chat(
        base_url=settings.bailian_base_url,
        model=settings.bailian_model_default,
        prompt=_build_structured_prompt(
            question=question,
            context=context,
            findings=findings,
            attachments=attachments,
        ),
        api_key=settings.bailian_api_key,
        timeout_sec=40,
    )
    parsed = _parse_structured_or_none(content)
    if not parsed:
        return _fallback_payload(question, findings)
    return _normalize_result(parsed, question, findings)
