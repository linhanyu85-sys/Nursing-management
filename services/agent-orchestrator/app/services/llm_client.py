from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.core.config import settings


SYS_MSG = (
    "你是临床护理 AI 助手。"
    "请输出简洁、可执行、以中文为主的结构化结论。"
    "尽量少用技术术语，必须出现专业词时请顺手解释成护士容易理解的话。"
)


async def _do_chat(
    *,
    base: str,
    mdl: str,
    txt: str,
    key: str = "",
    tm: int = 30,
) -> str | None:
    url = base.rstrip('/') + "/chat/completions"
    hdr: dict[str, str] = {"Content-Type": "application/json"}
    if key:
        hdr["Authorization"] = f"Bearer {key}"

    req: dict[str, Any] = {
        "model": mdl,
        "messages": [
            {"role": "system", "content": SYS_MSG},
            {"role": "user", "content": txt},
        ],
        "temperature": 0.2,
    }

    ret = None
    async with httpx.AsyncClient(timeout=tm, trust_env=False) as c:
        try:
            rsp = await c.post(url, headers=hdr, json=req)
            rsp.raise_for_status()
            try:
                body = json.loads(rsp.content.decode("utf-8"))
            except Exception:
                body = rsp.json()
            arr = body.get("choices", [{}])
            first = arr[0] if arr else {}
            msg = first.get("message", {})
            raw = msg.get("content", "")
            s = str(raw).strip()
            if s:
                ret = s
        except Exception:
            pass
    return ret


def _get_json(s: str | None) -> dict[str, Any] | None:
    txt = str(s or "").strip()
    if txt == "":
        return None

    cands: list[str] = [txt]
    pat = r"```(?:json)?\s*(\{.*?\})\s*```"
    found = re.findall(pat, txt, flags=re.DOTALL | re.IGNORECASE)
    for f in found:
        cands.append(f)

    i = txt.find("{")
    j = txt.rfind("}")
    ok = i >= 0 and j > i
    if ok:
        cands.append(txt[i : j + 1])

    ret = None
    for c in cands:
        try:
            obj = json.loads(c)
        except Exception:
            continue
        if isinstance(obj, dict):
            ret = obj
            break
    return ret


def _uniq(*arr: str | None) -> list[str]:
    out: list[str] = []
    dup: set[str] = set()
    for x in arr:
        m = str(x or "").strip()
        if m == "":
            continue
        k = m.lower()
        if k in dup:
            continue
        dup.add(k)
        out.append(m)
    return out


async def local_refine(prompt: str) -> str | None:
    enabled = settings.local_llm_enabled
    if not enabled:
        return None
    mock = settings.mock_mode
    force = settings.llm_force_enable
    if mock and not force:
        return None

    lst = _uniq(settings.local_llm_model_primary, settings.local_llm_model_fallback)
    n = len(lst)
    if n == 0:
        return None

    tm = settings.local_llm_timeout_sec
    per_tm = int(tm / max(1, n))
    if per_tm < 6:
        per_tm = 6
    ret = None
    idx = 0
    while idx < n:
        m = lst[idx]
        idx += 1
        r = await _do_chat(
            base=settings.local_llm_base_url,
            mdl=m,
            txt=prompt,
            key=settings.local_llm_api_key,
            tm=per_tm,
        )
        if r:
            ret = r
            break
    return ret


async def local_refine_with_model(prompt: str, model: str) -> str | None:
    if not settings.local_llm_enabled:
        return None
    mock = settings.mock_mode
    force = settings.llm_force_enable
    if mock and not force:
        return None
    m = model
    if not m:
        return None

    r = await _do_chat(
        base=settings.local_llm_base_url,
        mdl=m,
        txt=prompt,
        key=settings.local_llm_api_key,
        tm=settings.local_llm_timeout_sec,
    )
    return r


async def local_structured_json(
    prompt: str,
    *,
    model: str = "",
    timeout_sec: int | None = None,
) -> dict[str, Any] | None:
    if not settings.local_llm_enabled:
        return None
    mock = settings.mock_mode
    force = settings.llm_force_enable
    if mock and not force:
        return None

    cands = _uniq(
        model,
        settings.local_llm_model_planner,
        settings.local_llm_model_reasoning,
        settings.local_llm_model_primary,
        settings.local_llm_model_fallback,
    )
    n = len(cands)
    if n == 0:
        return None

    tm = timeout_sec
    if tm is None:
        tm = settings.agent_planner_timeout_sec
    ret = None
    i = 0
    while i < n:
        c = cands[i]
        i += 1
        raw = await _do_chat(
            base=settings.local_llm_base_url,
            mdl=c,
            txt=prompt,
            key=settings.local_llm_api_key,
            tm=tm,
        )
        obj = _get_json(raw)
        if obj is not None:
            ret = obj
            break
    return ret


async def probe_local_models() -> dict[str, Any]:
    if not settings.local_llm_enabled:
        return {"enabled": False, "reachable": False, "models": []}

    url = settings.local_llm_base_url.rstrip('/') + "/models"
    hdr: dict[str, str] = {}
    k = settings.local_llm_api_key
    if k:
        hdr["Authorization"] = f"Bearer {k}"

    body = None
    try:
        async with httpx.AsyncClient(timeout=6, trust_env=False) as c:
            rsp = await c.get(url, headers=hdr)
            rsp.raise_for_status()
            body = rsp.json()
    except Exception:
        return {"enabled": True, "reachable": False, "models": []}

    lst: list[str] = []
    arr = body.get("data", []) if isinstance(body, dict) else []
    for x in arr:
        if not isinstance(x, dict):
            continue
        v = x.get("id")
        if not v:
            v = x.get("model")
        nm = str(v or "").strip()
        if nm:
            lst.append(nm)

    return {
        "enabled": True,
        "reachable": True,
        "models": lst,
    }


async def bailian_refine(prompt: str) -> str:
    mock = settings.mock_mode
    force = settings.llm_force_enable
    do_mock = mock and not force
    if do_mock:
        return f"[本地演示模式] {prompt[:220]}"

    r = await local_refine(prompt)
    if r:
        return r

    only_local = settings.local_only_mode
    if only_local:
        msg = "本地回答服务当前不可用，系统已禁止云端回退。"
        msg += "请先启动本地中文模型服务（默认端口 9100），再重新尝试。"
        return msg

    key = settings.bailian_api_key
    if key:
        r2 = await _do_chat(
            base=settings.bailian_base_url,
            mdl=settings.bailian_model_default,
            txt=prompt,
            key=key,
            tm=18,
        )
        if r2:
            return r2

    if not key:
        return f"已收到问题：{prompt[:120]}。当前云端模型未配置，建议先启动本地中文模型服务。"
    return f"已收到问题：{prompt[:120]}。当前模型调用失败，请人工复核后执行。"
