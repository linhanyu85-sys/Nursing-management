from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any


_DEFAULT_USERS: dict[str, dict[str, Any]] = {
    "nurse01": {
        "password": "123456",
        "id": "u_nurse_01",
        "full_name": "张护士",
        "role_code": "nurse",
    },
    "doctor01": {
        "password": "123456",
        "id": "u_doctor_01",
        "full_name": "李医生",
        "role_code": "doctor",
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
        "full_name": str(raw.get("full_name") or username),
        "role_code": str(raw.get("role_code") or "nurse"),
        "phone": str(raw.get("phone") or "") or None,
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
