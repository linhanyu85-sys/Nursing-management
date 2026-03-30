from __future__ import annotations

import asyncio
import base64
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, File, UploadFile

from app.core.config import settings
from app.schemas.asr import TranscribeRequest, TranscribeResponse, VoiceUploadResponse
from app.services.local_asr import transcribe_audio_base64

router = APIRouter()
logger = logging.getLogger(__name__)

VOICE_CHUNKS: dict[str, str] = {}

LOW_QUALITY_MARKERS = (
    "语音转写失败",
    "未识别到语音",
    "未识别到清晰语音",
    "请重说",
    "请再说一遍",
    "手动输入",
    "无法听到您的话语",
)

LOW_SIGNAL_COMPACT_TEXTS = {
    "行不行",
    "可不可以",
    "可以吗",
    "能不能",
    "在吗",
    "你在吗",
    "听见吗",
    "听得到吗",
    "能听到吗",
}

DEVICE_SLEEP_COMMANDS = {
    "休眠",
    "进入休眠",
    "开始休眠",
    "请休眠",
    "小医休眠",
    "小智休眠",
    "sleep",
    "go sleep",
    "gosleep",
}

WAKE_WORD_FORMS = {
    "小医小医",
    "小医",
    "你好小医",
    "嗨小医",
    "嘿小医",
    "喂小医",
    "小依小依",
    "小依",
    "你好小依",
    "嗨小依",
    "小伊小伊",
    "小伊",
    "小一小一",
    "小一",
    "小衣小衣",
    "小衣",
    "小艺小艺",
    "小艺",
    "小宜小宜",
    "小宜",
    "小姨小姨",
    "小姨",
    "小智小智",
    "小智",
    "你好小智",
    "嗨小智",
    "xiaoyi",
    "xiaoyixiaoyi",
    "xiaoyi xiaoyi",
    "nihaoxiaoyi",
    "nihaoxiaoyixiaoyi",
    "xiaozhi",
    "xiaozhixiaozhi",
    "xiaozhi xiaozhi",
    "nihaoxiaozhi",
    "nihaoxiaozhixiaozhi",
}

CLINICAL_HINT_TOKENS = (
    "床",
    "号床",
    "床位",
    "病区",
    "患者",
    "病人",
    "护理",
    "交班",
    "文书",
    "草稿",
    "记录",
    "建议",
    "风险",
    "血压",
    "心率",
    "呼吸",
    "血氧",
    "尿量",
    "体温",
    "输液",
    "医生",
    "上报",
    "复核",
)

CN_DIGIT_MAP: dict[str, int] = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}

CN_UNIT_MAP: dict[str, int] = {
    "十": 10,
    "百": 100,
}

MOJIBAKE_MARKERS = (
    "鍖",
    "鐥",
    "鎶",
    "璇",
    "闂",
    "锟",
    "Ã",
)

_FUNASR_BACKOFF_UNTIL: datetime | None = None


def _normalize_text(text: str) -> str:
    return (text or "").strip()


def _repair_text(text: str) -> str:
    s = (text or "").strip()
    if not s:
        return ""

    if re.search(r"\\u[0-9a-fA-F]{4}", s):
        try:
            decoded = bytes(s, "utf-8").decode("unicode_escape")
            if decoded:
                s = decoded.strip()
        except Exception:
            pass

    candidates = [s]
    for src in ("latin1", "gbk"):
        try:
            recovered = s.encode(src, errors="ignore").decode("utf-8", errors="ignore").strip()
            if recovered:
                candidates.append(recovered)
        except Exception:
            continue

    def _score(value: str) -> tuple[int, int, int]:
        bad = sum(value.count(marker) for marker in MOJIBAKE_MARKERS)
        cjk = len(re.findall(r"[\u4e00-\u9fff]", value))
        return bad, -cjk, -len(value)

    best = min(candidates, key=_score)
    return best.strip()


def _compact_text(text: str) -> str:
    return re.sub(r"[\s,，。.!?？、；;:：~\-_=+（）()\[\]{}]+", "", (text or "").strip().lower())


def _is_wake_alias_text(text: str) -> bool:
    plain = _repair_text(text).strip()
    if not plain:
        return False
    compact = _compact_text(plain)
    if compact in WAKE_WORD_FORMS:
        return True
    cn_patterns = (
        r"^(?:你好|嗨|嘿|喂)?小[医依伊一衣艺易姨怡宜]小[医依伊一衣艺易姨怡宜]$",
        r"^(?:你好|嗨|嘿|喂)?小[医依伊一衣艺易姨怡宜]$",
    )
    return any(re.match(pattern, compact) for pattern in cn_patterns)


def _extract_device_action(text: str) -> str:
    plain = _repair_text(text).strip()
    if not plain:
        return ""
    if _is_wake_alias_text(plain):
        return "wake"
    compact = _compact_text(plain)
    if compact in DEVICE_SLEEP_COMMANDS:
        return "sleep"
    if compact.startswith(("休眠", "进入休眠", "请休眠", "小医休眠", "小智休眠", "sleep", "gosleep")):
        return "sleep"
    return ""


def _normalize_command_phrase(text: str) -> str:
    plain = _repair_text(text).strip()
    if not plain:
        return ""
    if _is_wake_alias_text(plain):
        return "小医小医"
    compact = _compact_text(plain)
    if re.search(r"(?:小[医依伊一衣艺易姨怡宜])?\s*(?:休眠|修眠|休明|待机|睡觉|gosleep|sleep)", compact):
        return "休眠"
    return plain


def _parse_cn_number(token: str) -> int | None:
    raw = (token or "").strip()
    if not raw:
        return None
    raw = raw.removeprefix("第")
    if not raw:
        return None
    if raw.isdigit():
        value = int(raw)
        return value if 1 <= value <= 199 else None
    if any(ch not in CN_DIGIT_MAP and ch not in CN_UNIT_MAP for ch in raw):
        return None
    if not any(ch in CN_UNIT_MAP for ch in raw):
        digits: list[str] = []
        for ch in raw:
            if ch not in CN_DIGIT_MAP:
                return None
            digits.append(str(CN_DIGIT_MAP[ch]))
        if not digits:
            return None
        value = int("".join(digits))
        return value if 1 <= value <= 199 else None

    total = 0
    current = 0
    for ch in raw:
        if ch in CN_DIGIT_MAP:
            current = CN_DIGIT_MAP[ch]
            continue
        unit = CN_UNIT_MAP.get(ch)
        if unit is None:
            return None
        if current == 0:
            current = 1
        total += current * unit
        current = 0
    total += current
    return total if 1 <= total <= 199 else None


def _has_bed_reference(text: str) -> bool:
    plain = _repair_text(text)
    if not plain:
        return False
    if re.search(r"(?<!\d)(\d{1,3})\s*(?:床|号床|床位)", plain):
        return True
    for match in re.finditer(r"(?:第)?([零〇一二两三四五六七八九十百]{1,5})\s*(?:床|号床|床位)", plain):
        if _parse_cn_number(match.group(1)) is not None:
            return True
    return False


def _is_clinical_hint(text: str) -> bool:
    plain = _repair_text(text)
    if not plain:
        return False
    if _has_bed_reference(plain):
        return True
    low = plain.lower()
    return any(token in plain or token in low for token in CLINICAL_HINT_TOKENS)


def _is_wake_only(text: str) -> bool:
    return _is_wake_alias_text(text)


def _is_low_signal_text(text: str) -> bool:
    plain = _repair_text(text).strip()
    if not plain:
        return True
    if _extract_device_action(plain):
        return False
    compact = _compact_text(plain)
    if compact in LOW_SIGNAL_COMPACT_TEXTS:
        return True
    if len(compact) <= 3 and not _is_clinical_hint(plain):
        return True
    return False


def _looks_like_bad_template(text: str) -> bool:
    t = _repair_text(text)
    if not t:
        return True
    if _extract_device_action(t):
        return False
    if _is_low_signal_text(t):
        return True
    if any(marker in t for marker in LOW_QUALITY_MARKERS):
        return True
    if re.search(r"[?？]{4,}", t):
        return True
    valid_chars = len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", t))
    return valid_chars < 2


def _funasr_available() -> bool:
    global _FUNASR_BACKOFF_UNTIL
    base = str(settings.funasr_base_url or "").strip()
    if not base:
        return False
    if settings.mock_mode:
        return False
    until = _FUNASR_BACKOFF_UNTIL
    if until and datetime.now(timezone.utc) < until:
        return False
    return True


def _mark_funasr_backoff(reason: str, cooldown_sec: int = 60) -> None:
    global _FUNASR_BACKOFF_UNTIL
    sec = max(int(cooldown_sec), 12)
    _FUNASR_BACKOFF_UNTIL = datetime.now(timezone.utc) + timedelta(seconds=sec)
    logger.warning("funasr_backoff sec=%s reason=%s", sec, reason)


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
        "local_asr_model_size": settings.local_asr_model_size,
    }


@router.post("/voice/upload", response_model=VoiceUploadResponse)
async def upload_voice(file: UploadFile = File(...)) -> VoiceUploadResponse:
    raw = await file.read()
    chunk_id = str(uuid.uuid4())
    VOICE_CHUNKS[chunk_id] = base64.b64encode(raw).decode("utf-8")
    return VoiceUploadResponse(chunk_id=chunk_id, received_at=datetime.now(timezone.utc))


@router.post("/asr/transcribe", response_model=TranscribeResponse)
async def transcribe(payload: TranscribeRequest) -> TranscribeResponse:
    audio_base64 = payload.audio_base64
    if not audio_base64 and payload.chunk_id:
        audio_base64 = VOICE_CHUNKS.get(payload.chunk_id)

    text_hint = _repair_text(_normalize_text(payload.text_hint or ""))
    if _looks_like_bad_template(text_hint):
        text_hint = ""

    async def _try_local_asr() -> TranscribeResponse | None:
        if (not audio_base64) or (not settings.local_asr_enabled):
            return None
        try:
            timeout_sec = max(min(int(settings.local_asr_timeout_sec or 8), 20), 2)
            text, confidence, provider = await asyncio.wait_for(
                asyncio.to_thread(transcribe_audio_base64, audio_base64, text_hint or None),
                timeout=timeout_sec,
            )
            fixed = _normalize_command_phrase(_normalize_text(text))
            if fixed and not _looks_like_bad_template(fixed):
                return TranscribeResponse(
                    text=fixed,
                    confidence=float(confidence or 0.78),
                    provider=provider,
                    created_at=datetime.now(timezone.utc),
                )
            logger.warning("local_asr_low_quality_result text=%s", fixed[:80])
        except asyncio.TimeoutError:
            logger.warning("local_asr_timeout timeout_sec=%s", settings.local_asr_timeout_sec)
        except Exception as exc:
            logger.warning("local_asr_failed: %s", exc)
        return None

    async def _try_funasr() -> TranscribeResponse | None:
        if not _funasr_available():
            return None
        if not audio_base64:
            return None
        request_json: dict[str, str] = {"audio_base64": audio_base64}
        if text_hint:
            request_json["text_hint"] = text_hint
        timeout = max(min(int(settings.funasr_timeout_sec or 8), 8), 2)
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=min(3, timeout)), trust_env=False) as client:
            try:
                response = await client.post(f"{settings.funasr_base_url}/transcribe", json=request_json)
                response.raise_for_status()
                body = response.json()
                fixed = _normalize_command_phrase(_normalize_text(str(body.get("text", ""))))
                if fixed and not _looks_like_bad_template(fixed):
                    return TranscribeResponse(
                        text=fixed,
                        confidence=float(body.get("confidence", 0.0) or 0.0),
                        provider="funasr",
                        created_at=datetime.now(timezone.utc),
                    )
                logger.warning("upstream_funasr_low_quality_result text=%s", fixed[:80])
            except Exception as exc:
                _mark_funasr_backoff(str(exc), cooldown_sec=max(20, timeout * 6))
                logger.warning("upstream_funasr_failed: %s", exc)
        return None

    priorities = ("local_first", "funasr_first")
    provider_priority = str(settings.asr_provider_priority or "local_first").strip().lower()
    if provider_priority not in priorities:
        provider_priority = "local_first"

    ordered_steps = (_try_funasr, _try_local_asr) if provider_priority == "funasr_first" else (_try_local_asr, _try_funasr)
    for step in ordered_steps:
        result = await step()
        if result is not None:
            return result

    if text_hint and _is_clinical_hint(text_hint):
        return TranscribeResponse(
            text=_normalize_command_phrase(text_hint),
            confidence=0.65,
            provider="text-hint",
            created_at=datetime.now(timezone.utc),
        )

    return TranscribeResponse(
        text="未识别到清晰语音，请再说一遍。",
        confidence=0.2 if not settings.mock_mode else 0.3,
        provider="mock-funasr" if settings.mock_mode else "fallback",
        created_at=datetime.now(timezone.utc),
    )
