from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.core.config import settings
from app.services.agent_task_worker import agent_task_worker


@asynccontextmanager
async def lifespan(_: FastAPI):
    await agent_task_worker.start()
    try:
        yield
    finally:
        await agent_task_worker.stop()


app = FastAPI(
    title=f"AI Nursing - {settings.service_name}",
    version=settings.app_version,
    lifespan=lifespan,
)

app.include_router(router)
