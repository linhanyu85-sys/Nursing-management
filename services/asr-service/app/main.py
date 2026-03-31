import asyncio
import logging

from fastapi import FastAPI

from app.api.routes import router
from app.core.config import settings
from app.services.local_asr import warmup_local_asr

app = FastAPI(
    title=f"AI Nursing - {settings.service_name}",
    version=settings.app_version,
)

app.include_router(router)

logger = logging.getLogger(__name__)


def _warmup_task() -> None:
    ok = warmup_local_asr()
    logger.info("asr_startup_warmup=%s model=%s", ok, settings.local_asr_model_size)


@app.on_event("startup")
async def on_startup() -> None:
    if settings.local_asr_enabled and settings.local_asr_warmup_on_startup:
        asyncio.create_task(asyncio.to_thread(_warmup_task))
