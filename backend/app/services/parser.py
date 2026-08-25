from __future__ import annotations

from pathlib import Path


SUPPORTED_FORMATS = {".txt", ".md", ".markdown"}


def decode_bytes(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="ignore")


def parse_text_file(filename: str, payload: bytes) -> tuple[str, str]:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_FORMATS:
        raise ValueError("第一版原型仅支持 TXT、Markdown 文档解析，PDF/DOCX 已预留扩展接口。")
    return decode_bytes(payload), suffix.lstrip(".")


def clean_sections(text: str) -> list[str]:
    sections: list[str] = []
    buffer: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#") and buffer:
            sections.append(" ".join(buffer))
            buffer = [line.lstrip("#").strip()]
        else:
            buffer.append(line)
    if buffer:
        sections.append(" ".join(buffer))
    return sections
