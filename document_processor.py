"""PDF validation, extraction, metadata, and chunking. OCR is not implemented."""
from __future__ import annotations

import hashlib
import io
import logging
import re
import uuid
from pathlib import Path
from typing import Any

from config import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    MAX_UPLOAD_BYTES,
    MIN_EXTRACT_CHARS,
    UPLOADS_DIR,
)
from database import Database, utc_now

logger = logging.getLogger("nyaya.document_processor")

SECTION_RE = re.compile(
    r"(?:(?:Section|Sec\.?|धारा|సెక్షన్)\s+)(\d+[A-Za-z]?)\s*[.\-–:]?\s*([^\n]{0,120})",
    re.IGNORECASE,
)


class DocumentProcessingError(Exception):
    def __init__(self, message: str, code: str = "error"):
        super().__init__(message)
        self.code = code


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_filename(original: str, digest: str) -> str:
    base = Path(original or "document.pdf").name
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    if not cleaned.lower().endswith(".pdf"):
        cleaned += ".pdf"
    if len(cleaned) > 80:
        cleaned = cleaned[:76] + ".pdf"
    return f"{digest[:12]}_{cleaned}"


def validate_upload(filename: str, data: bytes) -> None:
    if not filename or not str(filename).lower().endswith(".pdf"):
        raise DocumentProcessingError("Only PDF files are accepted.", "invalid_type")
    if not data:
        raise DocumentProcessingError("The uploaded file is empty.", "empty_file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise DocumentProcessingError("File exceeds the maximum upload size.", "too_large")
    if not data[:8].startswith(b"%PDF"):
        raise DocumentProcessingError("The file is not a valid PDF header.", "invalid_type")


def normalize_whitespace(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def infer_section(text: str) -> tuple[str, str]:
    match = SECTION_RE.search(text)
    if not match:
        return "unknown", ""
    number = match.group(1).strip()
    title = (match.group(2) or "").strip()
    title = re.sub(r"\s+", " ", title)
    if len(title) > 120:
        title = title[:117] + "..."
    return number, title


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    text = normalize_whitespace(text)
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(length, start + size)
        if end < length:
            window = text[start:end]
            split_at = window.rfind(". ")
            if split_at > size * 0.4:
                end = start + split_at + 1
        part = text[start:end].strip()
        if part:
            chunks.append(part)
        if end >= length:
            break
        start = max(0, end - overlap)
    return chunks


def extract_pages(data: bytes) -> list[tuple[int, str]]:
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError as exc:
        raise DocumentProcessingError("pypdf is not installed.", "dependency") from exc

    try:
        reader = PdfReader(io.BytesIO(data))
    except PdfReadError as exc:
        raise DocumentProcessingError("The PDF is corrupt or unreadable.", "corrupt") from exc
    except Exception as exc:
        raise DocumentProcessingError("The PDF could not be opened.", "corrupt") from exc

    if getattr(reader, "is_encrypted", False):
        try:
            ok = reader.decrypt("")
            if not ok:
                raise DocumentProcessingError("The PDF is encrypted and cannot be opened without a password.", "encrypted")
        except DocumentProcessingError:
            raise
        except Exception as exc:
            raise DocumentProcessingError("The PDF is encrypted and cannot be opened without a password.", "encrypted") from exc

    pages: list[tuple[int, str]] = []
    try:
        for i, page in enumerate(reader.pages, start=1):
            try:
                raw = page.extract_text() or ""
            except Exception:
                raw = ""
            pages.append((i, normalize_whitespace(raw)))
    except Exception as exc:
        raise DocumentProcessingError("Text extraction failed for this PDF.", "extract_failed") from exc
    if not pages:
        raise DocumentProcessingError("The PDF has no pages.", "empty_file")
    return pages


def pages_to_chunks(pages: list[tuple[int, str]], meta: dict[str, Any]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for page_no, page_text in pages:
        parts = chunk_text(page_text) if page_text else []
        for offset, part in enumerate(parts):
            section_number, section_title = infer_section(part)
            chunk_key = hashlib.sha256(
                f"{meta['document_id']}|{page_no}|{offset}|{part}".encode("utf-8")
            ).hexdigest()
            chunks.append(
                {
                    "chunk_key": chunk_key,
                    "document_id": meta["document_id"],
                    "act_name": meta.get("act_name") or "",
                    "section_number": section_number,
                    "section_title": section_title or meta.get("section_title") or "",
                    "page_number": str(page_no),
                    "source_url": meta.get("source_url") or "",
                    "language": meta.get("language") or "en",
                    "verification_status": meta.get("verification_status") or "unverified_upload",
                    "text": part,
                }
            )
    return chunks


class DocumentProcessor:
    def __init__(self, db: Database, uploads_dir: Path | None = None):
        self.db = db
        self.uploads_dir = Path(uploads_dir or UPLOADS_DIR)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)

    def ingest(
        self,
        filename: str,
        data: bytes,
        act_name: str = "",
        source_url: str = "",
        language: str = "en",
        version_or_date: str = "",
        document_id: str | None = None,
    ) -> dict[str, Any]:
        validate_upload(filename, data)
        digest = sha256_bytes(data)
        existing = self.db.find_document_by_hash(digest)
        if existing and not document_id:
            raise DocumentProcessingError("This exact PDF has already been added to the knowledge base.", "duplicate")

        doc_id = document_id or str(uuid.uuid4())
        stored_name = safe_filename(filename, digest)
        dest = self.uploads_dir / stored_name
        dest.write_bytes(data)

        record = {
            "id": doc_id,
            "document_id": doc_id,
            "original_filename": Path(filename).name,
            "stored_filename": stored_name,
            "act_name": (act_name or "").strip() or Path(filename).stem,
            "source_url": (source_url or "").strip(),
            "language": language or "en",
            "version_or_date": (version_or_date or "").strip(),
            "upload_date": utc_now(),
            "file_hash": digest,
            "extraction_status": "pending",
            "verification_status": "unverified_upload",
            "indexing_status": "pending",
            "processing_error": None,
            "page_count": 0,
            "chunk_count": 0,
            "active": 1,
        }
        self.db.upsert_document(record)

        try:
            pages = extract_pages(data)
        except DocumentProcessingError as exc:
            record["extraction_status"] = exc.code
            record["indexing_status"] = "failed"
            record["processing_error"] = str(exc)
            self.db.upsert_document(record)
            raise

        combined = "\n".join(t for _, t in pages).strip()
        if len(combined) < MIN_EXTRACT_CHARS:
            record["extraction_status"] = "insufficient_text"
            record["indexing_status"] = "failed"
            record["page_count"] = len(pages)
            record["processing_error"] = (
                "Very little text was extracted. This may be a scanned or image-only PDF. "
                "OCR is not implemented in this application; provide a text-based PDF."
            )
            self.db.upsert_document(record)
            raise DocumentProcessingError(record["processing_error"], "ocr_needed")

        chunks = pages_to_chunks(pages, record)
        if not chunks:
            record["extraction_status"] = "insufficient_text"
            record["indexing_status"] = "failed"
            record["processing_error"] = "No usable text chunks were produced."
            self.db.upsert_document(record)
            raise DocumentProcessingError(record["processing_error"], "ocr_needed")

        self.db.replace_chunks(doc_id, chunks)
        record["extraction_status"] = "ok"
        record["indexing_status"] = "indexed"
        record["page_count"] = len(pages)
        record["chunk_count"] = len(chunks)
        record["processing_error"] = None
        self.db.upsert_document(record)
        logger.info("Indexed document %s with %s chunks", doc_id, len(chunks))
        return record

    def reprocess(self, document_id: str) -> dict[str, Any]:
        doc = self.db.get_document(document_id)
        if not doc or not doc.get("active"):
            raise DocumentProcessingError("Document not found.", "missing")
        path = self.uploads_dir / doc["stored_filename"]
        if not path.exists():
            raise DocumentProcessingError("Stored PDF file is missing.", "missing_file")
        data = path.read_bytes()
        return self.ingest(
            filename=doc["original_filename"],
            data=data,
            act_name=doc.get("act_name") or "",
            source_url=doc.get("source_url") or "",
            language=doc.get("language") or "en",
            version_or_date=doc.get("version_or_date") or "",
            document_id=document_id,
        )

    def remove(self, document_id: str) -> None:
        self.db.deactivate_document(document_id)
