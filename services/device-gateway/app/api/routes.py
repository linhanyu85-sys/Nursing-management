from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
from typing import Any
import wave
from urllib.parse import unquote, urlparse

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from starlette.websockets import WebSocketState

from app.core.config import settings

try:
    import av  # type: ignore
except Exception:  # pragma: no cover
    av = None  # type: ignore[assignment]

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None  # type: ignore[assignment]

router = APIRouter()
logger = logging.getLogger(__name__)

LOW_SIGNAL_COMPACT_TEXTS = {
    "行不行",
    "可以吗",
    "可不可以",
    "能不能",
    "在吗",
    "你在吗",
    "听见吗",
    "听得到吗",
    "能听到吗",
    "好吗",
    "好不好",
    "是吗",
    "对吗",
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

DEVICE_SLEEP_COMMANDS = {
    "休眠",
    "进入休眠",
    "开始休眠",
    "请休眠",
    "小医休眠",
    "小智休眠",
    "小依休眠",
    "小姨休眠",
    "修眠",
    "休明",
    "睡觉",
    "关闭对话",
    "结束对话",
    "闭嘴",
    "别说了",
    "睡眠模式",
    "待机",
    "进入待机",
    "结束会话",
    "停止聆听",
    "停止监听",
    "停止听",
    "goodbye",
    "sleep",
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

FOLLOWUP_HINTS = {
    "然后呢",
    "接下来呢",
    "那怎么办",
    "怎么办",
    "下一步",
    "继续",
    "继续说",
    "再具体点",
    "再详细点",
    "需要上报吗",
    "要不要上报",
}

NOISE_BROADCAST_TOKENS = (
    "点赞",
    "订阅",
    "转发",
    "打赏",
    "明镜",
    "栏目",
    "关注",
    "下期",
)

ASR_PROMPT_ECHO_TOKENS = (
    "床号",
    "号床",
    "病区",
    "护理",
    "护理记录",
    "尿量",
    "血压",
    "心率",
    "呼吸",
    "体温",
    "血氧",
    "值班医生",
    "责任医生",
    "建议",
    "上报",
)

MOJIBAKE_MARKERS = (
    "鍖",
    "鐥",
    "鎶",
    "璇",
    "闂",
    "锟",
    "Ã",
    "�",
    "?",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _utc_now().isoformat()


def _timezone_offset_minutes() -> int:
    offset = datetime.now().astimezone().utcoffset()
    if offset is None:
        return 0
    return int(offset.total_seconds() // 60)


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
    # Fix UTF-8 text accidentally decoded as latin1 (e.g. "éå¸¸æ±æ­")
    if (not re.search(r"[\u4e00-\u9fff]", s)) and re.search(r"[ÃÂåæçèéêìíîïðñòóôõöøùúûüýþÿ]", s):
        try:
            fixed = s.encode("latin1", errors="ignore").decode("utf-8", errors="ignore").strip()
            if fixed:
                s = fixed
        except Exception:
            pass
    bad_markers = ("鎴", "璇", "鍖", "鏈", "妯", "锛", "銆", "闂", "鍙", "绯", "鏂", "鎵")
    bad_score = sum(s.count(m) for m in bad_markers) + s.count("�")
    if bad_score >= 2:
        candidates = [s]
        try:
            candidates.append(s.encode("gbk", errors="ignore").decode("utf-8", errors="ignore").strip())
        except Exception:
            pass
        try:
            candidates.append(s.encode("latin1", errors="ignore").decode("utf-8", errors="ignore").strip())
        except Exception:
            pass

        def _score(value: str) -> tuple[int, int]:
            bad = sum(value.count(m) for m in bad_markers) + value.count("�")
            cjk = len(re.findall(r"[\u4e00-\u9fff]", value))
            return (bad, -cjk)

        candidates = [c for c in candidates if c]
        if candidates:
            s = min(candidates, key=_score)
    return s


def _split_tts_sentences(text: str) -> list[str]:
    plain = _repair_text(text)
    if not plain:
        return []
    chunks = re.split(r"(?<=[.!?;。！？；])\s*", plain)
    normalized = [chunk.strip() for chunk in chunks if chunk.strip()]
    return normalized or [plain]


def _parse_chinese_number_token(token: str) -> int | None:
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


def _parse_bed_no_value(raw: str) -> str | None:
    value = _parse_chinese_number_token(raw)
    if value is None:
        return None
    return str(value)


def _extract_bed_candidates(text: str) -> list[str]:
    plain = _repair_text(text)
    if not plain:
        return []
    out: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        value = _parse_bed_no_value(raw)
        if not value or value in seen:
            return
        seen.add(value)
        out.append(value)

    for pattern in (
        r"(?<!\d)(\d{1,3})\s*(?:床|号床|床位|搴|号搴|搴位)",
        r"\bbed\s*(\d{1,3})\b",
        r"\b(\d{1,3})\s*bed\b",
    ):
        for match in re.finditer(pattern, plain, flags=re.IGNORECASE):
            add(match.group(1))

    for match in re.finditer(r"(?:第)?([零〇一二两三四五六七八九十百]{1,5})\s*(?:床|号床|床位|搴|号搴|搴位)", plain):
        add(match.group(1))

    if not out:
        has_context_signal = any(
            token in plain
            for token in (
                "看",
                "患者",
                "病人",
                "病区",
                "情况",
                "护理",
                "交班",
                "文书",
                "草稿",
                "记录",
                "建议",
            )
        )
        if has_context_signal or _looks_like_mojibake(plain):
            for match in re.finditer(r"(?<!\d)(\d{1,3})(?!\d)", plain):
                add(match.group(1))
    return out


def _extract_bed_no(text: str) -> str | None:
    candidates = _extract_bed_candidates(text)
    return candidates[0] if candidates else None


def _compact_text(text: str) -> str:
    return re.sub(r"[\s,，。.!！?？:：;；、~～\-_=+（）()\[\]{}]+", "", (text or "").strip().lower())


def _strip_leading_wake_words(text: str) -> str:
    plain = _repair_text(text).strip()
    if not plain:
        return ""
    if _is_wake_alias_text(plain):
        return ""

    wake_prefix_pattern = re.compile(
        r"^(?:你好|嗨|嘿|喂)?\s*小[医依伊一衣艺易姨怡宜](?:\s*小[医依伊一衣艺易姨怡宜])?\s*[,，。.!！?？:：;；\s]+"
    )
    stripped = plain
    for _ in range(2):
        updated = wake_prefix_pattern.sub("", stripped, count=1).strip()
        if updated == stripped:
            break
        stripped = updated
    return stripped


def _strip_question_echo(text: str) -> str:
    plain = _repair_text(text).strip()
    if not plain:
        return ""
    # Avoid repeating "当前提问：..." in TTS, which increases latency and sounds like context drift.
    cleaned = re.sub(r"(?:\n|\r|\s)*(?:当前提问|本次提问|提问内容)\s*[:：].*$", "", plain, flags=re.IGNORECASE | re.DOTALL)
    return cleaned.strip() or plain


def _looks_like_mojibake(text: str) -> bool:
    plain = (text or "").strip()
    if not plain:
        return False
    score = sum(plain.count(marker) for marker in MOJIBAKE_MARKERS)
    return score >= 2


def _is_followup_query(text: str) -> bool:
    plain = _repair_text(text).strip()
    if not plain:
        return False
    compact = _compact_text(plain)
    if compact in FOLLOWUP_HINTS:
        return True
    if compact.startswith(("然后", "接下来", "那怎么办")) and len(compact) <= 10:
        return True
    return False


def _should_reuse_recent_context(text: str, mode: str) -> bool:
    plain = _repair_text(text).strip()
    if not plain:
        return False
    if _extract_bed_no(plain):
        return False
    if _is_followup_query(plain):
        return True
    # Keep context reuse conservative to avoid stale patient carry-over.
    if any(token in plain for token in ("这个患者", "该患者", "这个病人", "这位患者", "这一床", "这床", "这个床位", "刚才那位患者", "上一位患者")):
        return True
    normalized_mode = (mode or "").strip().lower()
    if normalized_mode in {"document", "handover", "escalation", "collaboration"} and any(
        token in plain for token in ("这个患者", "该患者", "这个病人", "这位患者", "这床", "这一床")
    ):
        if any(token in plain for token in ("文书", "草稿", "交班", "建议", "上报", "优先级", "协作")):
            return True
    return False


def _is_noise_broadcast_text(text: str) -> bool:
    plain = _repair_text(text).strip()
    if not plain:
        return False
    if _extract_bed_no(plain):
        return False
    return all(token in plain for token in ("点赞", "订阅", "转发")) or any(token in plain for token in NOISE_BROADCAST_TOKENS)


def _is_prompt_echo_text(text: str) -> bool:
    plain = _repair_text(text).strip()
    if not plain:
        return False
    if _extract_bed_no(plain):
        return False
    hits = sum(1 for token in ASR_PROMPT_ECHO_TOKENS if token in plain)
    return hits >= 6


def _normalize_user_id(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return "u_linmeili"
    if raw.startswith("u_"):
        return raw
    return f"u_{raw}"


def _is_wake_alias_text(text: str) -> bool:
    plain = _repair_text(text).strip()
    if not plain:
        return False
    compact = re.sub(r"[\s,，。.!！?？:：;；~～\-_=+（）()\[\]{}]+", "", plain.lower())
    if compact in WAKE_WORD_FORMS:
        return True
    # Handle common near-homophone recognition in Chinese ASR.
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

    if compact.startswith(
        (
            "休眠",
            "进入休眠",
            "请休眠",
            "小医休眠",
            "小智休眠",
            "小依休眠",
            "小姨休眠",
            "修眠",
            "休明",
            "sleep",
            "gosleep",
        )
    ):
        if _extract_bed_no(plain):
            return ""
        if any(token in plain for token in ("睡眠质量", "睡眠情况", "睡眠监测")):
            return ""
        return "sleep"
    if re.search(r"(?:小[医依伊一衣艺易姨怡宜])?\s*(?:休眠|修眠|休明|待机|睡觉)", compact):
        if _extract_bed_no(plain):
            return ""
        return "sleep"
    return ""


def _is_clinical_hint(text: str) -> bool:
    plain = _repair_text(text)
    if not plain:
        return False
    if _extract_bed_no(plain):
        return True
    low = plain.lower()
    return any(token in plain or token in low for token in CLINICAL_HINT_TOKENS)


def _is_low_signal_text(text: str) -> bool:
    plain = _repair_text(text).strip()
    if not plain:
        return True
    if _is_noise_broadcast_text(plain):
        return True
    if _is_prompt_echo_text(plain):
        return True
    if _is_followup_query(plain):
        return False
    if _extract_device_action(plain):
        return False
    if _is_wake_alias_text(plain):
        return False
    compact = _compact_text(plain)
    if compact in LOW_SIGNAL_COMPACT_TEXTS:
        return True
    if len(compact) <= 3 and (not _is_clinical_hint(plain)):
        return True
    return False


def _should_accept_text_hint_fallback(text_hint: str, has_audio_input: bool) -> bool:
    hint = _repair_text(text_hint).strip()
    if not hint or _is_low_signal_text(hint):
        return False
    action = _extract_device_action(hint)
    bed_ref = _extract_bed_no(hint)
    valid_chars = len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", hint))
    if bed_ref:
        return True
    if not has_audio_input:
        return bool(action) or (_is_clinical_hint(hint) and valid_chars >= 3)
    # When audio exists, only trust strong clinical hints to avoid "行不行" style drift.
    return bool(action) or (_is_clinical_hint(hint) and valid_chars >= 3)


def _is_bad_stt_text(text: str) -> bool:
    plain = _repair_text(text)
    if not plain:
        return True
    if _is_low_signal_text(plain):
        return True
    markers = (
        "语音转写失败",
        "未识别到清晰语音",
        "未识别到语音",
        "请再说一遍",
        "无法听到您的话语",
        "请重试",
        "手动输入",
        "中文普通话护理场景问答",
        # Historical mojibake markers from older runs
        "璇煶杞啓澶辫触",
        "鏈瘑鍒埌娓呮櫚璇煶",
    )
    return any(marker in plain for marker in markers)


def _is_wake_only_text(text: str) -> bool:
    plain = _repair_text(text).strip()
    return _is_wake_alias_text(plain)


def _is_unusable_text_hint(text: str) -> bool:
    plain = _repair_text(text)
    if not plain:
        return True
    if _is_noise_broadcast_text(plain):
        return True
    if _extract_device_action(plain):
        return False
    if _is_followup_query(plain):
        return False
    if _is_low_signal_text(plain):
        return True
    if _is_bad_stt_text(plain):
        return True
    if re.search(r"[?？]{4,}", plain):
        return True
    valid_chars = len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", plain))
    return valid_chars < 2


def _infer_mode_from_text(text: str, default_mode: str) -> str:
    base = (default_mode or "patient_query").strip().lower() or "patient_query"
    if base in {"handover", "document", "escalation", "collaboration"}:
        return base
    plain = _repair_text(text).strip()
    if not plain:
        return base
    low = plain.lower()
    if any(token in plain for token in ("交班", "交接班")) or "handover" in low:
        return "handover"
    if any(token in plain for token in ("文书", "护理记录", "病程", "草稿")) or "document" in low:
        return "document"
    if any(token in plain for token in ("优先级", "风险", "上报", "异常", "建议")) or any(
        token in low for token in ("recommend", "escalate", "triage")
    ):
        return "escalation"
    if any(token in plain for token in ("通知", "发送给", "发给", "协作")) or "collab" in low:
        return "collaboration"
    return "patient_query"


def _request_ws_url(request: Request) -> str:
    if settings.device_public_ws_url:
        return settings.device_public_ws_url.strip()
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    ws_scheme = "wss" if str(proto).lower() == "https" else "ws"
    ws_path = settings.device_ws_path if settings.device_ws_path.startswith("/") else f"/{settings.device_ws_path}"
    return f"{ws_scheme}://{host}{ws_path}"


def _request_firmware_url(request: Request) -> str:
    configured = (settings.firmware_url or "").strip()
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
    http_scheme = "https" if str(proto).lower() == "https" else "http"
    if not configured:
        return f"{http_scheme}://{host}/firmware-not-used.bin"

    try:
        parsed = urlparse(configured)
    except Exception:
        parsed = None

    if parsed and parsed.hostname and parsed.hostname not in ("127.0.0.1", "localhost"):
        return configured

    path = "/firmware-not-used.bin"
    if parsed and parsed.path:
        path = parsed.path
    return f"{http_scheme}://{host}{path}"


def _decode_ws_audio_payload(frame_bytes: bytes) -> bytes:
    raw = bytes(frame_bytes or b"")
    if len(raw) < 4:
        return raw
    # BinaryProtocol3:
    # [0] type, [1] reserved, [2:4] payload_size (big-endian), [4:] payload
    payload_size = int.from_bytes(raw[2:4], byteorder="big", signed=False)
    if payload_size <= 0:
        return b""
    if payload_size <= len(raw) - 4:
        return raw[4 : 4 + payload_size]
    return raw


def _audio_frames_to_ndarray(frames: list[Any], target_sample_rate: int) -> list[Any]:
    if av is None or np is None:
        return []
    arrays: list[Any] = []
    resampler = av.audio.resampler.AudioResampler(
        format="s16",
        layout="mono",
        rate=target_sample_rate,
    )
    for frame in frames:
        resampled = resampler.resample(frame)
        if resampled is None:
            continue
        frame_list = resampled if isinstance(resampled, list) else [resampled]
        for item in frame_list:
            data = item.to_ndarray()
            if data.ndim > 1:
                data = data[0]
            if data.dtype != np.int16:
                data = data.astype(np.int16)
            arrays.append(data.reshape(-1))
    return arrays


def _normalize_pcm16_bytes(pcm: Any) -> Any:
    if np is None:
        return pcm
    if pcm is None or getattr(pcm, "size", 0) == 0:
        return pcm
    normalized = np.asarray(pcm, dtype=np.int16).astype(np.int32, copy=True)
    mean = int(np.mean(normalized))
    if abs(mean) > 120:
        normalized -= mean
    peak = int(np.max(np.abs(normalized))) if normalized.size else 0
    if peak > 0:
        if peak < 6000:
            scale = min(4.0, 14000.0 / peak)
        elif peak > 22000:
            scale = max(0.35, 16000.0 / peak)
        else:
            scale = 1.0
        if abs(scale - 1.0) > 1e-6:
            normalized = np.rint(normalized * scale)
    normalized = np.clip(normalized, -32768, 32767).astype(np.int16, copy=False)
    return normalized


def _opus_packets_to_wav_bytes(opus_packets: list[bytes], target_sample_rate: int = 16000) -> bytes:
    if av is None or np is None or not opus_packets:
        return b""
    try:
        decoder = av.codec.CodecContext.create("libopus", "r")
        decoder.sample_rate = target_sample_rate
        decoder.layout = "mono"
        decoder.open()
    except Exception as exc:
        logger.warning("opus_decoder_init_failed: %s", exc)
        return b""

    pcm_chunks: list[Any] = []
    for packet_bytes in opus_packets:
        if not packet_bytes:
            continue
        try:
            decoded = decoder.decode(av.packet.Packet(packet_bytes))
        except Exception:
            continue
        pcm_chunks.extend(_audio_frames_to_ndarray(decoded, target_sample_rate))

    try:
        flushed = decoder.decode(None)
    except Exception:
        flushed = []
    pcm_chunks.extend(_audio_frames_to_ndarray(flushed, target_sample_rate))

    if not pcm_chunks:
        return b""

    pcm = np.concatenate(pcm_chunks).astype(np.int16, copy=False)
    pcm = _normalize_pcm16_bytes(pcm)
    with io.BytesIO() as output:
        with wave.open(output, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(target_sample_rate)
            wav_file.writeframes(pcm.tobytes())
        return output.getvalue()


def _wav_bytes_to_opus_packets(
    wav_bytes: bytes,
    *,
    target_sample_rate: int = 16000,
    frame_duration_ms: int = 20,
) -> list[bytes]:
    if av is None or np is None or not wav_bytes:
        return []

    try:
        source = av.open(io.BytesIO(wav_bytes), mode="r")
    except Exception as exc:
        logger.warning("wav_open_failed: %s", exc)
        return []

    audio_stream = next((stream for stream in source.streams if stream.type == "audio"), None)
    if audio_stream is None:
        source.close()
        return []

    try:
        encoder = av.codec.CodecContext.create("libopus", "w")
        encoder.sample_rate = target_sample_rate
        encoder.layout = "mono"
        encoder.format = "s16"
        encoder.time_base = Fraction(1, target_sample_rate)
        encoder.options = {"frame_duration": str(frame_duration_ms)}
        encoder.open()
    except Exception as exc:
        source.close()
        logger.warning("opus_encoder_init_failed: %s", exc)
        return []

    frame_samples = max(encoder.frame_size or int(target_sample_rate * frame_duration_ms / 1000), 1)
    resampler = av.audio.resampler.AudioResampler(
        format="s16",
        layout="mono",
        rate=target_sample_rate,
    )

    packets: list[bytes] = []
    pending = np.zeros(0, dtype=np.int16)

    def encode_pending_chunk(chunk: Any) -> None:
        audio_frame = av.AudioFrame.from_ndarray(chunk.reshape(1, -1), format="s16", layout="mono")
        audio_frame.sample_rate = target_sample_rate
        for packet in encoder.encode(audio_frame):
            packets.append(bytes(packet))

    try:
        for decoded in source.decode(audio_stream):
            resampled = resampler.resample(decoded)
            if resampled is None:
                continue
            frame_list = resampled if isinstance(resampled, list) else [resampled]
            for frame in frame_list:
                data = frame.to_ndarray()
                if data.ndim > 1:
                    data = data[0]
                if data.dtype != np.int16:
                    data = data.astype(np.int16)
                pending = np.concatenate((pending, data.reshape(-1)))
                while pending.size >= frame_samples:
                    chunk = pending[:frame_samples]
                    pending = pending[frame_samples:]
                    encode_pending_chunk(chunk)

        if pending.size > 0:
            padded = np.pad(pending, (0, frame_samples - pending.size), mode="constant")
            encode_pending_chunk(padded)

        for packet in encoder.encode(None):
            packets.append(bytes(packet))
    finally:
        source.close()

    return [packet for packet in packets if packet]


def _pack_ws_binary_v3(payload: bytes) -> bytes:
    if not payload:
        return b""
    size = len(payload)
    if size > 65535:
        return b""
    return bytes((0, 0)) + size.to_bytes(2, byteorder="big", signed=False) + payload


async def _send_ws_audio_packets(websocket: WebSocket, packets: list[bytes], pace_ms: int = 20) -> None:
    if websocket.client_state != WebSocketState.CONNECTED:
        return
    delay = max(pace_ms, 0) / 1000.0
    for payload in packets:
        framed = _pack_ws_binary_v3(payload)
        if not framed:
            continue
        if websocket.client_state != WebSocketState.CONNECTED:
            break
        await websocket.send_bytes(framed)
        if delay:
            await asyncio.sleep(delay)


def _client_peer(ws: WebSocket) -> str:
    if ws.client is None:
        return "unknown"
    return f"{ws.client.host}:{ws.client.port}"


def _new_session_id() -> str:
    return f"{settings.device_session_prefix}-{uuid.uuid4()}"


class MockReplyPayload(BaseModel):
    stt_text: str | None = Field(default=None, description="Optional text for STT event")
    tts_text: str = Field(..., min_length=1, description="Text to be spoken back to device")
    once: bool = Field(default=True, description="true=use once, false=sticky")


class DeviceQueryPayload(BaseModel):
    device_id: str | None = None
    session_id: str
    text: str = ""
    mode: str = "patient_query"
    department_id: str | None = None
    requested_by: str | None = None


class DeviceBindPayload(BaseModel):
    user_id: str | None = None
    username: str | None = None


class DeviceSilentPayload(BaseModel):
    enabled: bool = True
    ttl_minutes: int | None = Field(default=None, ge=1, le=1440)


class DeviceHeartbeatPayload(BaseModel):
    device_id: str
    battery: int | None = None
    wifi_rssi: int | None = None
    status: str = "idle"


@dataclass
class PendingReply:
    stt_text: str | None
    tts_text: str
    once: bool = True


@dataclass
class SessionState:
    connection_id: str
    client: str
    created_at: str
    last_seen_at: str
    session_id: str = ""
    listening: bool = False
    listening_mode: str = ""
    binary_frames: int = 0
    audio_bytes: int = 0
    text_frames: int = 0
    turn_count: int = 0
    last_client_event: str = ""
    last_detect_text: str = ""
    last_stt_text: str = ""
    last_tts_text: str = ""
    last_error: str = ""
    owner_user_id: str = ""
    owner_username: str = ""
    listen_started_at: str = ""
    last_voice_at: str = ""
    tts_sample_rate: int = 16000
    tts_frame_duration_ms: int = 60
    last_turn_started_at: str = ""


@dataclass
class RecentContextState:
    owner_user_id: str
    device_id: str
    conversation_id: str
    bed_no: str = ""
    patient_id: str = ""
    mode: str = "patient_query"
    updated_at: str = ""


class GatewayRuntime:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions: dict[str, SessionState] = {}
        self._session_tasks: dict[str, asyncio.Task[Any]] = {}
        self._silence_tasks: dict[str, asyncio.Task[Any]] = {}
        self._turn_tasks: dict[str, asyncio.Task[Any]] = {}
        self._audio_buffers: dict[str, bytearray] = {}
        self._audio_packets: dict[str, list[bytes]] = {}
        self._uploaded_audio: dict[str, bytes] = {}
        self._turns: dict[str, dict[str, Any]] = {}
        self._heartbeats: dict[str, dict[str, Any]] = {}
        self._recent_contexts: dict[str, RecentContextState] = {}
        self._next_reply_once: PendingReply | None = None
        self._sticky_reply: PendingReply | None = None
        self._device_owner_user_id: str = (settings.device_owner_user_id or "u_linmeili").strip() or "u_linmeili"
        self._device_owner_username: str = (settings.device_owner_username or "linmeili").strip() or "linmeili"
        self._silent_enabled: bool = bool(settings.device_force_silent)
        self._silent_until_epoch: float | None = None

    async def add_session(self, connection_id: str, client: str) -> None:
        now = _iso_now()
        stale_session_tasks: list[asyncio.Task[Any]] = []
        stale_silence_tasks: list[asyncio.Task[Any]] = []
        async with self._lock:
            stale_ids = [sid for sid, state in self._sessions.items() if state.client == client and sid != connection_id]
            for sid in stale_ids:
                self._sessions.pop(sid, None)
                self._audio_buffers.pop(sid, None)
                self._audio_packets.pop(sid, None)
                task = self._session_tasks.pop(sid, None)
                if task is not None:
                    stale_session_tasks.append(task)
                silence_task = self._silence_tasks.pop(sid, None)
                if silence_task is not None:
                    stale_silence_tasks.append(silence_task)

            self._sessions[connection_id] = SessionState(
                connection_id=connection_id,
                client=client,
                created_at=now,
                last_seen_at=now,
                owner_user_id=self._device_owner_user_id,
                owner_username=self._device_owner_username,
                tts_sample_rate=max(int(settings.device_tts_sample_rate or 16000), 8000),
                tts_frame_duration_ms=max(10, min(int(settings.device_tts_frame_duration_ms or 60), 120)),
            )
            self._audio_buffers[connection_id] = bytearray()
            self._audio_packets[connection_id] = []
        for task in stale_session_tasks:
            if task and (not task.done()):
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        for task in stale_silence_tasks:
            if task and (not task.done()):
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def set_device_owner(self, *, user_id: str | None = None, username: str | None = None) -> dict[str, str]:
        async with self._lock:
            if user_id is not None:
                normalized_user_id = (user_id or "").strip()
                if normalized_user_id:
                    self._device_owner_user_id = normalized_user_id
            if username is not None:
                normalized_username = (username or "").strip()
                if normalized_username:
                    self._device_owner_username = normalized_username
            for state in self._sessions.values():
                state.owner_user_id = self._device_owner_user_id
                state.owner_username = self._device_owner_username
            return {
                "user_id": self._device_owner_user_id,
                "username": self._device_owner_username,
            }

    async def get_device_owner(self) -> dict[str, str]:
        async with self._lock:
            return {
                "user_id": self._device_owner_user_id,
                "username": self._device_owner_username,
            }

    def _is_silent_locked(self) -> bool:
        if not self._silent_enabled:
            return False
        if self._silent_until_epoch is not None and time.time() >= self._silent_until_epoch:
            self._silent_enabled = False
            self._silent_until_epoch = None
            return False
        return True

    async def set_silent(self, *, enabled: bool, ttl_minutes: int | None = None) -> dict[str, Any]:
        async with self._lock:
            self._silent_enabled = bool(enabled)
            if self._silent_enabled and ttl_minutes:
                self._silent_until_epoch = time.time() + (int(ttl_minutes) * 60)
            else:
                self._silent_until_epoch = None
            active = self._is_silent_locked()
            until_iso = ""
            if self._silent_until_epoch is not None:
                until_iso = datetime.fromtimestamp(self._silent_until_epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z")
            return {
                "enabled": active,
                "until": until_iso,
                "ttl_minutes": int(ttl_minutes or 0),
            }

    async def get_silent(self) -> dict[str, Any]:
        async with self._lock:
            active = self._is_silent_locked()
            until_iso = ""
            if self._silent_until_epoch is not None:
                until_iso = datetime.fromtimestamp(self._silent_until_epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z")
            return {
                "enabled": active,
                "until": until_iso,
                "ttl_minutes": 0,
            }

    async def is_silent(self) -> bool:
        async with self._lock:
            return self._is_silent_locked()

    async def remember_recent_context(
        self,
        *,
        owner_user_id: str,
        device_id: str,
        conversation_id: str,
        bed_no: str | None = None,
        patient_id: str | None = None,
        mode: str | None = None,
    ) -> None:
        key = (owner_user_id or "").strip()
        if not key:
            return
        now = _iso_now()
        async with self._lock:
            current = self._recent_contexts.get(key)
            if current is None:
                current = RecentContextState(
                    owner_user_id=key,
                    device_id=(device_id or settings.device_id_default).strip() or settings.device_id_default,
                    conversation_id=(conversation_id or "").strip(),
                    updated_at=now,
                )
                self._recent_contexts[key] = current
            if bed_no is not None and str(bed_no).strip():
                current.bed_no = str(bed_no).strip()
            if patient_id is not None and str(patient_id).strip():
                current.patient_id = str(patient_id).strip()
            if mode is not None and str(mode).strip():
                current.mode = str(mode).strip()
            if conversation_id:
                current.conversation_id = (conversation_id or "").strip()
            if device_id:
                current.device_id = (device_id or "").strip() or current.device_id
            current.updated_at = now

    async def get_recent_context(
        self,
        owner_user_id: str,
        *,
        max_age_sec: int = 900,
    ) -> dict[str, Any] | None:
        key = (owner_user_id or "").strip()
        if not key:
            return None
        async with self._lock:
            current = self._recent_contexts.get(key)
            if current is None:
                return None
            now = _utc_now()
            updated_at = _parse_iso_utc(current.updated_at)
            if (now - updated_at).total_seconds() > max(30, int(max_age_sec)):
                return None
            return {
                "owner_user_id": current.owner_user_id,
                "device_id": current.device_id,
                "conversation_id": current.conversation_id,
                "bed_no": current.bed_no,
                "patient_id": current.patient_id,
                "mode": current.mode,
                "updated_at": current.updated_at,
            }

    async def remove_session(self, connection_id: str) -> None:
        session_task: asyncio.Task[Any] | None = None
        silence_task: asyncio.Task[Any] | None = None
        async with self._lock:
            self._sessions.pop(connection_id, None)
            self._audio_buffers.pop(connection_id, None)
            self._audio_packets.pop(connection_id, None)
            session_task = self._session_tasks.pop(connection_id, None)
            silence_task = self._silence_tasks.pop(connection_id, None)
        if session_task and not session_task.done():
            session_task.cancel()
            try:
                await session_task
            except asyncio.CancelledError:
                pass
        if silence_task and not silence_task.done():
            silence_task.cancel()
            try:
                await silence_task
            except asyncio.CancelledError:
                pass

    async def attach_silence_task(self, connection_id: str, task: asyncio.Task[Any]) -> None:
        previous: asyncio.Task[Any] | None = None
        async with self._lock:
            previous = self._silence_tasks.pop(connection_id, None)
            self._silence_tasks[connection_id] = task
        if previous and not previous.done():
            previous.cancel()
            try:
                await previous
            except asyncio.CancelledError:
                pass

    async def cancel_silence_task(self, connection_id: str) -> None:
        task: asyncio.Task[Any] | None = None
        async with self._lock:
            task = self._silence_tasks.pop(connection_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def attach_session_task(self, connection_id: str, task: asyncio.Task[Any]) -> None:
        previous: asyncio.Task[Any] | None = None
        async with self._lock:
            previous = self._session_tasks.pop(connection_id, None)
            self._session_tasks[connection_id] = task
        if previous and not previous.done():
            previous.cancel()
            try:
                await previous
            except asyncio.CancelledError:
                pass

    async def cancel_session_task(self, connection_id: str) -> None:
        task: asyncio.Task[Any] | None = None
        async with self._lock:
            task = self._session_tasks.pop(connection_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def has_active_session_task(self, connection_id: str) -> bool:
        async with self._lock:
            task = self._session_tasks.get(connection_id)
            return bool(task and (not task.done()))

    async def attach_turn_task(self, session_id: str, task: asyncio.Task[Any]) -> None:
        previous: asyncio.Task[Any] | None = None
        async with self._lock:
            previous = self._turn_tasks.pop(session_id, None)
            self._turn_tasks[session_id] = task
        if previous and not previous.done():
            previous.cancel()
            try:
                await previous
            except asyncio.CancelledError:
                pass

    async def set_session_id(self, connection_id: str, session_id: str) -> None:
        async with self._lock:
            state = self._sessions.get(connection_id)
            if state:
                state.session_id = session_id
                state.last_seen_at = _iso_now()

    async def set_audio_params(
        self,
        connection_id: str,
        *,
        sample_rate: int | None = None,
        frame_duration_ms: int | None = None,
    ) -> tuple[int, int]:
        async with self._lock:
            state = self._sessions.get(connection_id)
            if not state:
                return (
                    max(int(settings.device_tts_sample_rate or 16000), 8000),
                    max(10, min(int(settings.device_tts_frame_duration_ms or 60), 120)),
                )
            if sample_rate is not None:
                # Keep server-side TTS sample rate authoritative to avoid
                # board-side resample mismatch across firmware variants.
                _ = max(int(sample_rate), 8000)
                state.tts_sample_rate = max(int(settings.device_tts_sample_rate or 16000), 8000)
            if frame_duration_ms is not None:
                state.tts_frame_duration_ms = max(10, min(int(frame_duration_ms), 120))
            state.last_seen_at = _iso_now()
            return (state.tts_sample_rate, state.tts_frame_duration_ms)

    async def get_audio_params(self, connection_id: str) -> tuple[int, int]:
        async with self._lock:
            state = self._sessions.get(connection_id)
            if not state:
                return (
                    max(int(settings.device_tts_sample_rate or 16000), 8000),
                    max(10, min(int(settings.device_tts_frame_duration_ms or 60), 120)),
                )
            return (state.tts_sample_rate, state.tts_frame_duration_ms)

    async def get_session_id(self, connection_id: str) -> str:
        async with self._lock:
            state = self._sessions.get(connection_id)
            return state.session_id if state else ""

    async def set_listening(self, connection_id: str, listening: bool, mode: str = "") -> None:
        now = _iso_now()
        async with self._lock:
            state = self._sessions.get(connection_id)
            if state:
                state.listening = listening
                if mode:
                    state.listening_mode = mode
                state.last_seen_at = now
                if listening:
                    state.listen_started_at = now
                    state.last_voice_at = now
                    # Reset stale text hint when a new listen turn starts.
                    state.last_detect_text = ""
                else:
                    state.listen_started_at = ""

    async def mark_text_frame(self, connection_id: str, event: str = "") -> None:
        async with self._lock:
            state = self._sessions.get(connection_id)
            if state:
                state.text_frames += 1
                state.last_seen_at = _iso_now()
                if event:
                    state.last_client_event = event

    async def append_audio_frame(self, connection_id: str, data: bytes) -> None:
        append_bytes = bytes(data or b"")
        if not append_bytes:
            return
        now = _iso_now()
        async with self._lock:
            state = self._sessions.get(connection_id)
            buffer = self._audio_buffers.get(connection_id)
            packets = self._audio_packets.get(connection_id)
            if state:
                state.binary_frames += 1
                state.audio_bytes += len(append_bytes)
                state.last_seen_at = now
                # Only active listening audio should extend the silence window.
                # Some firmware variants keep sending background frames even when
                # no turn is open, which can otherwise prevent auto-stop forever.
                if state.listening:
                    state.last_voice_at = now
            if buffer is not None:
                buffer.extend(append_bytes)
                max_bytes = max(settings.device_max_audio_buffer_bytes, 0)
                if max_bytes and len(buffer) > max_bytes:
                    overflow = len(buffer) - max_bytes
                    del buffer[:overflow]
            if packets is not None:
                packets.append(append_bytes)

    async def consume_audio_buffer(self, connection_id: str) -> bytes:
        async with self._lock:
            buffer = self._audio_buffers.get(connection_id)
            if buffer is None:
                return b""
            raw = bytes(buffer)
            buffer.clear()
            return raw

    async def consume_audio_packets(self, connection_id: str) -> list[bytes]:
        async with self._lock:
            packets = self._audio_packets.get(connection_id)
            if packets is None:
                return []
            copied = [bytes(packet) for packet in packets]
            packets.clear()
            return copied

    async def clear_audio_buffer(self, connection_id: str) -> None:
        async with self._lock:
            buffer = self._audio_buffers.get(connection_id)
            packets = self._audio_packets.get(connection_id)
            if buffer is not None:
                buffer.clear()
            if packets is not None:
                packets.clear()

    async def set_detect_text(self, connection_id: str, text: str) -> None:
        normalized = (text or "").strip()
        if not normalized:
            return
        now = _iso_now()
        async with self._lock:
            state = self._sessions.get(connection_id)
            if state:
                state.last_detect_text = normalized
                state.last_seen_at = now
                state.last_voice_at = now

    async def get_listen_snapshot(self, connection_id: str) -> dict[str, Any] | None:
        async with self._lock:
            state = self._sessions.get(connection_id)
            if state is None:
                return None
            return {
                "listening": state.listening,
                "listening_mode": state.listening_mode,
                "listen_started_at": state.listen_started_at,
                "last_voice_at": state.last_voice_at,
                "session_id": state.session_id,
            }

    async def consume_detect_text(self, connection_id: str) -> str:
        async with self._lock:
            state = self._sessions.get(connection_id)
            if not state:
                return ""
            text = state.last_detect_text.strip()
            state.last_detect_text = ""
            state.last_seen_at = _iso_now()
            return text

    async def clear_detect_text(self, connection_id: str) -> None:
        async with self._lock:
            state = self._sessions.get(connection_id)
            if not state:
                return
            state.last_detect_text = ""
            state.last_seen_at = _iso_now()

    async def try_mark_turn_started(self, connection_id: str, *, min_interval_sec: float = 0.6) -> bool:
        threshold = max(float(min_interval_sec), 0.1)
        now_utc = _utc_now()
        now_iso = _iso_now()
        async with self._lock:
            state = self._sessions.get(connection_id)
            if not state:
                return False
            if state.last_turn_started_at:
                prev_utc = _parse_iso_utc(state.last_turn_started_at)
                if (now_utc - prev_utc).total_seconds() < threshold:
                    return False
            state.last_turn_started_at = now_iso
            state.last_seen_at = now_iso
            return True

    async def set_turn_text(self, connection_id: str, stt_text: str | None = None, tts_text: str | None = None) -> None:
        async with self._lock:
            state = self._sessions.get(connection_id)
            if not state:
                return
            if stt_text is not None:
                state.last_stt_text = stt_text
            if tts_text is not None:
                state.last_tts_text = tts_text
                state.turn_count += 1
            state.last_seen_at = _iso_now()

    async def set_last_error(self, connection_id: str, error_text: str) -> None:
        async with self._lock:
            state = self._sessions.get(connection_id)
            if state:
                state.last_error = (error_text or "").strip()
                state.last_seen_at = _iso_now()

    async def list_sessions(self) -> list[dict[str, Any]]:
        async with self._lock:
            return [
                {
                    "connection_id": s.connection_id,
                    "session_id": s.session_id,
                    "client": s.client,
                    "created_at": s.created_at,
                    "last_seen_at": s.last_seen_at,
                    "listening": s.listening,
                    "listening_mode": s.listening_mode,
                    "binary_frames": s.binary_frames,
                    "audio_bytes": s.audio_bytes,
                    "text_frames": s.text_frames,
                    "turn_count": s.turn_count,
                    "last_client_event": s.last_client_event,
                    "last_detect_text": s.last_detect_text,
                    "last_stt_text": s.last_stt_text,
                    "last_tts_text": s.last_tts_text,
                    "last_error": s.last_error,
                    "owner_user_id": s.owner_user_id or self._device_owner_user_id,
                    "owner_username": s.owner_username or self._device_owner_username,
                    "listen_started_at": s.listen_started_at,
                    "last_voice_at": s.last_voice_at,
                    "tts_sample_rate": s.tts_sample_rate,
                    "tts_frame_duration_ms": s.tts_frame_duration_ms,
                }
                for s in self._sessions.values()
            ]

    async def set_mock_reply(self, payload: MockReplyPayload) -> None:
        reply = PendingReply(stt_text=payload.stt_text, tts_text=payload.tts_text.strip(), once=payload.once)
        async with self._lock:
            if payload.once:
                self._next_reply_once = reply
            else:
                self._sticky_reply = reply

    async def clear_mock_reply(self) -> None:
        async with self._lock:
            self._next_reply_once = None
            self._sticky_reply = None

    async def consume_reply(self) -> PendingReply:
        async with self._lock:
            if self._next_reply_once is not None:
                reply = self._next_reply_once
                self._next_reply_once = None
                return reply
            if self._sticky_reply is not None:
                return self._sticky_reply
        return PendingReply(
            stt_text=settings.device_default_stt_text,
            tts_text=settings.device_default_tts_text,
            once=True,
        )

    async def save_uploaded_audio(self, session_id: str, audio_bytes: bytes) -> None:
        async with self._lock:
            self._uploaded_audio[session_id] = bytes(audio_bytes or b"")

    async def get_uploaded_audio(self, session_id: str) -> bytes:
        async with self._lock:
            return bytes(self._uploaded_audio.get(session_id, b""))

    async def upsert_turn(self, session_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            turn = self._turns.get(session_id)
            if turn is None:
                turn = {
                    "session_id": session_id,
                    "device_id": settings.device_id_default,
                    "requested_by": settings.device_owner_user_id,
                    "owner_username": settings.device_owner_username,
                    "status": "waiting",
                    "mode": "patient_query",
                    "summary": "",
                    "stt_text": "",
                    "tts_text": "",
                    "findings": [],
                    "recommendations": [],
                    "confidence": 0.0,
                    "review_required": True,
                    "audio_ready": False,
                    "audio_base64": "",
                    "audio_mime": "audio/wav",
                    "source": "http",
                    "error": "",
                    "input_text": "",
                    "input_audio_bytes": 0,
                    "conversation_id": "",
                    "resolved_bed_no": "",
                    "resolved_patient_id": "",
                    "skip_reply": False,
                    "created_at": _iso_now(),
                    "updated_at": _iso_now(),
                }
                self._turns[session_id] = turn
            for key, value in patch.items():
                turn[key] = value
            turn["updated_at"] = _iso_now()
            return dict(turn)

    async def get_turn(self, session_id: str) -> dict[str, Any] | None:
        async with self._lock:
            turn = self._turns.get(session_id)
            return dict(turn) if turn else None

    async def set_heartbeat(self, device_id: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            now = _iso_now()
            body = dict(payload)
            body["device_id"] = device_id
            body["at"] = now
            self._heartbeats[device_id] = body

    async def get_heartbeat(self, device_id: str) -> dict[str, Any] | None:
        async with self._lock:
            value = self._heartbeats.get(device_id)
            return dict(value) if value else None


runtime = GatewayRuntime()


async def _send_json(websocket: WebSocket, connection_id: str, payload: dict[str, Any]) -> None:
    if websocket.client_state != WebSocketState.CONNECTED:
        return
    session_id = await runtime.get_session_id(connection_id)
    body = dict(payload)
    if session_id and "session_id" not in body:
        body["session_id"] = session_id
    await websocket.send_json(body)


async def _call_json(method: str, url: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    timeout = httpx.Timeout(settings.device_http_timeout_sec, connect=8)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        response = await client.request(method, url, json=payload)
    if response.status_code >= 400:
        message = response.text or f"upstream error {response.status_code}"
        raise HTTPException(status_code=502, detail=message)
    if not response.text:
        return {}
    try:
        parsed = response.json()
        if isinstance(parsed, dict):
            return parsed
        return {"raw": parsed}
    except Exception:
        return {"raw": response.text}


async def _call_upload_voice(audio_bytes: bytes) -> str:
    if not audio_bytes:
        return ""
    timeout = httpx.Timeout(settings.device_http_timeout_sec, connect=8)
    files = {"file": ("device_audio.opus", audio_bytes, "application/octet-stream")}
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        response = await client.post(f"{settings.asr_service_url}/voice/upload", files=files)
    if response.status_code >= 400:
        return ""
    try:
        body = response.json()
    except Exception:
        return ""
    return str(body.get("chunk_id") or "").strip()


async def _run_pipeline(
    *,
    session_id: str,
    device_id: str,
    department_id: str,
    requested_by: str,
    owner_username: str = "",
    mode: str,
    source: str,
    input_text: str,
    audio_bytes: bytes,
    audio_packets: list[bytes] | None = None,
) -> dict[str, Any]:
    start_ts = time.perf_counter()
    owner_user_id = _normalize_user_id(requested_by or settings.device_owner_user_id)
    await runtime.upsert_turn(
        session_id,
        {
            "session_id": session_id,
            "conversation_id": session_id,
            "device_id": device_id or settings.device_id_default,
            "department_id": (department_id or "").strip() or settings.device_department_id_default,
            "requested_by": owner_user_id,
            "owner_username": (owner_username or "").strip() or settings.device_owner_username,
            "mode": mode or "patient_query",
            "source": source,
            "status": "processing",
            "input_text": (input_text or "").strip(),
            "input_audio_bytes": len(audio_bytes or b""),
            "error": "",
        },
    )

    try:
        raw_hint = (input_text or "").strip()
        text_hint = "" if _is_unusable_text_hint(raw_hint) else _repair_text(raw_hint)
        asr_audio_bytes = bytes(audio_bytes or b"")
        if audio_packets:
            decoded_wav = _opus_packets_to_wav_bytes(
                audio_packets,
                target_sample_rate=max(int(settings.device_stt_sample_rate or 16000), 8000),
            )
            if decoded_wav:
                asr_audio_bytes = decoded_wav
        has_audio_input = bool(asr_audio_bytes)
        strong_audio_input = len(asr_audio_bytes) >= max(
            int(settings.device_min_feedback_audio_bytes or 0),
            max(int(settings.device_min_audio_bytes or 0) * 20, 6000),
        )

        transcribe_payload: dict[str, Any] = {
            "request_id": str(uuid.uuid4()),
        }
        if text_hint:
            transcribe_payload["text_hint"] = text_hint
        if asr_audio_bytes:
            transcribe_payload["audio_base64"] = base64.b64encode(asr_audio_bytes).decode("utf-8")

        stt_text = ""
        raw_stt_candidate = ""
        if (not asr_audio_bytes) and text_hint:
            stt_text = text_hint
            raw_stt_candidate = text_hint
        elif asr_audio_bytes:
            try:
                stt_resp = await _call_json("POST", f"{settings.asr_service_url}/asr/transcribe", payload=transcribe_payload)
                candidate = _repair_text(str(stt_resp.get("text") or "")).strip()
                raw_stt_candidate = candidate
                if candidate and not _is_bad_stt_text(candidate):
                    stt_text = candidate
            except Exception as exc:
                logger.warning("asr_transcribe_failed session_id=%s err=%s", session_id, exc)

        if _is_bad_stt_text(stt_text) and text_hint and (_is_clinical_hint(text_hint) or _is_followup_query(text_hint)):
            stt_text = text_hint

        if (not stt_text) and _should_accept_text_hint_fallback(text_hint, has_audio_input):
            stt_text = text_hint

        stt_text = _repair_text(stt_text or "")
        if stt_text:
            stripped_stt = _strip_leading_wake_words(stt_text)
            if stripped_stt:
                stt_text = stripped_stt
        if text_hint:
            stripped_hint = _strip_leading_wake_words(text_hint)
            if stripped_hint:
                text_hint = stripped_hint
        drop_noisy_turn = False
        usable_text_hint = bool(
            text_hint
            and (not _is_wake_alias_text(text_hint))
            and (not _is_noise_broadcast_text(text_hint))
            and ((not _is_low_signal_text(text_hint)) or _is_clinical_hint(text_hint) or _extract_device_action(text_hint))
        )
        if not stt_text or _is_bad_stt_text(stt_text):
            candidate_plain = _repair_text(raw_stt_candidate or "")
            if source == "websocket" and (not usable_text_hint):
                if ((not candidate_plain) or _is_low_signal_text(candidate_plain) or _is_noise_broadcast_text(candidate_plain)) and (
                    not strong_audio_input
                ):
                    drop_noisy_turn = True
            stt_text = "未识别到清晰语音，请再说一遍。"
            logger.info(
                "pipeline_stt_unusable session_id=%s source=%s text_hint=%s has_audio=%s strong_audio=%s input_audio_bytes=%s",
                session_id,
                source,
                bool(text_hint),
                has_audio_input,
                strong_audio_input,
                len(asr_audio_bytes),
            )
        if (not drop_noisy_turn) and source == "websocket":
            normalized_mode = (mode or "patient_query").strip().lower() or "patient_query"
            if normalized_mode == "patient_query":
                if stt_text and (not _is_clinical_hint(stt_text)) and (not _is_followup_query(stt_text)):
                    if (not _extract_device_action(stt_text)) and (not strong_audio_input):
                        drop_noisy_turn = True
        if drop_noisy_turn:
            turn = await runtime.upsert_turn(
                session_id,
                {
                    "status": "completed",
                    "mode": mode or "patient_query",
                    "conversation_id": session_id,
                    "stt_text": stt_text,
                    "summary": "",
                    "tts_text": "",
                    "findings": [],
                    "recommendations": [],
                    "confidence": 0.0,
                    "review_required": False,
                    "resolved_bed_no": "",
                    "resolved_patient_id": "",
                    "audio_base64": "",
                    "audio_ready": False,
                    "audio_mime": "audio/wav",
                    "silent_mode": True,
                    "device_action": "",
                    "skip_reply": True,
                    "error": "",
                },
            )
            logger.info("pipeline_skip_noisy_turn session_id=%s source=%s", session_id, source)
            return turn

        device_action = _extract_device_action(stt_text or text_hint)
        effective_mode = _infer_mode_from_text(stt_text, mode or "patient_query")
        bed_no = _extract_bed_no(stt_text)
        recent_ctx = await runtime.get_recent_context(owner_user_id)
        reuse_recent_context = _should_reuse_recent_context(stt_text, effective_mode)
        conversation_id = session_id
        if reuse_recent_context and recent_ctx:
            prior_conversation_id = str(recent_ctx.get("conversation_id") or "").strip()
            prior_bed_no = str(recent_ctx.get("bed_no") or "").strip()
            if prior_conversation_id:
                conversation_id = prior_conversation_id
            if (not bed_no) and prior_bed_no:
                bed_no = prior_bed_no
                logger.info(
                    "pipeline_reuse_context session_id=%s owner=%s bed_no=%s conversation_id=%s mode=%s",
                    session_id,
                    owner_user_id,
                    bed_no,
                    conversation_id,
                    effective_mode,
                )
        ai_resp: dict[str, Any]
        if device_action == "wake":
            await runtime.set_silent(enabled=False)
            ai_resp = {
                "summary": "我在，请讲。",
                "findings": ["device_wake_ack"],
                "recommendations": [{"title": "请直接说患者床号与需求，例如：帮我看12床情况。", "priority": 1}],
                "confidence": 0.98,
                "review_required": False,
            }
        elif device_action == "sleep":
            await runtime.set_silent(enabled=True, ttl_minutes=480)
            ai_resp = {
                "summary": "已收到，设备将进入休眠。需要我时请说“小医小医”。",
                "findings": ["device_sleep"],
                "recommendations": [{"title": "需要时再次唤醒后继续提问。", "priority": 1}],
                "confidence": 0.92,
                "review_required": False,
            }
        elif _is_bad_stt_text(stt_text):
            ai_resp = {
                "summary": "未识别到清晰语音，请再说一遍。",
                "findings": ["asr_low_quality"],
                "recommendations": [{"title": "靠近麦克风并放慢语速后重试", "priority": 1}],
                "confidence": 0.3,
                "review_required": False,
            }
        else:
            try:
                if effective_mode in {"handover", "document", "escalation"}:
                    workflow_map = {
                        "handover": "handover_generate",
                        "document": "document_generation",
                        "escalation": "recommendation_request",
                    }
                    wf_payload: dict[str, Any] = {
                        "workflow_type": workflow_map.get(effective_mode, "voice_inquiry"),
                        "conversation_id": conversation_id,
                        "user_input": stt_text,
                        "requested_by": owner_user_id,
                    }
                    target_department = (department_id or "").strip() or settings.device_department_id_default
                    if target_department:
                        wf_payload["department_id"] = target_department
                    if bed_no:
                        wf_payload["bed_no"] = bed_no
                    ai_resp = await _call_json("POST", f"{settings.agent_orchestrator_service_url}/workflow/run", payload=wf_payload)
                else:
                    # Patient query should go through workflow orchestration so bed context,
                    # recommendation/doc writeback, and audit remain consistent.
                    wf_payload = {
                        "workflow_type": "voice_inquiry",
                        "conversation_id": conversation_id,
                        "user_input": stt_text,
                        "requested_by": owner_user_id,
                    }
                    target_department = (department_id or "").strip() or settings.device_department_id_default
                    if target_department:
                        wf_payload["department_id"] = target_department
                    if bed_no:
                        wf_payload["bed_no"] = bed_no
                    ai_resp = await _call_json("POST", f"{settings.agent_orchestrator_service_url}/workflow/run", payload=wf_payload)
            except Exception as exc:
                logger.warning("pipeline_agent_call_failed session_id=%s err=%s", session_id, exc)
                ai_resp = {
                    "summary": "后端AI暂时不可用，请稍后再试。",
                    "findings": [f"agent_call_failed:{exc}"],
                    "recommendations": [
                        {
                            "title": (
                                "检查后端链路："
                                f"ASR={settings.asr_service_url} "
                                f"ORCH={settings.agent_orchestrator_service_url} "
                                f"TTS={settings.tts_service_url}"
                            ),
                            "priority": 1,
                        }
                    ],
                    "confidence": 0.25,
                    "review_required": True,
                }

        summary = _strip_question_echo(str(ai_resp.get("summary") or settings.device_default_tts_text))
        findings_raw = ai_resp.get("findings") if isinstance(ai_resp.get("findings"), list) else []
        recommendations_raw = ai_resp.get("recommendations") if isinstance(ai_resp.get("recommendations"), list) else []
        findings: list[Any] = [_repair_text(str(item)) for item in findings_raw if _repair_text(str(item))]
        recommendations: list[Any] = []
        for item in recommendations_raw:
            if isinstance(item, dict):
                title = _repair_text(str(item.get("title") or "")).strip()
                if title:
                    recommendations.append({"title": title, "priority": int(item.get("priority", 2) or 2)})
            else:
                title = _repair_text(str(item)).strip()
                if title:
                    recommendations.append({"title": title, "priority": 2})
        confidence = float(ai_resp.get("confidence", 0.72) or 0.72)
        review_required = bool(ai_resp.get("review_required", True))
        resolved_patient_id = str(ai_resp.get("patient_id") or ai_resp.get("resolved_patient_id") or "").strip()
        resolved_bed_no = (
            bed_no
            or str(ai_resp.get("bed_no") or ai_resp.get("resolved_bed_no") or "").strip()
        )
        resolved_bed_no = (resolved_bed_no or "").strip()

        if resolved_bed_no or resolved_patient_id:
            await runtime.remember_recent_context(
                owner_user_id=owner_user_id,
                device_id=device_id or settings.device_id_default,
                conversation_id=conversation_id,
                bed_no=resolved_bed_no,
                patient_id=resolved_patient_id,
                mode=effective_mode,
            )

        silent_mode = await runtime.is_silent()
        tts_input = re.sub(r"\s+", " ", summary).strip()
        if not tts_input:
            tts_input = settings.device_default_tts_text
        max_chars = max(settings.device_tts_max_chars, 0)
        if silent_mode:
            tts_input = ""
        elif max_chars and len(tts_input) > max_chars:
            chunks = [seg.strip() for seg in re.split(r"(?<=[。！？.!?；;])\s*", tts_input) if seg.strip()]
            if chunks:
                reduced = ""
                for seg in chunks:
                    if len(reduced) + len(seg) > max_chars:
                        break
                    reduced += seg
                    if len(reduced) >= int(max_chars * 0.7):
                        break
                tts_input = reduced or tts_input
            if len(tts_input) > max_chars:
                tts_input = f"{tts_input[:max_chars].rstrip('，,。.!！?？;；')}。"
        logger.info(
            "tts_text_prepared session_id=%s summary_len=%s tts_len=%s max_chars=%s silent=%s",
            session_id,
            len(summary),
            len(tts_input),
            max_chars,
            silent_mode,
        )

        audio_base64 = ""
        if (not silent_mode) and tts_input:
            try:
                tts_resp = await _call_json(
                    "POST",
                    f"{settings.tts_service_url}/tts/speak",
                    payload={"text": tts_input, "voice": "default"},
                )
                audio_base64 = str(tts_resp.get("audio_base64") or "").strip()
            except Exception as exc:
                logger.warning("pipeline_tts_failed session_id=%s err=%s", session_id, exc)

        turn = await runtime.upsert_turn(
            session_id,
            {
                "status": "completed",
                "conversation_id": conversation_id,
                "mode": effective_mode,
                "stt_text": stt_text,
                "summary": summary,
                "tts_text": tts_input,
                "findings": findings,
                "recommendations": recommendations,
                "confidence": confidence,
                "review_required": review_required,
                "resolved_bed_no": resolved_bed_no,
                "resolved_patient_id": resolved_patient_id,
                "audio_base64": audio_base64,
                "audio_ready": bool(audio_base64),
                "audio_mime": "audio/wav",
                "silent_mode": silent_mode,
                "device_action": device_action,
                "error": "",
            },
        )
        logger.info(
            "pipeline_completed session_id=%s source=%s stt_len=%s summary_len=%s audio_ready=%s elapsed_ms=%d",
            session_id,
            source,
            len(stt_text),
            len(summary),
            bool(audio_base64),
            int((time.perf_counter() - start_ts) * 1000),
        )
        return turn
    except asyncio.CancelledError:
        raise
    except HTTPException as exc:
        turn = await runtime.upsert_turn(
            session_id,
            {
                "status": "failed",
                "error": str(exc.detail or "pipeline_failed"),
            },
        )
        return turn
    except Exception as exc:
        turn = await runtime.upsert_turn(
            session_id,
            {
                "status": "failed",
                "error": f"pipeline_failed:{exc}",
            },
        )
        return turn


def _parse_iso_utc(value: str | None) -> datetime:
    raw = (value or "").strip()
    if not raw:
        return _utc_now()
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return _utc_now()


async def _watch_listen_silence(websocket: WebSocket, connection_id: str, mode: str) -> None:
    timeout_sec = max(int(settings.device_listen_silence_timeout_sec or 3), 1)
    max_turn_sec = max(int(settings.device_listen_max_duration_sec or 0), 0)
    tick_sec = 0.25
    while True:
        await asyncio.sleep(tick_sec)
        snapshot = await runtime.get_listen_snapshot(connection_id)
        if not snapshot:
            return
        if not bool(snapshot.get("listening")):
            return

        started_at = _parse_iso_utc(str(snapshot.get("listen_started_at") or ""))
        last_voice_at = _parse_iso_utc(str(snapshot.get("last_voice_at") or ""))
        now = _utc_now()
        listen_seconds = (now - started_at).total_seconds()
        idle_seconds = (now - max(started_at, last_voice_at)).total_seconds()
        should_stop_by_timeout = idle_seconds >= timeout_sec
        should_stop_by_max = bool(max_turn_sec and listen_seconds >= max_turn_sec)
        if (not should_stop_by_timeout) and (not should_stop_by_max):
            continue

        await runtime.set_listening(connection_id, False, mode or "patient_query")
        logger.info(
            "listen_auto_stop connection_id=%s idle_seconds=%.2f timeout=%s listen_seconds=%.2f max_turn=%s reason=%s",
            connection_id,
            idle_seconds,
            timeout_sec,
            listen_seconds,
            max_turn_sec,
            "max_duration" if should_stop_by_max else "silence",
        )
        if settings.mock_mode:
            turn_task = asyncio.create_task(_run_mock_turn(websocket, connection_id))
        else:
            can_start = await runtime.try_mark_turn_started(connection_id, min_interval_sec=1.1)
            if not can_start:
                logger.info("listen_auto_stop_skip_duplicate connection_id=%s", connection_id)
                return
            turn_task = asyncio.create_task(_run_ws_turn(websocket, connection_id, mode))
        await runtime.attach_session_task(connection_id, turn_task)
        return


async def _run_ws_turn(websocket: WebSocket, connection_id: str, mode: str) -> None:
    wait_sec = max(settings.device_capture_wait_ms, 0) / 1000.0
    if wait_sec:
        await asyncio.sleep(wait_sec)

    session_id = await runtime.get_session_id(connection_id)
    if not session_id:
        session_id = _new_session_id()
        await runtime.set_session_id(connection_id, session_id)

    detect_text = _repair_text(await runtime.consume_detect_text(connection_id))

    min_audio_bytes = max(settings.device_min_audio_bytes, 0)
    audio_packets: list[bytes] = []
    audio_chunks: list[bytes] = []
    # Audio frames may arrive slightly after listen:stop in some firmware variants.
    # Keep a short grace window before deciding this turn is empty.
    for idx in range(8):
        new_packets = await runtime.consume_audio_packets(connection_id)
        new_audio = await runtime.consume_audio_buffer(connection_id)
        if new_packets:
            audio_packets.extend(new_packets)
        if new_audio:
            audio_chunks.append(new_audio)
        merged_len = sum(len(chunk) for chunk in audio_chunks)
        if merged_len >= min_audio_bytes:
            break
        # If detect text arrives first, wait a little longer for trailing audio
        # to avoid over-trusting noisy short text snippets.
        if detect_text and merged_len >= max(96, min_audio_bytes // 3):
            break
        if detect_text and idx >= 4:
            break
        if idx < 7:
            await asyncio.sleep(0.2)

    audio_bytes = b"".join(audio_chunks)
    if len(audio_bytes) < min_audio_bytes and not detect_text:
        logger.info(
            "skip_turn_empty_audio connection_id=%s bytes=%s packets=%s",
            connection_id,
            len(audio_bytes),
            len(audio_packets),
        )
        return
    if (not detect_text) and len(audio_bytes) < max(2000, min_audio_bytes * 4):
        logger.info(
            "skip_turn_low_audio_noise connection_id=%s bytes=%s packets=%s",
            connection_id,
            len(audio_bytes),
            len(audio_packets),
        )
        return

    delay_sec = max(settings.device_response_delay_ms, 0) / 1000.0
    if delay_sec:
        await asyncio.sleep(delay_sec)

    owner = await runtime.get_device_owner()
    turn = await _run_pipeline(
        session_id=session_id,
        device_id=settings.device_id_default,
        department_id=settings.device_department_id_default,
        requested_by=(owner.get("user_id") or settings.device_owner_user_id),
        owner_username=(owner.get("username") or settings.device_owner_username),
        mode=mode or "patient_query",
        source="websocket",
        input_text=detect_text,
        audio_bytes=audio_bytes,
        audio_packets=audio_packets,
    )

    if turn.get("status") != "completed":
        error_text = str(turn.get("error") or "local processing failed")
        silent_mode = await runtime.is_silent()
        await runtime.set_last_error(connection_id, error_text)
        await _send_json(websocket, connection_id, {"type": "stt", "text": error_text})
        if not silent_mode:
            await _send_json(websocket, connection_id, {"type": "tts", "state": "start"})
            await _send_json(websocket, connection_id, {"type": "tts", "state": "sentence_start", "text": error_text})
            await _send_json(websocket, connection_id, {"type": "tts", "state": "stop"})
        return
    if bool(turn.get("skip_reply")):
        logger.info("ws_turn_skip_reply connection_id=%s session_id=%s", connection_id, session_id)
        return

    stt_text = str(turn.get("stt_text") or settings.device_default_stt_text)
    tts_text = str(turn.get("tts_text") or turn.get("summary") or settings.device_default_tts_text)
    silent_mode = bool(turn.get("silent_mode"))
    await runtime.set_turn_text(connection_id, stt_text=stt_text, tts_text=tts_text)
    try:
        await _send_json(websocket, connection_id, {"type": "stt", "text": stt_text})
        await _send_json(websocket, connection_id, {"type": "llm", "emotion": "neutral"})
        if not silent_mode:
            await _send_json(websocket, connection_id, {"type": "tts", "state": "start"})
            sentence_gap = max(settings.device_tts_sentence_gap_ms, 0) / 1000.0
            for sentence in _split_tts_sentences(tts_text):
                await _send_json(websocket, connection_id, {"type": "tts", "state": "sentence_start", "text": sentence})
                if sentence_gap:
                    await asyncio.sleep(sentence_gap)

            # Stream encoded Opus packets to the firmware speaker path.
            audio_base64 = str(turn.get("audio_base64") or "").strip()
            tts_packets: list[bytes] = []
            tts_sample_rate, tts_frame_duration_ms = await runtime.get_audio_params(connection_id)
            if audio_base64:
                try:
                    wav_bytes = base64.b64decode(audio_base64)
                except Exception:
                    wav_bytes = b""
                if wav_bytes:
                    tts_packets = _wav_bytes_to_opus_packets(
                        wav_bytes,
                        target_sample_rate=max(int(tts_sample_rate or settings.device_tts_sample_rate or 16000), 8000),
                        frame_duration_ms=max(10, min(int(tts_frame_duration_ms or settings.device_tts_frame_duration_ms or 60), 120)),
                    )
            if tts_packets:
                await _send_ws_audio_packets(websocket, tts_packets, pace_ms=max(0, settings.device_tts_packet_pace_ms))
            else:
                logger.warning("ws_tts_no_audio_packets connection_id=%s session_id=%s", connection_id, session_id)
            await _send_json(websocket, connection_id, {"type": "tts", "state": "stop"})
        else:
            logger.info("ws_tts_skipped_by_silent connection_id=%s session_id=%s", connection_id, session_id)
        if str(turn.get("device_action") or "").strip().lower() == "sleep":
            await _send_json(websocket, connection_id, {"type": "goodbye"})
            await websocket.close()
            logger.info("ws_device_sleep connection_id=%s session_id=%s", connection_id, session_id)
            return
    except WebSocketDisconnect:
        logger.info("ws_turn_client_disconnected connection_id=%s session_id=%s", connection_id, session_id)
        return
    except Exception as exc:
        logger.warning("ws_turn_send_failed connection_id=%s session_id=%s err=%s", connection_id, session_id, exc)
        return


async def _run_mock_turn(websocket: WebSocket, connection_id: str) -> None:
    reply = await runtime.consume_reply()
    stt_text = (reply.stt_text or settings.device_default_stt_text).strip()
    tts_text = (reply.tts_text or settings.device_default_tts_text).strip()
    silent_mode = await runtime.is_silent()
    delay = max(settings.device_response_delay_ms, 0) / 1000.0
    try:
        if delay:
            await asyncio.sleep(delay)
        await _send_json(websocket, connection_id, {"type": "stt", "text": stt_text})
        await runtime.set_turn_text(connection_id, stt_text=stt_text)
        await asyncio.sleep(0.1)
        await _send_json(websocket, connection_id, {"type": "llm", "emotion": "neutral"})
        if not silent_mode:
            await asyncio.sleep(0.08)
            await _send_json(websocket, connection_id, {"type": "tts", "state": "start"})
            for sentence in _split_tts_sentences(tts_text):
                await _send_json(websocket, connection_id, {"type": "tts", "state": "sentence_start", "text": sentence})
                await asyncio.sleep(0.16)
            await _send_json(websocket, connection_id, {"type": "tts", "state": "stop"})
            await runtime.set_turn_text(connection_id, tts_text=tts_text)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("mock_turn_failed connection_id=%s err=%s", connection_id, exc)


async def _handle_text_message(websocket: WebSocket, connection_id: str, message: str) -> None:
    try:
        payload = json.loads(message)
    except json.JSONDecodeError:
        logger.info("ignore_non_json connection_id=%s", connection_id)
        return

    msg_type = str(payload.get("type") or "").strip().lower()
    await runtime.mark_text_frame(connection_id, msg_type or "unknown")

    if msg_type == "hello":
        session_id = str(payload.get("session_id") or "").strip() or _new_session_id()
        await runtime.set_session_id(connection_id, session_id)
        incoming_audio = payload.get("audio_params", {}) if isinstance(payload.get("audio_params"), dict) else {}
        req_sample_rate = incoming_audio.get("sample_rate")
        req_frame_duration = incoming_audio.get("frame_duration")
        try:
            req_sample_rate = int(req_sample_rate) if req_sample_rate is not None else None
        except Exception:
            req_sample_rate = None
        try:
            req_frame_duration = int(req_frame_duration) if req_frame_duration is not None else None
        except Exception:
            req_frame_duration = None
        chosen_sample_rate, chosen_frame_duration = await runtime.set_audio_params(
            connection_id,
            sample_rate=req_sample_rate,
            frame_duration_ms=req_frame_duration,
        )
        await _send_json(
            websocket,
            connection_id,
            {
                "type": "hello",
                "transport": "websocket",
                "session_id": session_id,
                "audio_params": {
                    "format": "opus",
                    "sample_rate": chosen_sample_rate,
                    "channels": 1,
                    "frame_duration": chosen_frame_duration,
                },
                "features": {"mcp": True},
            },
        )
        logger.info(
            "ws_hello connection_id=%s session_id=%s tts_sample_rate=%s frame_duration=%s",
            connection_id,
            session_id,
            chosen_sample_rate,
            chosen_frame_duration,
        )
        return

    if msg_type == "listen":
        state = str(payload.get("state") or "").strip().lower()
        mode = str(payload.get("mode") or "").strip().lower() or "patient_query"
        if mode == "auto":
            mode = "patient_query"
        if state == "start":
            if await runtime.has_active_session_task(connection_id):
                logger.info("listen_start_ignore_turn_inflight connection_id=%s mode=%s", connection_id, mode)
                return
            snapshot = await runtime.get_listen_snapshot(connection_id)
            if snapshot and bool(snapshot.get("listening")):
                logger.info("listen_start_ignore_duplicate connection_id=%s mode=%s", connection_id, mode)
                return
            await runtime.cancel_silence_task(connection_id)
            await runtime.clear_detect_text(connection_id)
            await runtime.set_listening(connection_id, True, mode)
            await runtime.clear_audio_buffer(connection_id)
            silence_task = asyncio.create_task(_watch_listen_silence(websocket, connection_id, mode))
            await runtime.attach_silence_task(connection_id, silence_task)
            logger.info("listen_start connection_id=%s mode=%s", connection_id, mode)
            return
        if state == "stop":
            if await runtime.has_active_session_task(connection_id):
                logger.info("listen_stop_ignore_turn_inflight connection_id=%s mode=%s", connection_id, mode)
                return
            await runtime.cancel_silence_task(connection_id)
            await runtime.set_listening(connection_id, False, mode)
            can_start = await runtime.try_mark_turn_started(connection_id, min_interval_sec=1.1)
            if not can_start:
                logger.info("listen_stop_skip_duplicate connection_id=%s mode=%s", connection_id, mode)
                return
            if settings.mock_mode:
                task = asyncio.create_task(_run_mock_turn(websocket, connection_id))
            else:
                task = asyncio.create_task(_run_ws_turn(websocket, connection_id, mode))
            await runtime.attach_session_task(connection_id, task)
            logger.info("listen_stop connection_id=%s mode=%s", connection_id, mode)
            return
        if state == "detect":
            if await runtime.has_active_session_task(connection_id):
                logger.info("listen_detect_ignore_turn_inflight connection_id=%s", connection_id)
                return
            snapshot = await runtime.get_listen_snapshot(connection_id)
            if not snapshot or not bool(snapshot.get("listening")):
                logger.info("listen_detect_ignored_not_listening connection_id=%s", connection_id)
                return
            detect_text = _repair_text(str(payload.get("text") or "").strip())
            if detect_text and _is_noise_broadcast_text(detect_text):
                # Ignore startup/noise transcripts pushed by firmware demos.
                logger.info("listen_detect_ignore_noise connection_id=%s text=%s", connection_id, detect_text)
                return
            if detect_text and _is_wake_only_text(detect_text):
                # Wake aliases should not consume a full turn; keep listening for real query.
                logger.info("listen_detect_wake_only connection_id=%s text=%s", connection_id, detect_text)
                return
            if detect_text:
                await runtime.set_detect_text(connection_id, detect_text)
                if _is_low_signal_text(detect_text) and not _extract_device_action(detect_text):
                    # Keep collecting audio for this turn instead of committing too early.
                    logger.info("listen_detect_defer_low_signal connection_id=%s text=%s", connection_id, detect_text)
                else:
                    logger.info("listen_detect_buffered connection_id=%s text=%s", connection_id, detect_text)
            # Do not force trigger a turn on detect. We wait for listen:stop or silence auto-stop
            # so the ASR gets complete utterance audio instead of truncated fragments.
            return

    if msg_type == "abort":
        await runtime.cancel_silence_task(connection_id)
        await runtime.cancel_session_task(connection_id)
        await _send_json(websocket, connection_id, {"type": "tts", "state": "stop"})
        logger.info("abort connection_id=%s", connection_id)
        return

    if msg_type == "goodbye":
        await runtime.cancel_silence_task(connection_id)
        await runtime.cancel_session_task(connection_id)
        await _send_json(websocket, connection_id, {"type": "goodbye"})
        await websocket.close()
        logger.info("goodbye connection_id=%s", connection_id)
        return

    if msg_type == "mcp":
        await _send_json(
            websocket,
            connection_id,
            {"type": "mcp", "payload": {"status": "ok", "echo": payload.get("payload", {})}},
        )
        logger.info("mcp_echo connection_id=%s", connection_id)
        return

    logger.info("ignore_type connection_id=%s type=%s", connection_id, msg_type or "<empty>")


@router.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": settings.service_name}


@router.get("/ready")
def ready() -> dict[str, Any]:
    return {"status": "ready", "service": settings.service_name}


@router.get("/version")
def version() -> dict[str, Any]:
    return {
        "service": settings.service_name,
        "version": settings.app_version,
        "env": settings.app_env,
        "mock_mode": settings.mock_mode,
        "pipeline_mode": settings.device_pipeline_mode,
        "owner_user_id": settings.device_owner_user_id,
        "owner_username": settings.device_owner_username,
        "force_silent_default": settings.device_force_silent,
        "ws_audio_stream": True,
        "decode_client_binary_v3": True,
    }


@router.api_route("/xiaozhi/ota/", methods=["GET", "POST"])
@router.api_route("/xiaozhi/ota", methods=["GET", "POST"])
@router.api_route("/xiaozhi/", methods=["GET", "POST"])
@router.api_route("/xiaozhi", methods=["GET", "POST"])
@router.api_route("/xiaoz/", methods=["GET", "POST"])
@router.api_route("/xiaoz", methods=["GET", "POST"])
@router.api_route("/xi/", methods=["GET", "POST"])
@router.api_route("/xi", methods=["GET", "POST"])
async def xiaozhi_ota(request: Request) -> dict[str, Any]:
    now = _utc_now()
    return {
        "server_time": {
            "timestamp": int(now.timestamp() * 1000),
            "timezone_offset": _timezone_offset_minutes(),
        },
        "firmware": {
            "version": settings.firmware_version_floor,
            "url": _request_firmware_url(request),
            "force": 0,
        },
        "websocket": {
            "url": _request_ws_url(request),
            "token": settings.device_ws_token,
            "version": settings.device_ws_version,
        },
    }


@router.api_route("/xiaozhi/ota/{tail:path}", methods=["GET", "POST"])
@router.api_route("/xiaoz/{tail:path}", methods=["GET", "POST"])
@router.api_route("/xi/{tail:path}", methods=["GET", "POST"])
async def xiaozhi_ota_fallback(tail: str, request: Request) -> dict[str, Any]:
    _ = tail
    # Some firmware variants accidentally append encoded CRLF/command fragments.
    # Always return canonical OTA payload to let the device self-recover.
    return await xiaozhi_ota(request)


@router.get("/firmware-not-used.bin")
async def firmware_not_used() -> Response:
    return Response(content=b"", media_type="application/octet-stream")


@router.post("/xiaozhi/ota/activate")
async def xiaozhi_activate(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "status": "ok",
        "activated": True,
        "received": bool(payload),
        "at": _iso_now(),
    }


@router.get("/api/device/sessions")
async def device_sessions() -> dict[str, Any]:
    sessions = await runtime.list_sessions()
    return {"count": len(sessions), "sessions": sessions}


@router.get("/api/device/binding")
async def device_binding() -> dict[str, Any]:
    owner = await runtime.get_device_owner()
    return {
        "status": "ok",
        "device_id": settings.device_id_default,
        "owner_user_id": owner.get("user_id") or settings.device_owner_user_id,
        "owner_username": owner.get("username") or settings.device_owner_username,
    }


@router.post("/api/device/bind")
async def device_bind(payload: DeviceBindPayload) -> dict[str, Any]:
    user_id = (payload.user_id or "").strip()
    username = (payload.username or "").strip()
    if not user_id and not username:
        raise HTTPException(status_code=400, detail="user_id_or_username_required")

    if not user_id and username:
        user_id = f"u_{username}"
    if user_id and not username:
        if user_id.startswith("u_"):
            username = user_id[2:]
        else:
            username = user_id

    owner = await runtime.set_device_owner(user_id=user_id, username=username)
    return {
        "status": "ok",
        "device_id": settings.device_id_default,
        "owner_user_id": owner.get("user_id") or settings.device_owner_user_id,
        "owner_username": owner.get("username") or settings.device_owner_username,
    }


@router.get("/api/device/silent")
async def device_silent_status() -> dict[str, Any]:
    state = await runtime.get_silent()
    return {"status": "ok", **state}


@router.post("/api/device/silent")
async def device_silent_set(payload: DeviceSilentPayload) -> dict[str, Any]:
    state = await runtime.set_silent(enabled=payload.enabled, ttl_minutes=payload.ttl_minutes)
    return {"status": "ok", **state}


@router.post("/api/device/mock/reply")
async def set_mock_reply(payload: MockReplyPayload) -> dict[str, Any]:
    await runtime.set_mock_reply(payload)
    return {
        "status": "ok",
        "mode": "once" if payload.once else "sticky",
        "stt_text": payload.stt_text,
        "tts_text": payload.tts_text,
    }


@router.delete("/api/device/mock/reply")
async def clear_mock_reply() -> dict[str, Any]:
    await runtime.clear_mock_reply()
    return {"status": "ok", "cleared": True}


@router.post("/api/device/audio/upload")
async def device_audio_upload(
    request: Request,
    file: UploadFile | None = File(default=None),
    device_id: str = Form(default=""),
    session_id: str = Form(default=""),
) -> dict[str, Any]:
    sid = (session_id or "").strip() or _new_session_id()
    raw = b""
    if file is not None:
        raw = await file.read()
    if not raw:
        raw = await request.body()
    await runtime.save_uploaded_audio(sid, raw)
    await runtime.upsert_turn(
        sid,
        {
            "session_id": sid,
            "device_id": (device_id or settings.device_id_default).strip() or settings.device_id_default,
            "status": "accepted",
            "source": "http_upload",
            "input_audio_bytes": len(raw),
        },
    )
    return {"session_id": sid, "status": "accepted"}


@router.post("/api/device/query")
async def device_query(payload: DeviceQueryPayload) -> dict[str, Any]:
    sid = (payload.session_id or "").strip() or _new_session_id()
    mode = (payload.mode or "patient_query").strip() or "patient_query"
    device_id = (payload.device_id or settings.device_id_default).strip() or settings.device_id_default
    department_id = (payload.department_id or settings.device_department_id_default).strip() or settings.device_department_id_default
    owner = await runtime.get_device_owner()
    requested_by = _normalize_user_id(payload.requested_by or owner.get("user_id") or settings.device_owner_user_id)
    text = (payload.text or "").strip()
    audio = await runtime.get_uploaded_audio(sid)

    await runtime.upsert_turn(
        sid,
        {
            "session_id": sid,
            "device_id": device_id,
            "department_id": department_id,
            "requested_by": requested_by,
            "owner_username": owner.get("username") or settings.device_owner_username,
            "mode": mode,
            "status": "processing",
            "source": "http_query",
            "input_text": text,
            "input_audio_bytes": len(audio),
            "error": "",
        },
    )

    async def _job() -> None:
        await _run_pipeline(
            session_id=sid,
            device_id=device_id,
            department_id=department_id,
            requested_by=requested_by,
            owner_username=(owner.get("username") or settings.device_owner_username),
            mode=mode,
            source="http_query",
            input_text=text,
            audio_bytes=audio,
        )

    task = asyncio.create_task(_job())
    await runtime.attach_turn_task(sid, task)
    return {"status": "processing", "session_id": sid}


@router.get("/api/device/result/{session_id}")
async def device_result(session_id: str) -> dict[str, Any]:
    sid = (session_id or "").strip()
    turn = await runtime.get_turn(sid)
    if not turn:
        return {
            "status": "waiting",
            "summary": "",
            "audio_ready": False,
            "audio_url": "",
            "review_required": True,
            "session_id": sid,
        }
    return {
        "status": turn.get("status", "waiting"),
        "summary": turn.get("summary", ""),
        "audio_ready": bool(turn.get("audio_ready")),
        "audio_url": f"/api/device/audio/{sid}" if turn.get("audio_base64") else "",
        "review_required": bool(turn.get("review_required", True)),
        "session_id": sid,
        "requested_by": turn.get("requested_by", ""),
        "owner_username": turn.get("owner_username", ""),
        "conversation_id": turn.get("conversation_id", ""),
        "resolved_bed_no": turn.get("resolved_bed_no", ""),
        "resolved_patient_id": turn.get("resolved_patient_id", ""),
        "stt_text": turn.get("stt_text", ""),
        "tts_text": turn.get("tts_text", ""),
        "findings": turn.get("findings", []),
        "recommendations": turn.get("recommendations", []),
        "confidence": turn.get("confidence", 0.0),
        "device_action": turn.get("device_action", ""),
        "error": turn.get("error", ""),
    }


@router.get("/api/device/audio/{session_id}")
async def device_audio(session_id: str) -> Response:
    sid = (session_id or "").strip()
    turn = await runtime.get_turn(sid)
    if not turn:
        raise HTTPException(status_code=404, detail="session_not_found")
    audio_base64 = str(turn.get("audio_base64") or "").strip()
    if not audio_base64:
        raise HTTPException(status_code=404, detail="audio_not_ready")
    try:
        binary = base64.b64decode(audio_base64)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"audio_decode_failed:{exc}") from exc
    media_type = str(turn.get("audio_mime") or "audio/wav")
    return Response(content=binary, media_type=media_type)


@router.post("/api/device/heartbeat")
async def device_heartbeat(payload: DeviceHeartbeatPayload) -> dict[str, Any]:
    await runtime.set_heartbeat(
        payload.device_id,
        {
            "battery": payload.battery,
            "wifi_rssi": payload.wifi_rssi,
            "status": payload.status,
        },
    )
    return {"status": "ok", "device_id": payload.device_id, "at": _iso_now()}


@router.websocket("/xiaozhi/v1/")
@router.websocket("/xiaozhi/v1")
@router.websocket("/xia")
@router.websocket("/xia/")
@router.websocket("/xiaoz")
@router.websocket("/xiaoz/")
@router.websocket("/xi")
@router.websocket("/xi/")
async def xiaozhi_v1(websocket: WebSocket) -> None:
    await websocket.accept()
    connection_id = str(uuid.uuid4())
    await runtime.add_session(connection_id, _client_peer(websocket))
    logger.info("ws_connected connection_id=%s client=%s", connection_id, _client_peer(websocket))

    try:
        while True:
            frame = await websocket.receive()
            if frame.get("type") == "websocket.disconnect":
                break
            if frame.get("text") is not None:
                await _handle_text_message(websocket, connection_id, str(frame["text"]))
                continue
            if frame.get("bytes") is not None:
                payload = _decode_ws_audio_payload(bytes(frame["bytes"]))
                await runtime.append_audio_frame(connection_id, payload)
                continue
    except WebSocketDisconnect:
        logger.info("ws_disconnected connection_id=%s", connection_id)
    except Exception as exc:
        logger.warning("ws_error connection_id=%s err=%s", connection_id, exc)
        try:
            await websocket.close()
        except Exception:
            pass
    finally:
        await runtime.remove_session(connection_id)


@router.websocket("/{ws_tail:path}")
async def xiaozhi_ws_fallback(websocket: WebSocket, ws_tail: str) -> None:
    raw = f"/{ws_tail or ''}"
    decoded = unquote(raw).strip().lower()
    if decoded in {"/", ""} or any(token in decoded for token in ("xia", "protocol", "ws")):
        logger.warning("ws_path_fallback raw=%s decoded=%s", raw, decoded)
        await xiaozhi_v1(websocket)
        return
    await websocket.close(code=1008)

