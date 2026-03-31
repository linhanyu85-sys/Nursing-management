from datetime import datetime

from pydantic import BaseModel


class TranscribeRequest(BaseModel):
    text_hint: str | None = None
    audio_base64: str | None = None
    chunk_id: str | None = None
    request_id: str | None = None


class TranscribeResponse(BaseModel):
    text: str
    confidence: float
    provider: str
    created_at: datetime


class VoiceUploadResponse(BaseModel):
    chunk_id: str
    received_at: datetime
