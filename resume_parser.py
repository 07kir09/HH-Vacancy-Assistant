from __future__ import annotations

from pathlib import Path


class ResumeParseError(RuntimeError):
    pass


def extract_text(path: str | Path) -> str:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(file_path)
    if suffix == ".docx":
        return _extract_docx(file_path)
    if suffix in {".txt", ".md"}:
        return file_path.read_text(encoding="utf-8", errors="ignore")
    raise ResumeParseError(f"Unsupported resume format: {suffix}. Use PDF, DOCX or TXT.")


def _extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ResumeParseError("PDF parsing requires pypdf. Run: pip install -r requirements.txt") from exc

    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    text = "\n".join(parts).strip()
    if not text:
        raise ResumeParseError("Could not extract text from PDF. OCR is not implemented yet.")
    return text


def _extract_docx(path: Path) -> str:
    try:
        from docx import Document
    except ImportError as exc:
        raise ResumeParseError("DOCX parsing requires python-docx. Run: pip install -r requirements.txt") from exc

    document = Document(str(path))
    parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    text = "\n".join(parts).strip()
    if not text:
        raise ResumeParseError("Could not extract text from DOCX.")
    return text
