from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException


async def forward_json(meth: str, url: str, *, payload: dict[str, Any] | None = None) -> Any:
    rsp = None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(45, connect=8), trust_env=False) as c:
            rsp = await c.request(meth, url, json=payload)
    except httpx.TimeoutException as e:
        raise HTTPException(status_code=504, detail="upstream_timeout") from e
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail="upstream_unavailable") from e
    code = rsp.status_code
    if code >= 400:
        msg: Any = rsp.text or "upstream_error"
        try:
            obj = rsp.json()
            is_dict = isinstance(obj, dict)
            if is_dict and "detail" in obj:
                msg = obj["detail"]
            else:
                msg = obj
        except Exception:
            pass
        raise HTTPException(status_code=code, detail=msg)
    txt = rsp.text
    if txt:
        try:
            return rsp.json()
        except Exception:
            return {"raw": txt}
    return {}


async def forward_get(url: str, *, params: dict[str, Any] | None = None) -> Any:
    rsp = None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(35, connect=8), trust_env=False) as c:
            rsp = await c.get(url, params=params)
    except httpx.TimeoutException as e:
        raise HTTPException(status_code=504, detail="upstream_timeout") from e
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail="upstream_unavailable") from e
    code = rsp.status_code
    if code >= 400:
        msg: Any = rsp.text or "upstream_error"
        try:
            obj = rsp.json()
            is_dict = isinstance(obj, dict)
            if is_dict and "detail" in obj:
                msg = obj["detail"]
            else:
                msg = obj
        except Exception:
            pass
        raise HTTPException(status_code=code, detail=msg)
    try:
        return rsp.json()
    except Exception:
        return {"raw": rsp.text}
