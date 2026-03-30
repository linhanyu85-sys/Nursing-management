from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, status

from app.core.config import settings
from app.schemas.auth import (
    AdminUserUpsertRequest,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
    UserOut,
)
from app.services.user_store import get_user, list_users, register_user, upsert_user

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
    if str(user.get("status") or "active") != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="account_unavailable")

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=1440)
    return LoginResponse(
        access_token=f"mock_access_{payload.username}",
        refresh_token=f"mock_refresh_{payload.username}",
        expires_at=expires_at,
        user=UserOut(
            id=user["id"],
            username=user.get("username") or payload.username,
            full_name=user["full_name"],
            role_code=user["role_code"],
            phone=user.get("phone"),
            email=user.get("email"),
            department=user.get("department"),
            title=user.get("title"),
            status=user.get("status") or "active",
        ),
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
        user=UserOut(
            id=user["id"],
            username=payload.username,
            full_name=user["full_name"],
            role_code=user["role_code"],
            phone=user.get("phone"),
            email=user.get("email"),
            department=user.get("department"),
            title=user.get("title"),
            status=user.get("status") or "active",
        ),
    )


@router.get("/auth/admin/users", response_model=list[UserOut])
def admin_list_users(query: str = "", status_filter: str | None = None) -> list[UserOut]:
    rows = list_users(query=query, status_filter=status_filter)
    return [
        UserOut(
            id=item["id"],
            username=item.get("username"),
            full_name=item["full_name"],
            role_code=item["role_code"],
            phone=item.get("phone"),
            email=item.get("email"),
            department=item.get("department"),
            title=item.get("title"),
            status=item.get("status") or "active",
        )
        for item in rows
    ]


@router.post("/auth/admin/users/upsert", response_model=UserOut)
def admin_upsert_user(payload: AdminUserUpsertRequest) -> UserOut:
    item = upsert_user(
        username=payload.username,
        full_name=payload.full_name,
        role_code=payload.role_code,
        password=payload.password,
        phone=payload.phone,
        email=payload.email,
        department=payload.department,
        title=payload.title,
        status=payload.status,
    )
    return UserOut(
        id=item["id"],
        username=item.get("username"),
        full_name=item["full_name"],
        role_code=item["role_code"],
        phone=item.get("phone"),
        email=item.get("email"),
        department=item.get("department"),
        title=item.get("title"),
        status=item.get("status") or "active",
    )
