from datetime import datetime

from pydantic import BaseModel


class SpeakRequest(BaseModel):
    text: str
    voice: str = "default"


class SpeakResponse(BaseModel):
    audio_base64: str
    provider: str
    created_at: datetime
