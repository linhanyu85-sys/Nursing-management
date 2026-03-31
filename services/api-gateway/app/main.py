from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
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


def _resolve_admin_dir() -> Path | None:
    configured = Path(settings.admin_web_dir).expanduser() if settings.admin_web_dir else None
    candidates = [
        configured,
        Path(__file__).resolve().parents[3] / "apps" / "admin-web",
    ]
    for candidate in candidates:
        if candidate and candidate.exists() and (candidate / "index.html").exists():
            return candidate
    return None


admin_dir = _resolve_admin_dir()
if admin_dir is not None:
    app.mount("/admin", StaticFiles(directory=str(admin_dir), html=True), name="admin-web")


@app.get("/", include_in_schema=False, response_model=None)
def root():
    if admin_dir is not None:
        return RedirectResponse(url="/admin/")
    return {"status": "ok", "service": settings.service_name}
