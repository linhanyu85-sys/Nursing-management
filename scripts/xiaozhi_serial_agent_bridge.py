#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass
from typing import Any

import requests
import serial


LOG_FILTER_PATTERNS = (
    r"^\(\d+\)\s+",  # ESP-IDF style logs
    r"\bSystemInfo\b",
    r"\bfree\s+sram\b",
    r"\bheap\b",
    r"\bstack\b",
    r"\bwifi\b",
    r"\bboot\b",
    r"\berror:\b",
    r"\bwarn(ing)?\b",
    r"\binfo:\b",
    r"\bxiaoyi_evt:",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Xiaozhi serial bridge: COM text -> AI Agent chat endpoint."
    )
    parser.add_argument("--port", default="COM5", help="Serial port, default COM5")
    parser.add_argument("--baud", type=int, default=115200, help="Serial baudrate")
    parser.add_argument("--api-base", default="http://127.0.0.1:8000", help="API gateway base URL")
    parser.add_argument("--department-id", default="dep-card-01", help="Default department id/code")
    parser.add_argument("--user-id", default="linmeili", help="Requester user id or username")
    parser.add_argument(
        "--write-back",
        action="store_true",
        help="Write AI result back to serial (off by default for safety)",
    )
    parser.add_argument("--read-timeout", type=float, default=1.0, help="Serial read timeout seconds")
    parser.add_argument("--retry-sec", type=float, default=2.5, help="Reconnect interval seconds")
    parser.add_argument("--show-raw", action="store_true", help="Print all raw serial lines")
    parser.add_argument("--wake-word", default="小医小医", help="Wake word")
    parser.add_argument("--sleep-word", default="休眠", help="Sleep command")
    parser.add_argument("--concise-tts", action="store_true", help="Use concise brief text for TTS")
    return parser.parse_args()


@dataclass
class BridgeConfig:
    port: str
    baud: int
    api_base: str
    department_id: str
    user_id: str
    write_back: bool
    read_timeout: float
    retry_sec: float
    show_raw: bool
    wake_word: str
    sleep_word: str
    concise_tts: bool



def _is_log_line(raw: str) -> bool:
    low = raw.lower()
    for p in LOG_FILTER_PATTERNS:
        if re.search(p, low):
            return True
    return False



def _extract_from_json_obj(obj: dict[str, Any]) -> str | None:
    # direct keys
    for key in (
        "text",
        "query",
        "content",
        "asr",
        "stt",
        "transcript",
        "recognized_text",
        "utterance",
        "message",
    ):
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    # nested payload
    payload = obj.get("payload")
    if isinstance(payload, dict):
        for key in ("text", "content", "stt", "transcript", "message"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    return None



def extract_text(line: str) -> str | None:
    raw = line.strip()
    if not raw:
        return None

    if _is_log_line(raw):
        return None

    # JSON line mode: {"text":"..."} / MCP-like message
    if raw.startswith("{") and raw.endswith("}"):
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                text = _extract_from_json_obj(obj)
                if text:
                    return text
        except Exception:
            pass

    # Prefix mode: ASR: xxx / TEXT: xxx
    for prefix in ("ASR:", "TEXT:", "QUERY:", "INPUT:", "STT:"):
        if raw.upper().startswith(prefix):
            text = raw[len(prefix) :].strip()
            if text:
                return text

    # Plain text mode (strict): must look like a natural query
    if len(raw) < 2 or len(raw) > 240:
        return None
    if not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", raw):
        return None
    return raw


def parse_xiaozhi_event(line: str) -> tuple[str, str] | None:
    raw = line.strip()
    if not raw:
        return None
    m = re.search(r"XIAOYI_EVT:\s*([A-Za-z_]+)\s*:\s*(.*)$", raw, re.IGNORECASE)
    if m:
        kind = m.group(1).strip().lower()
        payload = (m.group(2) or "").strip() or "-"
        mapped = {"wake": "wake", "stt": "stt", "tts": "tts", "state": "state"}.get(kind)
        if mapped:
            return (mapped, payload)
    m = re.search(r"Wake word detected:\s*(.+)$", raw, re.IGNORECASE)
    if m and m.group(1).strip():
        return ("wake", m.group(1).strip())
    m = re.search(r">>\s*(.+)$", raw)
    if m and m.group(1).strip():
        return ("stt", m.group(1).strip())
    m = re.search(r"<<\s*(.+)$", raw)
    if m and m.group(1).strip():
        return ("tts", m.group(1).strip())
    if raw.startswith("{") and raw.endswith("}"):
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                t = str(obj.get("type") or "").strip().lower()
                if t == "stt":
                    text = str(obj.get("text") or "").strip()
                    if text:
                        return ("stt", text)
                if t == "tts":
                    text = str(obj.get("text") or "").strip()
                    if text:
                        return ("tts", text)
                if t == "listen" and str(obj.get("state") or "").strip().lower() == "detect":
                    text = str(obj.get("text") or "").strip() or "唤醒词"
                    return ("wake", text)
        except Exception:
            pass
    return None



def extract_bed_no(text: str) -> str | None:
    m = re.search(r"(\d{1,3})\s*(床|号床|床位)", text)
    if m:
        return m.group(1)
    m2 = re.search(r"^\s*(\d{1,3})(?=\D|$)", text)
    if m2:
        return m2.group(1)
    return None



def api_get(url: str, params: dict[str, Any] | None = None, timeout: float = 8.0) -> Any:
    resp = requests.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()



def api_post(url: str, payload: dict[str, Any], timeout: float = 45.0) -> Any:
    resp = requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()



def resolve_patient_id(api_base: str, department_id: str, query_text: str) -> tuple[str | None, str | None]:
    bed_no = extract_bed_no(query_text)
    if not bed_no:
        return None, None

    try:
        beds = api_get(f"{api_base}/api/wards/{department_id}/beds")
        if isinstance(beds, list):
            for item in beds:
                if str(item.get("bed_no") or "") == bed_no:
                    patient_id = item.get("current_patient_id")
                    if isinstance(patient_id, str) and patient_id:
                        return patient_id, bed_no
    except Exception:
        pass
    return None, bed_no



def run_agent(config: BridgeConfig, query_text: str) -> dict[str, Any]:
    patient_id, bed_no = resolve_patient_id(config.api_base, config.department_id, query_text)
    requested_by = config.user_id if str(config.user_id).startswith("u_") else f"u_{config.user_id}"
    body = {
        "mode": "agent_cluster",
        "cluster_profile": "nursing_default_cluster",
        "department_id": config.department_id,
        "patient_id": patient_id,
        "bed_no": bed_no,
        "user_input": query_text,
        "requested_by": requested_by,
        "attachments": [],
    }
    return api_post(f"{config.api_base}/api/ai/chat", body, timeout=60.0)


def normalize_output_text(text: str) -> str:
    cleaned = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"^\s*#{1,6}\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"\*(.*?)\*", r"\1", cleaned)
    cleaned = re.sub(r"`([^`]*)`", r"\1", cleaned)
    cleaned = re.sub(r"^\s*[-*]\s+", "• ", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def build_brief(summary: str, findings: list[Any] | None, recommendations: list[Any] | None) -> str:
    text = normalize_output_text(summary)
    lines = [line.strip().strip("•").strip() for line in text.splitlines() if line.strip()]
    chunks: list[str] = []
    if lines:
        chunks.append(lines[0])
    if findings:
        chunks.append(f"发现：{str(findings[0]).strip()}")
    if recommendations:
        first = recommendations[0]
        if isinstance(first, dict):
            title = str(first.get("title") or first.get("action") or "").strip()
        else:
            title = str(first).strip()
        if title:
            chunks.append(f"建议：{title}")
    if not chunks:
        chunks = [text[:60] or "已完成分析，请查看详情。"]
    out = "；".join(chunks)
    out = re.sub(r"\s+", " ", out).strip("；;。,. ")
    if len(out) > 90:
        out = out[:88].rstrip() + "…"
    return f"重点：{out}。"



def write_line_safe(ser: serial.Serial, line: str) -> None:
    payload = (line.strip() + "\n").encode("utf-8", errors="ignore")
    ser.write(payload)
    ser.flush()



def bridge_loop(config: BridgeConfig) -> None:
    voice_awake = False
    while True:
        try:
            print(f"[bridge] opening {config.port} @ {config.baud}")
            with serial.Serial(config.port, config.baud, timeout=config.read_timeout) as ser:
                print("[bridge] serial connected")
                if config.write_back:
                    write_line_safe(ser, "AGENT_BRIDGE_READY")

                while True:
                    raw = ser.readline()
                    if not raw:
                        continue

                    line = raw.decode("utf-8", errors="ignore").strip()
                    if not line:
                        continue

                    if config.show_raw:
                        print(f"[raw] {line}")

                    ev = parse_xiaozhi_event(line)
                    if ev is not None:
                        kind, payload = ev
                        if kind == "wake":
                            voice_awake = True
                            print(f"[voice] wake_event: {payload}")
                            continue
                        if kind == "tts":
                            print(f"[device_tts] {payload}")
                            continue
                        if kind == "stt":
                            voice_awake = True
                            text = payload
                        else:
                            text = None
                    else:
                        text = extract_text(line)
                    if not text:
                        continue

                    if config.sleep_word and config.sleep_word in text:
                        voice_awake = False
                        print("[voice] sleep")
                        if config.write_back:
                            write_line_safe(ser, "TTS:收到，已休眠。")
                        continue

                    if config.wake_word and config.wake_word in text:
                        voice_awake = True
                        remain = text.replace(config.wake_word, " ").strip(" ，,。.!！?？")
                        if not remain:
                            print("[voice] wake")
                            if config.write_back:
                                write_line_safe(ser, "TTS:我在，请讲。")
                            continue
                        text = remain
                        print(f"[voice] wake+query: {text}")
                    elif not voice_awake:
                        print(f"[voice] sleeping_ignore: {text}")
                        continue

                    print(f"[serial] {text}")
                    try:
                        result = run_agent(config, text)
                        summary = normalize_output_text(str(result.get("summary") or "").strip())
                        findings = result.get("findings") if isinstance(result.get("findings"), list) else []
                        recommendations = result.get("recommendations") if isinstance(result.get("recommendations"), list) else []
                        brief = build_brief(summary, findings, recommendations)
                        confidence = result.get("confidence")
                        review_required = result.get("review_required")
                        out_obj = {
                            "ok": True,
                            "summary": summary,
                            "brief": brief,
                            "confidence": confidence,
                            "review_required": review_required,
                        }
                        out_line = json.dumps(out_obj, ensure_ascii=False)
                        print(f"[agent] {out_line}")
                        if config.write_back:
                            write_line_safe(ser, out_line)
                            tts_line = brief if config.concise_tts else summary
                            write_line_safe(ser, f"TTS:{tts_line}")
                    except Exception as exc:
                        err_obj = {"ok": False, "error": str(exc)}
                        err_line = json.dumps(err_obj, ensure_ascii=False)
                        print(f"[agent_error] {err_line}")
                        if config.write_back:
                            write_line_safe(ser, err_line)
        except Exception as exc:
            print(f"[bridge] disconnected: {exc}")
            time.sleep(max(config.retry_sec, 0.5))



def main() -> None:
    args = parse_args()
    config = BridgeConfig(
        port=args.port,
        baud=args.baud,
        api_base=args.api_base.rstrip("/"),
        department_id=args.department_id,
        user_id=args.user_id,
        write_back=bool(args.write_back),
        read_timeout=float(args.read_timeout),
        retry_sec=float(args.retry_sec),
        show_raw=bool(args.show_raw),
        wake_word=args.wake_word.strip(),
        sleep_word=args.sleep_word.strip(),
        concise_tts=bool(args.concise_tts),
    )
    print("[bridge] start")
    print(f"[bridge] api_base={config.api_base}")
    print(f"[bridge] department_id={config.department_id}")
    print(f"[bridge] write_back={config.write_back}")
    bridge_loop(config)


if __name__ == "__main__":
    main()
