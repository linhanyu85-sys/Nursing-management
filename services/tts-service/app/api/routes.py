import base64
import io
import math
import os
import subprocess
import sys
import tempfile
import wave
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter

from app.core.config import settings
from app.schemas.tts import SpeakRequest, SpeakResponse

router = APIRouter()


def _beep_wav_base64(duration_sec: float = 1.2, sample_rate: int = 16000, freq_hz: float = 660.0) -> str:
    total = max(int(duration_sec * sample_rate), 1)
    amplitude = 0.22 * 32767.0
    with io.BytesIO() as buffer:
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            frames = bytearray()
            for i in range(total):
                value = int(amplitude * math.sin(2.0 * math.pi * freq_hz * i / sample_rate))
                frames.extend(int(value).to_bytes(2, byteorder="little", signed=True))
            wav.writeframes(bytes(frames))
        return base64.b64encode(buffer.getvalue()).decode("ascii")


def _windows_sapi_wav_base64(text: str) -> str | None:
    if os.name != "nt":
        return None
    spoken = (text or "").strip()
    if not spoken:
        spoken = "Test speech from local fallback."

    fd, wav_path = tempfile.mkstemp(prefix="tts_fallback_", suffix=".wav")
    os.close(fd)
    try:
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        powershell_exe = os.path.join(system_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
        if not os.path.exists(powershell_exe):
            powershell_exe = "powershell"
        ps_script = (
            "$ErrorActionPreference='Stop'; "
            "Add-Type -AssemblyName System.Speech; "
            "$txt=[Environment]::GetEnvironmentVariable('TTS_TEXT'); "
            "$out=[Environment]::GetEnvironmentVariable('TTS_OUT'); "
            "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$s.Volume=100; "
            "$s.Rate=2; "
            "$s.SetOutputToWaveFile($out); "
            "$s.Speak($txt); "
            "$s.Dispose();"
        )
        env = os.environ.copy()
        env["TTS_TEXT"] = spoken
        env["TTS_OUT"] = wav_path
        subprocess.run(
            [powershell_exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            check=True,
            env=env,
            timeout=20,
        )
        with open(wav_path, "rb") as f:
            data = f.read()
        if len(data) < 512:
            return None
        try:
            with wave.open(io.BytesIO(data), "rb") as wav_obj:
                if wav_obj.getnframes() <= 0:
                    return None
        except Exception:
            return None
        return base64.b64encode(data).decode("ascii")
    except Exception as exc:
        print(f"[tts-service] windows_sapi_fallback_failed: {exc}")
        return None
    finally:
        try:
            os.remove(wav_path)
        except Exception:
            pass


def _pyttsx3_wav_base64(text: str) -> str | None:
    spoken = (text or "").strip()
    if not spoken:
        spoken = "Test speech from local fallback."

    fd, wav_path = tempfile.mkstemp(prefix="tts_pyttsx3_", suffix=".wav")
    os.close(fd)
    try:
        py_script = (
            "import os, pyttsx3; "
            "txt=os.environ.get('TTS_TEXT','Test speech from local fallback.'); "
            "out=os.environ.get('TTS_OUT'); "
            "engine=pyttsx3.init(); "
            "engine.setProperty('rate', 220); "
            "engine.save_to_file(txt, out); "
            "engine.runAndWait(); "
            "engine.stop()"
        )
        env = os.environ.copy()
        env["TTS_TEXT"] = spoken
        env["TTS_OUT"] = wav_path
        subprocess.run([sys.executable, "-c", py_script], check=True, timeout=30, env=env)
        with open(wav_path, "rb") as f:
            data = f.read()
        if len(data) < 512:
            return None
        try:
            with wave.open(io.BytesIO(data), "rb") as wav_obj:
                if wav_obj.getnframes() <= 0:
                    return None
        except Exception:
            return None
        return base64.b64encode(data).decode("ascii")
    except Exception as exc:
        print(f"[tts-service] pyttsx3_fallback_failed: {exc}")
        return None
    finally:
        try:
            os.remove(wav_path)
        except Exception:
            pass


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


@router.get("/debug/source")
def debug_source() -> dict:
    return {
        "module_file": __file__,
        "mock_mode": settings.mock_mode,
        "llm_force_enable": settings.llm_force_enable,
        "cosyvoice_base_url": settings.cosyvoice_base_url,
    }


@router.post("/tts/speak", response_model=SpeakResponse)
async def speak(payload: SpeakRequest) -> SpeakResponse:
    should_mock = settings.mock_mode and not settings.llm_force_enable
    if should_mock:
        local_voice_b64 = _windows_sapi_wav_base64(payload.text)
        if local_voice_b64:
            return SpeakResponse(
                audio_base64=local_voice_b64,
                provider="mock-windows-sapi",
                created_at=datetime.now(timezone.utc),
            )
        pyttsx3_b64 = _pyttsx3_wav_base64(payload.text)
        if pyttsx3_b64:
            return SpeakResponse(
                audio_base64=pyttsx3_b64,
                provider="mock-pyttsx3",
                created_at=datetime.now(timezone.utc),
            )
        return SpeakResponse(
            audio_base64=_beep_wav_base64(),
            provider="mock-beep",
            created_at=datetime.now(timezone.utc),
        )

    try:
        async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
            response = await client.post(f"{settings.cosyvoice_base_url}/speak", json=payload.model_dump())
        response.raise_for_status()
        body = response.json()
        return SpeakResponse(
            audio_base64=body.get("audio_base64", ""),
            provider="cosyvoice",
            created_at=datetime.now(timezone.utc),
        )
    except Exception:
        local_voice_b64 = _windows_sapi_wav_base64(payload.text)
        if local_voice_b64:
            return SpeakResponse(
                audio_base64=local_voice_b64,
                provider="fallback-windows-sapi",
                created_at=datetime.now(timezone.utc),
            )
        pyttsx3_b64 = _pyttsx3_wav_base64(payload.text)
        if pyttsx3_b64:
            return SpeakResponse(
                audio_base64=pyttsx3_b64,
                provider="fallback-pyttsx3",
                created_at=datetime.now(timezone.utc),
            )
        return SpeakResponse(
            audio_base64=_beep_wav_base64(),
            provider="fallback-beep",
            created_at=datetime.now(timezone.utc),
        )
