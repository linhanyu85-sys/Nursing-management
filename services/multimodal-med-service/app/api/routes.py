from datetime import datetime, timezone
import json

import httpx
from fastapi import APIRouter

from app.core.config import settings
from app.schemas.multimodal import AnalyzeRequest, AnalyzeResponse

router = APIRouter()


def _compact_ref(ref: str, index: int) -> str:
    if ref.startswith("data:"):
        mime = ref.split(";", 1)[0].replace("data:", "") or "unknown"
        return f"附件{index}({mime})"
    if ref.startswith("http://") or ref.startswith("https://"):
        return f"附件{index}(url)"
    text = ref if len(ref) <= 50 else f"{ref[:47]}..."
    return f"附件{index}({text})"


def _mock_analysis(payload: AnalyzeRequest) -> AnalyzeResponse:
    refs = [_compact_ref(item, idx) for idx, item in enumerate(payload.input_refs, start=1)]
    return AnalyzeResponse(
        patient_id=payload.patient_id,
        summary=f"已接收{len(payload.input_refs)}个多模态附件，建议结合临床数据进行人工复核。",
        findings=refs,
        recommendations=[
            {"title": "优先核对生命体征与检验变化", "priority": 1},
            {"title": "将关键风险同步到交班记录", "priority": 2},
        ],
        confidence=0.77,
        review_required=True,
        created_at=datetime.now(timezone.utc),
    )


async def _bailian_multimodal(payload: AnalyzeRequest) -> AnalyzeResponse | None:
    if not settings.bailian_api_key:
        return None

    content: list[dict] = [
        {
            "type": "text",
            "text": (
                "你是临床护理多模态分析助手。"
                "请仅返回JSON对象，字段包含：summary, findings, recommendations, confidence, review_required。"
                f"患者ID: {payload.patient_id}。问题: {payload.question or '请总结当前病情重点'}。"
            ),
        }
    ]

    for idx, item in enumerate(payload.input_refs[:4], start=1):
        if item.startswith("data:image/"):
            content.append({"type": "image_url", "image_url": {"url": item}})
        elif item.startswith("http://") or item.startswith("https://"):
            content.append({"type": "image_url", "image_url": {"url": item}})
        else:
            content.append({"type": "text", "text": f"附件引用：{_compact_ref(item, idx)}"})

    request_json = {
        "model": settings.bailian_multimodal_model,
        "messages": [
            {"role": "system", "content": "请输出中文JSON，不要输出markdown。"},
            {"role": "user", "content": content},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }

    headers = {
        "Authorization": f"Bearer {settings.bailian_api_key}",
        "Content-Type": "application/json",
    }
    endpoint = f"{settings.bailian_base_url}/chat/completions"

    async with httpx.AsyncClient(timeout=45, trust_env=False) as client:
        try:
            response = await client.post(endpoint, headers=headers, json=request_json)
            response.raise_for_status()
            body = response.json()
            content_text = body["choices"][0]["message"]["content"]
            parsed = json.loads(content_text)
        except Exception:
            return None

    summary = str(parsed.get("summary", "")).strip() or f"已完成附件分析，共{len(payload.input_refs)}个附件。"

    findings = parsed.get("findings", [])
    if not isinstance(findings, list):
        findings = []

    recommendations = parsed.get("recommendations", [])
    if not isinstance(recommendations, list):
        recommendations = []

    confidence = parsed.get("confidence", 0.75)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.75
    confidence = max(0.0, min(1.0, confidence))

    review_required = bool(parsed.get("review_required", True))

    return AnalyzeResponse(
        patient_id=payload.patient_id,
        summary=summary,
        findings=[str(item) for item in findings][:12],
        recommendations=recommendations[:8],
        confidence=confidence,
        review_required=review_required,
        created_at=datetime.now(timezone.utc),
    )


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": settings.service_name}


@router.get("/ready")
def ready() -> dict:
    return {"status": "ready", "service": settings.service_name}


@router.get("/version")
def version() -> dict:
    return {
        "service": settings.service_name,
        "version": settings.app_version,
        "env": settings.app_env,
        "mock_mode": settings.mock_mode,
    }


@router.post("/multimodal/analyze", response_model=AnalyzeResponse)
async def analyze(payload: AnalyzeRequest) -> AnalyzeResponse:
    should_mock = settings.mock_mode and not settings.llm_force_enable
    if should_mock:
        return _mock_analysis(payload)

    bailian_result = await _bailian_multimodal(payload)
    if bailian_result is not None:
        return bailian_result

    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        try:
            response = await client.post(f"{settings.medgemma_base_url}/analyze", json=payload.model_dump())
            response.raise_for_status()
            body = response.json()
            return AnalyzeResponse(
                patient_id=payload.patient_id,
                summary=body.get("summary", ""),
                findings=body.get("findings", []),
                recommendations=body.get("recommendations", []),
                confidence=float(body.get("confidence", 0.0)),
                review_required=bool(body.get("review_required", True)),
                created_at=datetime.now(timezone.utc),
            )
        except Exception:
            return _mock_analysis(payload)
