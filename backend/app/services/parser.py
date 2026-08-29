from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree


SUPPORTED_FORMATS = {".txt", ".md", ".markdown", ".pdf", ".docx", ".pptx"}


def decode_bytes(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="ignore")


def extract_ooxml_text(payload: bytes, prefix: str) -> str:
    import io

    parts: list[str] = []
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = sorted(name for name in archive.namelist() if name.startswith(prefix) and name.endswith(".xml"))
        for name in names:
            root = ElementTree.fromstring(archive.read(name))
            texts = [node.text or "" for node in root.iter() if node.tag.endswith("}t") or node.tag.endswith("}instrText")]
            joined = " ".join(text.strip() for text in texts if text and text.strip())
            if joined:
                parts.append(joined)
    return "\n".join(parts)


def extract_pdf_text(payload: bytes) -> str:
    import io

    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(payload))
        pages = [page.extract_text() or "" for page in reader.pages]
        if sum(len(page.strip()) for page in pages) < max(30, len(pages) * 12):
            pages = _ocr_pdf_pages(payload)
        return "\n\n".join(f"[PAGE {index}]\n{text}" for index, text in enumerate(pages, start=1) if text.strip())
    except Exception:
        fallback = decode_bytes(payload)
        text = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9，。；：、,.?!?()（）#\s-]", " ", fallback)
        return re.sub(r"\s+", " ", text).strip()


def _ocr_pdf_pages(payload: bytes) -> list[str]:
    try:
        import fitz
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise ValueError("该 PDF 可能是扫描件，请安装 requirements-ocr.txt 后启用 OCR") from exc
    engine = RapidOCR()
    document = fitz.open(stream=payload, filetype="pdf")
    pages: list[str] = []
    for page in document:
        pixmap = page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), alpha=False)
        result, _ = engine(pixmap.tobytes("png"))
        lines = [str(item[1]) for item in (result or []) if len(item) > 1]
        pages.append("\n".join(lines))
    document.close()
    return pages


def parse_text_file(filename: str, payload: bytes) -> tuple[str, str]:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_FORMATS:
        raise ValueError("当前支持 TXT、Markdown、PDF、DOCX、PPTX 课程资料解析。")
    if suffix in {".txt", ".md", ".markdown"}:
        return decode_bytes(payload), suffix.lstrip(".")
    if suffix == ".docx":
        return extract_ooxml_text(payload, "word/"), "docx"
    if suffix == ".pptx":
        return extract_ooxml_text(payload, "ppt/slides/"), "pptx"
    return extract_pdf_text(payload), "pdf"


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
