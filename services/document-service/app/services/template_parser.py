from __future__ import annotations

import base64
import io
import re
import zipfile

from app.schemas.document import TemplateImportRequest


def _safe_decode_text(raw: bytes) -> str:
    for encoding in ("utf-8", "gb18030", "latin-1"):
        try:
            return raw.decode(encoding)
        except Exception:
            continue
    return raw.decode("utf-8", errors="ignore")


def _extract_docx_text(raw: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            xml = zf.read("word/document.xml")
    except Exception:
        return ""

    text = _safe_decode_text(xml)
    text = re.sub(r"<w:tab[^>]*/>", "\t", text)
    text = re.sub(r"</w:p>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def parse_template_import(payload: TemplateImportRequest) -> tuple[str, str]:
    name = (payload.name or "").strip()

    if payload.template_text and payload.template_text.strip():
        if not name:
            name = "导入模板"
        return name, payload.template_text.strip()

    if not payload.template_base64:
        raise ValueError("template_content_missing")

    try:
        raw = base64.b64decode(payload.template_base64)
    except Exception as exc:
        raise ValueError("template_base64_invalid") from exc

    file_name = (payload.file_name or "").lower()
    mime_type = (payload.mime_type or "").lower()

    extracted = ""
    if file_name.endswith(".docx") or "officedocument.wordprocessingml.document" in mime_type:
        extracted = _extract_docx_text(raw)
    elif (
        file_name.endswith(".txt")
        or file_name.endswith(".md")
        or file_name.endswith(".json")
        or file_name.endswith(".xml")
        or "text/" in mime_type
    ):
        extracted = _safe_decode_text(raw)
    else:
        extracted = _safe_decode_text(raw)

    extracted = extracted.strip()
    if not extracted:
        raise ValueError("template_parse_failed")

    if not name:
        name = payload.file_name or "导入模板"
    return name, extracted
