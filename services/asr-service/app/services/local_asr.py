from __future__ import annotations

import base64
import binascii
import logging
import os
import tempfile
import wave
from io import BytesIO
from pathlib import Path
from threading import Lock

from app.core.config import settings

try:
    from faster_whisper import WhisperModel
except Exception:  # pragma: no cover
    WhisperModel = None  # type: ignore[assignment]


_MODEL = None
_MODEL_LOCK = Lock()
logger = logging.getLogger(__name__)
NURSING_ASR_PROMPT = (
    "医疗护理场景中文对话。"
    "常见词：床号、号床、病区、交班、护理记录、尿量、血压、心率、呼吸、体温、血氧、值班医生、责任医生、建议、上报。"
    "唤醒词和命令：小医小医、小依小依、小智小智、休眠、进入休眠、停止聆听。"
)
COMMAND_FALLBACK_PROMPT = (
    "短指令识别。高频词：小医小医、小依小依、休眠、停止聆听、"
    "帮我看12床情况、23床交班草稿、护理记录草稿。"
)


def _guess_suffix(raw: bytes) -> str:
    if raw.startswith(b"RIFF"):
        return ".wav"
    if raw.startswith(b"OggS"):
        return ".ogg"
    if raw.startswith(b"ID3") or raw[:2] == b"\xff\xfb":
        return ".mp3"
    if b"ftyp" in raw[:32]:
        return ".m4a"
    return ".bin"


def _decode_audio_base64(audio_base64: str) -> bytes:
    text = (audio_base64 or "").strip()
    if text.startswith("data:") and "," in text:
        text = text.split(",", 1)[1]
    if not text:
        return b""
    try:
        return base64.b64decode(text, validate=False)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("invalid_audio_base64") from exc


def _get_model() -> WhisperModel:
    global _MODEL
    if WhisperModel is None:
        raise RuntimeError("faster_whisper_not_installed")

    with _MODEL_LOCK:
        if _MODEL is None:
            download_root = Path(settings.local_asr_download_root).resolve()
            download_root.mkdir(parents=True, exist_ok=True)
            _MODEL = WhisperModel(
                settings.local_asr_model_size,
                device=settings.local_asr_device,
                compute_type=settings.local_asr_compute_type,
                download_root=str(download_root),
            )
    return _MODEL


def _build_initial_prompt(text_hint: str | None) -> str:
    hint = (text_hint or "").strip()
    if hint:
        return f"{NURSING_ASR_PROMPT} 用户问题可能包含：{hint}"
    return NURSING_ASR_PROMPT


def _transcribe_once(model: WhisperModel, temp_path: str, kwargs: dict) -> tuple:
    try:
        return model.transcribe(temp_path, **kwargs)
    except TypeError:
        # Compatibility fallback for older faster-whisper versions.
        safe_kwargs = dict(kwargs)
        safe_kwargs.pop("vad_parameters", None)
        safe_kwargs.pop("without_timestamps", None)
        return model.transcribe(temp_path, **safe_kwargs)


def _warmup_audio_bytes(sample_rate: int = 16000, duration_ms: int = 360) -> bytes:
    samples = max(int(sample_rate * duration_ms / 1000), 1)
    with BytesIO() as buf:
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(b"\x00\x00" * samples)
        return buf.getvalue()


def warmup_local_asr() -> bool:
    if not settings.local_asr_enabled:
        return False
    try:
        model = _get_model()
    except Exception as exc:
        logger.warning("local_asr_warmup_skip: %s", exc)
        return False

    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
            temp_file.write(_warmup_audio_bytes())
            temp_path = temp_file.name

        _transcribe_once(
            model,
            temp_path,
            {
                "task": "transcribe",
                "language": "zh",
                "beam_size": 1,
                "vad_filter": False,
                "condition_on_previous_text": False,
                "initial_prompt": NURSING_ASR_PROMPT,
                "temperature": 0.0,
                "without_timestamps": True,
            },
        )
        logger.info(
            "local_asr_warmup_ok model=%s device=%s compute=%s",
            settings.local_asr_model_size,
            settings.local_asr_device,
            settings.local_asr_compute_type,
        )
        return True
    except Exception as exc:
        logger.warning("local_asr_warmup_failed: %s", exc)
        return False
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def transcribe_audio_base64(audio_base64: str, text_hint: str | None = None) -> tuple[str, float, str]:
    raw = _decode_audio_base64(audio_base64)
    if not raw:
        return "", 0.0, f"faster-whisper-{settings.local_asr_model_size}"

    suffix = _guess_suffix(raw)
    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_file.write(raw)
            temp_path = temp_file.name

        model = _get_model()
        transcribe_kwargs = {
            "task": "transcribe",
            "language": "zh",
            "beam_size": max(int(settings.local_asr_beam_size or 1), 1),
            "vad_filter": True,
            "vad_parameters": {
                "min_silence_duration_ms": max(int(settings.local_asr_vad_min_silence_ms or 260), 120),
                "speech_pad_ms": max(int(settings.local_asr_vad_speech_pad_ms or 120), 0),
            },
            "condition_on_previous_text": False,
            "initial_prompt": _build_initial_prompt(text_hint),
            "temperature": 0.0,
            "without_timestamps": True,
        }
        segments, info = _transcribe_once(model, temp_path, transcribe_kwargs)
        text = "".join(segment.text for segment in segments).strip()
        confidence = float(getattr(info, "language_probability", 0.0) or 0.0)

        if not text:
            segments, info = _transcribe_once(
                model,
                temp_path,
                {
                    "task": "transcribe",
                    "language": None,
                    "beam_size": 1,
                    "vad_filter": True,
                    "condition_on_previous_text": False,
                    "initial_prompt": _build_initial_prompt(text_hint),
                    "temperature": 0.0,
                    "without_timestamps": True,
                },
            )
            text = "".join(segment.text for segment in segments).strip()
            confidence = float(getattr(info, "language_probability", 0.0) or 0.0)

        # Short command utterances can be cut too aggressively by VAD.
        if not text:
            segments, info = _transcribe_once(
                model,
                temp_path,
                {
                    "task": "transcribe",
                    "language": "zh",
                    "beam_size": 1,
                    "vad_filter": False,
                    "condition_on_previous_text": False,
                    "initial_prompt": COMMAND_FALLBACK_PROMPT,
                    "temperature": 0.0,
                    "without_timestamps": True,
                },
            )
            text = "".join(segment.text for segment in segments).strip()
            confidence = float(getattr(info, "language_probability", 0.0) or 0.0)

        return text, confidence, f"faster-whisper-{settings.local_asr_model_size}"
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
