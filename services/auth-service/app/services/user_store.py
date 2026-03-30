from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any


_DEFAULT_USERS: dict[str, dict[str, Any]] = {
    "nurse01": {
        "password": "123456",
        "id": "u_nurse_01",
        "username": "nurse01",
        "full_name": "张护士",
        "role_code": "nurse",
        "department": "心内一病区",
        "title": "责任护士",
        "status": "active",
    },
    "doctor01": {
        "password": "123456",
        "id": "u_doctor_01",
        "username": "doctor01",
        "full_name": "李医生",
        "role_code": "doctor",
        "department": "心内一病区",
        "title": "主治医师",
        "status": "active",
    },
}

_LOCK = Lock()
_LOADED = False
_STORE: dict[str, dict[str, Any]] = {}
_STORE_FILE = Path(__file__).resolve().parents[2] / "data" / "mock_users.json"


def _normalize_user(raw: dict[str, Any], username: str) -> dict[str, Any]:
    return {
        "password": str(raw.get("password") or ""),
        "id": str(raw.get("id") or f"u_{username}"),
        "username": username,
        "full_name": str(raw.get("full_name") or username),
        "role_code": str(raw.get("role_code") or "nurse"),
        "phone": str(raw.get("phone") or "") or None,
        "email": str(raw.get("email") or "") or None,
        "department": str(raw.get("department") or "") or None,
        "title": str(raw.get("title") or "") or None,
        "status": str(raw.get("status") or "active") or "active",
    }


def _load_store_unlocked() -> None:
    global _LOADED, _STORE
    if _LOADED:
        return

    base = {k: _normalize_user(v, k) for k, v in _DEFAULT_USERS.items()}
    if _STORE_FILE.exists():
        try:
            parsed = json.loads(_STORE_FILE.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                for username, raw in parsed.items():
                    if isinstance(username, str) and isinstance(raw, dict):
                        base[username] = _normalize_user(raw, username)
        except Exception:
            # 本地开发容错：文件损坏时保留默认账号继续可登录
            pass

    _STORE = base
    _LOADED = True


def _save_store_unlocked() -> None:
    _STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STORE_FILE.write_text(
        json.dumps(_STORE, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


def get_user(username: str) -> dict[str, Any] | None:
    with _LOCK:
        _load_store_unlocked()
        user = _STORE.get(username)
        if user is None:
            return None
        return dict(user)


def list_users(*, query: str = "", status_filter: str | None = None) -> list[dict[str, Any]]:
    with _LOCK:
        _load_store_unlocked()
        q = (query or "").strip().lower()
        status_value = (status_filter or "").strip().lower()
        rows: list[dict[str, Any]] = []
        for username, user in _STORE.items():
            if status_value and str(user.get("status") or "").lower() != status_value:
                continue
            joined = " ".join(
                [
                    username,
                    str(user.get("full_name") or ""),
                    str(user.get("role_code") or ""),
                    str(user.get("department") or ""),
                    str(user.get("title") or ""),
                    str(user.get("phone") or ""),
                    str(user.get("email") or ""),
                ]
            ).lower()
            if q and q not in joined:
                continue
            rows.append(dict(user))
        rows.sort(key=lambda item: (str(item.get("role_code") or ""), str(item.get("full_name") or "")))
        return rows


def register_user(
    *,
    username: str,
    password: str,
    full_name: str,
    role_code: str = "nurse",
    phone: str | None = None,
) -> dict[str, Any] | None:
    with _LOCK:
        _load_store_unlocked()
        if username in _STORE:
            return None

        user = _normalize_user(
            {
                "password": password,
                "id": f"u_{username}",
                "full_name": full_name,
                "role_code": role_code or "nurse",
                "phone": phone,
            },
            username=username,
        )
        _STORE[username] = user
        _save_store_unlocked()
        return dict(user)


def upsert_user(
    *,
    username: str,
    full_name: str,
    role_code: str = "nurse",
    password: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    department: str | None = None,
    title: str | None = None,
    status: str = "active",
) -> dict[str, Any]:
    with _LOCK:
        _load_store_unlocked()
        existing = dict(_STORE.get(username) or {})
        normalized = _normalize_user(
            {
                "password": password if password is not None and str(password).strip() else existing.get("password", "123456"),
                "id": existing.get("id") or f"u_{username}",
                "full_name": full_name,
                "role_code": role_code or existing.get("role_code") or "nurse",
                "phone": phone if phone is not None else existing.get("phone"),
                "email": email if email is not None else existing.get("email"),
                "department": department if department is not None else existing.get("department"),
                "title": title if title is not None else existing.get("title"),
                "status": status or existing.get("status") or "active",
            },
            username=username,
        )
        _STORE[username] = normalized
        _save_store_unlocked()
        return dict(normalized)
