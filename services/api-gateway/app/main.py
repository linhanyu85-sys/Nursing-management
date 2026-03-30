from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import settings

app = FastAPI(
    title=f"AI Nursing - {settings.service_name}",
    version=settings.app_version,
)

allow_origins = [item.strip() for item in settings.cors_origins.split(",")] if settings.cors_origins else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

admin_web_dir = Path(__file__).resolve().parents[3] / "apps" / "admin-web"
if admin_web_dir.exists():
    app.mount("/admin", StaticFiles(directory=admin_web_dir, html=True), name="admin-web")
