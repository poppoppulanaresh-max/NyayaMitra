from __future__ import annotations

import pytest

from document_processor import DocumentProcessingError
from tests.pdf_builder import blank_pdf_bytes, encrypted_pdf_bytes, text_pdf_bytes


def test_valid_text_pdf(processor, rag):
    data = text_pdf_bytes("Section 3 Right to information. All citizens shall have the right to information. " * 8)
    record = processor.ingest("rti_test.pdf", data, act_name="RTI Test Fixture", source_url="https://example.test/not-official")
    assert record["extraction_status"] == "ok"
    assert record["indexing_status"] == "indexed"
    assert record["chunk_count"] >= 1
    assert record["verification_status"] == "unverified_upload"
    rag.reload()
    hits = rag.search("right to information")
    assert hits
    assert hits[0]["section_number"] in {"3", "unknown"}


def test_empty_pdf(processor):
    with pytest.raises(DocumentProcessingError) as exc:
        processor.ingest("empty.pdf", blank_pdf_bytes())
    assert exc.value.code in {"ocr_needed", "insufficient_text", "empty_file"}


def test_corrupt_pdf(processor):
    with pytest.raises(DocumentProcessingError) as exc:
        processor.ingest("bad.pdf", b"%PDF-1.4\nthis is not a valid pdf body")
    assert exc.value.code in {"corrupt", "invalid_type", "ocr_needed"}


def test_encrypted_pdf(processor):
    with pytest.raises(DocumentProcessingError) as exc:
        processor.ingest("enc.pdf", encrypted_pdf_bytes())
    assert exc.value.code in {"encrypted", "corrupt", "ocr_needed"}


def test_scanned_or_no_text(processor):
    with pytest.raises(DocumentProcessingError) as exc:
        processor.ingest("scan.pdf", blank_pdf_bytes())
    assert exc.value.code in {"ocr_needed", "insufficient_text", "empty_file"}
    assert "OCR" in str(exc.value) or "text" in str(exc.value).lower()


def test_duplicate_upload(processor):
    data = text_pdf_bytes("Unique fixture statute language for duplicate detection. " * 10)
    processor.ingest("dup.pdf", data, act_name="Dup Act")
    with pytest.raises(DocumentProcessingError) as exc:
        processor.ingest("dup.pdf", data, act_name="Dup Act")
    assert exc.value.code == "duplicate"


def test_invalid_and_large_file(processor, monkeypatch):
    with pytest.raises(DocumentProcessingError) as exc:
        processor.ingest("notes.txt", b"not a pdf")
    assert exc.value.code == "invalid_type"
    monkeypatch.setattr("document_processor.MAX_UPLOAD_BYTES", 20)
    with pytest.raises(DocumentProcessingError) as exc2:
        processor.ingest("big.pdf", b"%PDF-1.4" + b"x" * 50)
    assert exc2.value.code == "too_large"


def test_remove_and_reindex(processor, rag):
    data = text_pdf_bytes("Section 99 Test Removal Clause unique zebra token. " * 10)
    record = processor.ingest("remove_me.pdf", data, act_name="Removal Act")
    rag.reload()
    assert any("zebra" in (h.get("text") or "").lower() for h in rag.search("zebra token"))
    processor.remove(record["id"])
    rag.reload()
    assert all(h.get("document_id") != record["id"] for h in rag.search("zebra token"))
    assert rag.db.get_document(record["id"])["active"] == 0
