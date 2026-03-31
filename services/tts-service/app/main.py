from fastapi import FastAPI

from app.api.routes import router
from app.core.config import settings

app = FastAPI(
    title=f'AI Nursing - {settings.service_name}',
    version=settings.app_version,
)

app.include_router(router)
