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


def test_replacement_failure_leaves_original_intact(processor, rag):
    original_data = text_pdf_bytes("Section 10 Initial valid statute content with original antelope keyword. " * 8)
    record = processor.ingest("valid_original.pdf", original_data, act_name="Antelope Act", source_url="https://example.test/antelope")
    assert record["indexing_status"] == "indexed"
    original_id = record["id"]

    # Attempt to replace with corrupt PDF
    with pytest.raises(DocumentProcessingError) as exc_corrupt:
        processor.ingest("corrupt_update.pdf", b"%PDF-1.4\ncorrupt body", document_id=original_id)
    assert exc_corrupt.value.code in {"corrupt", "invalid_type", "ocr_needed"}

    # Attempt to replace with scanned/empty PDF
    with pytest.raises(DocumentProcessingError) as exc_scan:
        processor.ingest("scanned_update.pdf", blank_pdf_bytes(), document_id=original_id)
    assert exc_scan.value.code == "ocr_needed"

    # Original document record and chunks must remain active and indexed
    doc_after_failures = processor.db.get_document(original_id)
    assert doc_after_failures["indexing_status"] == "indexed"
    assert doc_after_failures["extraction_status"] == "ok"
    assert doc_after_failures["active"] == 1
    chunks = processor.db.search_chunks(document_id=original_id)
    assert len(chunks) > 0
    assert any("antelope" in c["text"].lower() for c in chunks)

    # Now verify successful replacement updates the document without creating duplicates
    replacement_data = text_pdf_bytes("Section 10 Updated statute content with modified buffalo keyword. " * 8)
    updated_record = processor.ingest(
        "updated_version.pdf",
        replacement_data,
        act_name="Antelope Act (Updated)",
        source_url="https://example.test/antelope-v2",
        document_id=original_id,
    )
    assert updated_record["id"] == original_id
    assert updated_record["act_name"] == "Antelope Act (Updated)"
    docs = [d for d in processor.db.list_documents() if d["id"] == original_id]
    assert len(docs) == 1
    updated_chunks = processor.db.search_chunks(document_id=original_id)
    assert any("buffalo" in c["text"].lower() for c in updated_chunks)
    assert not any("antelope" in c["text"].lower() for c in updated_chunks)
