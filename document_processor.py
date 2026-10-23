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

CHAPTER_RE = re.compile(
    r"(?i)\bCHAPTER\s+([IVXLCDM]+|\d+[A-Z]?)\b"
)
SECTION_PATTERNS = (
    re.compile(
        r"(?i)(?:^|\s)(?:Section|Sec\.?|Article|Art\.?|धारा|अनुच्छेद|సెక్షన్|ఆర్టికల్)\s+(\d{1,3}[A-Za-z]?)\s*[.\-–:]?\s*([^\n]{0,160})"
    ),
    # Many Indian Acts print section headings as “10. What agreements are
    # contracts” without the word “Section”. Requiring a line start and a
    # capitalized title avoids treating subsection numbers and dates as Acts.
    re.compile(r"(?<![\w.])(\d{1,3}[A-Za-z]?)\.\s+([A-Z][^.\n—–:?!\ufffd]{2,160})"),
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
    headings = [event for event in structure_headings(text) if event[1] in {"section", "article"}]
    if not headings:
        return "unknown", ""
    _, _, number, title = headings[0]
    if len(title) > 120:
        title = title[:117] + "..."
    return number, title


def clean_heading_title(value: str) -> str:
    title = re.sub(r"\s+", " ", value or "").strip()
    title = re.split(r"\s+[—–-]\s*|[.?!\ufffd]", title, maxsplit=1)[0]
    return title.strip(" .?!-–—")


def structure_headings(text: str) -> list[tuple[int, str, str, str]]:
    """Return ordered chapter/section headings detected in extracted Act text."""
    events: list[tuple[int, str, str, str]] = []
    section_positions = [match.start() for pattern in SECTION_PATTERNS for match in pattern.finditer(text or "")]
    for match in CHAPTER_RE.finditer(text or ""):
        following_section = min((position for position in section_positions if position > match.end()), default=None)
        raw_title = (text or "")[match.end():following_section] if following_section is not None else (text or "")[match.end():match.end() + 160]
        title = re.sub(r"\s+", " ", raw_title.strip())[:160]
        if not title:
            following = []
            for line in (text or "")[match.end():].splitlines()[:4]:
                line = re.sub(r"\s+", " ", line).strip()
                if not line or line.casefold() in {"sections", "section"}:
                    continue
                letters = [character for character in line if character.isalpha()]
                if letters and sum(character.isupper() for character in letters) / len(letters) >= 0.75:
                    following.append(line)
                else:
                    break
            title = " ".join(following)[:160]
        events.append((match.start(), "chapter", match.group(1).strip(), title))
    for pattern in SECTION_PATTERNS:
        for match in pattern.finditer(text or ""):
            prefix = (text or "")[max(0, match.start() - 24):match.start()]
            is_article_heading = bool(re.match(
                r"\s*(?:article|art\.?|अनुच्छेद|ఆర్టికల్)", match.group(0), re.IGNORECASE
            )) or bool(re.search(r"(?:article|art\.?|अनुच्छेद|ఆర్టికల్)\s*$", prefix, re.IGNORECASE))
            # The numeric fallback also sees the number inside “Article 21.”;
            # keep the explicit heading classification instead of downgrading it.
            if is_article_heading and not re.match(r"\s*(?:article|art\.?|अनुच्छेद|ఆర్టికల్)", match.group(0), re.IGNORECASE):
                continue
            provision_type = "article" if is_article_heading else "section"
            title = clean_heading_title(match.group(2) or "")[:160]
            if provision_type == "section" and re.match(
                r"(?i)(?:for the statement of objects|subs?\.? by act|ins\.? by act|"
                r"omitted by act|the words .* omitted|the enactments mentioned|see gazette|vide act)",
                title,
            ):
                continue
            events.append((match.start(), provision_type, match.group(1).strip(), title))
    # Explicit and bare patterns may both detect a labelled heading.
    unique: dict[tuple[int, str, str], tuple[int, str, str, str]] = {}
    for event in events:
        unique[(event[0], event[1], event[2])] = event
    return sorted(unique.values(), key=lambda event: event[0])


def is_contents_page(text: str) -> bool:
    """Detect section indexes so their numbered entries are not cited as provisions."""
    sample = (text or "")[:700]
    if re.search(r"arrangement\s+of\s+sections|table\s+of\s+contents|\bcontents\b", sample, re.IGNORECASE):
        return True
    section_index = re.search(r"(?im)^\s*SECTIONS\s*$", sample)
    return bool(section_index and len(structure_headings(text)) >= 3)


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
    current_section, current_section_title, current_provision_type = "unknown", "", "section"
    current_chapter, current_chapter_title = "", ""
    for page_no, page_text in pages:
        contents_page = is_contents_page(page_text)
        headings = [] if contents_page else structure_headings(page_text)
        if contents_page:
            current_section, current_section_title = "unknown", "Arrangement of Sections"
            current_chapter, current_chapter_title = "", ""
        section_events = [event for event in headings if event[1] in {"section", "article"}]
        segment_starts = [0] + [event[0] for event in section_events[1:]]
        segment_ends = segment_starts[1:] + [len(page_text)]
        offset = 0
        for segment_start, segment_end in zip(segment_starts, segment_ends):
            segment = page_text[segment_start:segment_end]
            parts = chunk_text(segment) if segment else []
            cursor = segment_start
            for part in parts:
                part_start = page_text.find(part, cursor)
                if part_start < 0 or part_start >= segment_end:
                    part_start = cursor
                part_end = min(segment_end, part_start + len(part))
                cursor = part_end
                for heading_start, kind, number, title in headings:
                    if heading_start >= part_end:
                        break
                    if kind == "chapter":
                        current_chapter = number
                        current_chapter_title = title
                    else:
                        current_section = number
                        current_section_title = title
                        current_provision_type = kind
                chunk_key = hashlib.sha256(
                    f"{meta['document_id']}|{page_no}|{offset}|{part}".encode("utf-8")
                ).hexdigest()
                chunks.append(
                    {
                        "chunk_key": chunk_key,
                        "document_id": meta["document_id"],
                        "act_name": meta.get("act_name") or "",
                        "section_number": current_section,
                        "section_title": current_section_title or meta.get("section_title") or "",
                        "provision_type": current_provision_type,
                        "chapter": current_chapter,
                        "chapter_title": current_chapter_title,
                        "page_number": str(page_no),
                        "original_filename": meta.get("original_filename") or "",
                        "source_url": meta.get("source_url") or "",
                        "language": meta.get("language") or "en",
                        "verification_status": meta.get("verification_status") or "unverified_upload",
                        "text": part,
                    }
                )
                offset += 1
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

        existing_doc = self.db.get_document(document_id) if document_id else None
        if document_id and not existing_doc:
            raise DocumentProcessingError("The document to update was not found.", "missing")

        existing_by_hash = self.db.find_document_by_hash(digest)
        if existing_by_hash:
            if not document_id:
                raise DocumentProcessingError(
                    "This exact PDF has already been added to the knowledge base.", "duplicate"
                )
            if str(existing_by_hash["id"]) != str(document_id):
                raise DocumentProcessingError(
                    "This exact PDF matches a different document already in the knowledge base.", "duplicate"
                )

        # Extract and validate text in-memory before modifying the database or disk.
        # If extraction fails, any existing indexed document remains completely intact.
        pages = extract_pages(data)
        combined = "\n".join(t for _, t in pages).strip()
        if len(combined) < MIN_EXTRACT_CHARS:
            raise DocumentProcessingError(
                "Very little text was extracted. This may be a scanned or image-only PDF. "
                "OCR is not implemented in this application; provide a text-based PDF.",
                "ocr_needed",
            )

        doc_id = document_id or str(uuid.uuid4())
        stored_name = safe_filename(filename, digest)

        resolved_act_name = (
            (act_name or "").strip()
            or (existing_doc.get("act_name") if existing_doc else "")
            or Path(filename).stem
        )
        resolved_source_url = (
            (source_url or "").strip()
            or (existing_doc.get("source_url") if existing_doc else "")
        )
        resolved_version = (
            (version_or_date or "").strip()
            or (existing_doc.get("version_or_date") if existing_doc else "")
        )
        resolved_language = language or (existing_doc.get("language") if existing_doc else "en")
        verification_status = (
            existing_doc.get("verification_status") if existing_doc else "unverified_upload"
        )

        candidate_meta = {
            "document_id": doc_id,
            "act_name": resolved_act_name,
            "source_url": resolved_source_url,
            "language": resolved_language,
            "verification_status": verification_status,
            "original_filename": Path(filename).name,
        }

        chunks = pages_to_chunks(pages, candidate_meta)
        if not chunks:
            raise DocumentProcessingError("No usable text chunks were produced.", "ocr_needed")

        # Write the content-addressed file only after extraction and chunking have
        # succeeded, then replace its database row and chunks in one transaction.
        # Updates use a new hash-derived filename, so the old PDF remains intact
        # until the new file and index are ready.
        dest = self.uploads_dir / stored_name
        existed_before = dest.exists()
        try:
            dest.write_bytes(data)

            record = {
                "id": doc_id,
                "document_id": doc_id,
                "original_filename": Path(filename).name,
                "stored_filename": stored_name,
                "act_name": resolved_act_name,
                "source_url": resolved_source_url,
                "language": resolved_language,
                "version_or_date": resolved_version,
                "upload_date": utc_now(),
                "file_hash": digest,
                "extraction_status": "ok",
                "verification_status": verification_status,
                "indexing_status": "indexed",
                "processing_error": None,
                "page_count": len(pages),
                "chunk_count": len(chunks),
                "active": 1,
            }

            self.db.save_document_index(record, chunks)
        except Exception:
            if not existed_before:
                # The record transaction rolled back; remove the new orphan file.
                dest.unlink(missing_ok=True)
            raise
        logger.info("Indexed document %s with %s chunks", doc_id, len(chunks))
        return record

    def reprocess(self, document_id: str) -> dict[str, Any]:
        doc = self.db.get_document(document_id)
        if not doc or not doc.get("active"):
            raise DocumentProcessingError("Document not found.", "missing")
        path = self.uploads_dir / doc["stored_filename"]
        if not path.exists() and getattr(self.db, "library_db", None):
            path = self.db.library_db.uploads_dir / doc["stored_filename"]
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
