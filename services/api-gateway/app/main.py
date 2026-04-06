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

project_apps_dir = Path(__file__).resolve().parents[3] / "apps"

static_mounts = [
    ("admin-web", "/admin", True),
    ("mobile-web", "/mobile", True),
    ("downloads", "/downloads", False),
]

for folder_name, mount_path, html_mode in static_mounts:
    static_dir = project_apps_dir / folder_name
    if static_dir.exists():
        app.mount(
            mount_path,
            StaticFiles(directory=static_dir, html=html_mode),
            name=folder_name,
        )
