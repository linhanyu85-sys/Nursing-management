from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.config import settings


def _fallback_render(template_text: str, context: dict[str, Any], spoken_text: str, template_name: str | None) -> dict[str, Any]:
    diagnoses = "、".join(context.get("diagnoses", [])) or "待补充"
    risk_tags = "、".join(context.get("risk_tags", [])) or "暂无"
    pending_tasks = "、".join(context.get("pending_tasks", [])) or "暂无"

    replacements = {
        "{{patient_id}}": str(context.get("patient_id", "-")),
        "{{bed_no}}": str(context.get("bed_no", "-")),
        "{{diagnoses}}": diagnoses,
        "{{risk_tags}}": risk_tags,
        "{{pending_tasks}}": pending_tasks,
        "{{spoken_text}}": spoken_text,
    }

    rendered = template_text
    for key, value in replacements.items():
        rendered = rendered.replace(key, value)

    if spoken_text not in rendered:
        rendered = f"{rendered.rstrip()}\n记录补充：{spoken_text}"
    if "需人工复核" not in rendered:
        rendered = f"{rendered.rstrip()}\n\n[AI提示] 该草稿需人工复核后提交。"

    return {
        "draft_text": rendered,
        "structured_fields": {
            "template_name": template_name or "未命名模板",
            "template_applied": True,
            "render_mode": "fallback",
        },
    }


async def _openai_compatible_chat(
    *,
    base_url: str,
    model: str,
    prompt: dict[str, Any],
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
            {"role": "system", "content": "你是医疗文书助手。必须返回JSON对象。"},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
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


def _parse_draft_json(content: str | None) -> tuple[str, dict[str, Any]] | None:
    if not content:
        return None
    try:
        parsed = json.loads(content)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    draft_text = str(
        parsed.get("draft_text")
        or parsed.get("draf_text")
        or parsed.get("draft")
        or ""
    ).strip()
    if not draft_text:
        return None
    structured_fields = parsed.get("structured_fields", {})
    if not isinstance(structured_fields, dict):
        structured_fields = {}
    return draft_text, structured_fields


async def adapt_document_by_template(
    *,
    document_type: str,
    template_text: str,
    template_name: str | None,
    spoken_text: str,
    context: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    should_mock = settings.mock_mode and not settings.llm_force_enable
    if should_mock:
        fallback = _fallback_render(template_text, context, spoken_text, template_name)
        return fallback["draft_text"], fallback["structured_fields"]

    prompt = {
        "task": "护理文书模板自适应",
        "document_type": document_type,
        "template_name": template_name or "未命名模板",
        "template_text": template_text,
        "spoken_text": spoken_text,
        "patient_context": {
            "patient_id": context.get("patient_id"),
            "bed_no": context.get("bed_no"),
            "diagnoses": context.get("diagnoses", []),
            "risk_tags": context.get("risk_tags", []),
            "pending_tasks": context.get("pending_tasks", []),
        },
        "constraints": {
            "language": "zh-CN",
            "must_keep_template_structure": True,
            "must_append_manual_review_notice": True,
            "output_json_only": True,
        },
        "output_schema": {
            "draft_text": "string",
            "structured_fields": {
                "template_name": "string",
                "template_applied": True,
                "render_mode": "llm",
            },
        },
    }

    # 本地优先
    local_models = [settings.local_llm_model_primary, settings.local_llm_model_fallback]
    local_models = [m for m in local_models if m] if settings.local_llm_enabled else []
    per_model_timeout = max(6, int(settings.local_llm_timeout_sec / max(1, len(local_models)))) if local_models else 10
    for model in local_models:
        content = await _openai_compatible_chat(
            base_url=settings.local_llm_base_url,
            model=model,
            prompt=prompt,
            api_key=settings.local_llm_api_key,
            timeout_sec=per_model_timeout,
        )
        parsed = _parse_draft_json(content)
        if parsed:
            draft_text, structured_fields = parsed
        elif content:
            draft_text = content.strip()
            if draft_text in {"{}", "[]", '""', "null"} or len(draft_text) < 10:
                continue
            structured_fields = {}
        else:
            continue
        if "需人工复核" not in draft_text:
            draft_text = f"{draft_text.rstrip()}\n\n[AI提示] 该草稿需人工复核后提交。"
        structured_fields.setdefault("template_name", template_name or "未命名模板")
        structured_fields.setdefault("template_applied", True)
        structured_fields.setdefault("render_mode", "local_llm")
        return draft_text, structured_fields

    # 强制本地：不走云端
    if settings.local_only_mode:
        fallback = _fallback_render(template_text, context, spoken_text, template_name)
        fallback["draft_text"] = (
            "本地模型当前不可用，已禁止云端回退。\n"
            "请先启动本地模型服务后再生成。\n\n"
            f"{fallback['draft_text']}"
        )
        return fallback["draft_text"], fallback["structured_fields"]

    if settings.bailian_api_key:
        content = await _openai_compatible_chat(
            base_url=settings.bailian_base_url,
            model=settings.bailian_model_default,
            prompt=prompt,
            api_key=settings.bailian_api_key,
            timeout_sec=40,
        )
        parsed = _parse_draft_json(content)
        if parsed:
            draft_text, structured_fields = parsed
            if "需人工复核" not in draft_text:
                draft_text = f"{draft_text.rstrip()}\n\n[AI提示] 该草稿需人工复核后提交。"
            structured_fields.setdefault("template_name", template_name or "未命名模板")
            structured_fields.setdefault("template_applied", True)
            structured_fields.setdefault("render_mode", "llm")
            return draft_text, structured_fields

    fallback = _fallback_render(template_text, context, spoken_text, template_name)
    return fallback["draft_text"], fallback["structured_fields"]
