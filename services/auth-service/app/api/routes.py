from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, status

from app.core.config import settings
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
    UserOut,
)
from app.services.user_store import get_user, register_user

router = APIRouter()


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


@router.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest) -> LoginResponse:
    user = get_user(payload.username)
    if user is None or user["password"] != payload.password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=1440)
    return LoginResponse(
        access_token=f"mock_access_{payload.username}",
        refresh_token=f"mock_refresh_{payload.username}",
        expires_at=expires_at,
        user=UserOut(id=user["id"], full_name=user["full_name"], role_code=user["role_code"]),
    )


@router.post("/auth/register", response_model=RegisterResponse)
def register(payload: RegisterRequest) -> RegisterResponse:
    user = register_user(
        username=payload.username,
        password=payload.password,
        full_name=payload.full_name,
        role_code=payload.role_code,
        phone=payload.phone,
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="username_exists")
    return RegisterResponse(
        ok=True,
        user=UserOut(id=user["id"], full_name=user["full_name"], role_code=user["role_code"]),
    )
