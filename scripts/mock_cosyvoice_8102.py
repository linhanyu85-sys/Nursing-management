import base64
import io
import os
import subprocess
import sys
import tempfile
import wave
from datetime import datetime, timezone

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="mock-cosyvoice-8102")


class SpeakReq(BaseModel):
    text: str = ""
    voice: str = "default"


def _gen_wav_b64(txt: str) -> str:
    s = (txt or "").strip()
    if s == "":
        s = "Hello from local cosyvoice mock."

    fd, p = tempfile.mkstemp(prefix="cosyvoice_mock_", suffix=".wav")
    os.close(fd)
    try:
        code = (
            "import os, pyttsx3; "
            "txt=os.environ.get('TTS_TEXT','Hello from local cosyvoice mock.'); "
            "out=os.environ.get('TTS_OUT'); "
            "engine=pyttsx3.init(); "
            "engine.save_to_file(txt, out); "
            "engine.runAndWait(); "
            "engine.stop()"
        )
        e = os.environ.copy()
        e["TTS_TEXT"] = s
        e["TTS_OUT"] = p
        subprocess.run([sys.executable, "-c", code], check=True, timeout=30, env=e)

        f = open(p, "rb")
        d = f.read()
        f.close()
        if len(d) < 512:
            raise RuntimeError("generated wav too short")
        buf = io.BytesIO(d)
        w = wave.open(buf, "rb")
        nf = w.getnframes()
        w.close()
        if nf <= 0:
            raise RuntimeError("generated wav has zero frames")
        return base64.b64encode(d).decode("ascii")
    finally:
        try:
            os.remove(p)
        except Exception:
            pass


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "mock-cosyvoice-8102"}


@app.post("/speak")
def speak(req: SpeakReq) -> dict:
    b64 = _gen_wav_b64(req.text)
    ts = datetime.now(timezone.utc).isoformat()
    return {
        "audio_base64": b64,
        "provider": "mock-cosyvoice-pyttsx3",
        "created_at": ts,
    }
