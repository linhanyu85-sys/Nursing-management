from __future__ import annotations

from typing import Any

from app.services.llm_client import adapt_document_by_template


async def build_document_draft(
    *,
    document_type: str,
    spoken_text: str | None,
    context: dict[str, Any],
    template_text: str | None = None,
    template_name: str | None = None,
) -> tuple[str, dict[str, Any]]:
    diagnoses = "、".join(context.get("diagnoses", [])) or "待补充"
    risk_tags = "、".join(context.get("risk_tags", [])) or "暂无"
    pending_tasks = "、".join(context.get("pending_tasks", [])) or "暂无"
    spoken = spoken_text or "患者病情平稳，继续监测。"

    if template_text:
        draft_text, template_structured = await adapt_document_by_template(
            document_type=document_type,
            template_text=template_text,
            template_name=template_name,
            spoken_text=spoken,
            context=context,
        )
        structured_fields = {
            "diagnoses": context.get("diagnoses", []),
            "risk_tags": context.get("risk_tags", []),
            "pending_tasks": context.get("pending_tasks", []),
            "spoken_text": spoken_text,
            "template_name": template_name,
            "template_applied": True,
        }
        structured_fields.update(template_structured)
        return draft_text, structured_fields

    draft_text = (
        f"[{document_type}]\n"
        f"患者ID: {context.get('patient_id')} 床号: {context.get('bed_no', '-')}\n"
        f"主要诊断: {diagnoses}\n"
        f"风险标签: {risk_tags}\n"
        f"待处理任务: {pending_tasks}\n"
        f"护理记录: {spoken}\n"
        "AI提示: 该草稿需人工复核后提交。"
    )

    structured_fields = {
        "diagnoses": context.get("diagnoses", []),
        "risk_tags": context.get("risk_tags", []),
        "pending_tasks": context.get("pending_tasks", []),
        "spoken_text": spoken_text,
        "template_name": template_name,
        "template_applied": False,
    }
    return draft_text, structured_fields
