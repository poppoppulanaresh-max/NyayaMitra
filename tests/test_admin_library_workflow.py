from __future__ import annotations

import pytest

from database import Database
from document_processor import DocumentProcessor
from rag_engine import NyayMitraRAG
from tests.pdf_builder import text_pdf_bytes


def test_admin_pdf_is_shared_with_home_browser_and_assistant(tmp_path):
    library = Database(tmp_path / "library.db", uploads_dir=tmp_path / "library_uploads")
    admin_processor = DocumentProcessor(library, uploads_dir=library.uploads_dir)
    visitor_db = Database(
        tmp_path / "visitor.db",
        library_db=library,
        uploads_dir=tmp_path / "visitor_uploads",
    )
    visitor_rag = NyayMitraRAG(visitor_db)

    record = admin_processor.ingest(
        "shared_water_act.pdf",
        text_pdf_bytes("Section 12 The water authority must publish monthly quality results for public review. " * 8),
        act_name="Shared Water Act Fixture",
        source_url="https://example.test/shared-water-act",
    )

    assert any(doc["id"] == record["id"] for doc in visitor_db.list_documents())
    assert any(chunk["document_id"] == record["id"] for chunk in visitor_db.active_chunks())
    answer = visitor_rag.answer("What water quality results must be published?")
    assert any(source["document_id"] == record["id"] for source in answer["sources"])
    admin_processor.remove(record["id"])
    assert all(source["document_id"] != record["id"] for source in visitor_rag.search("monthly quality results"))
    admin_processor.remove(record["id"])
    assert all(source["document_id"] != record["id"] for source in visitor_rag.search("monthly quality results"))


def test_database_failure_during_replacement_keeps_old_pdf_and_index(processor, db, rag, monkeypatch):
    original = text_pdf_bytes("Section 8 Original text about a valid public notice and old keyword. " * 8)
    record = processor.ingest("original.pdf", original, act_name="Atomic Fixture Act")
    old_chunks = db.search_chunks(document_id=record["id"])
    original_path = processor.uploads_dir / record["stored_filename"]
    assert original_path.read_bytes() == original

    def fail_commit(*_args, **_kwargs):
        raise RuntimeError("simulated database write failure")

    monkeypatch.setattr(db, "save_document_index", fail_commit)
    replacement = text_pdf_bytes("Section 8 Replacement content about another public notice and new keyword. " * 8)
    with pytest.raises(RuntimeError):
        processor.ingest(
            "replacement.pdf",
            replacement,
            act_name="Atomic Fixture Act",
            document_id=record["id"],
        )

    assert db.get_document(record["id"])["stored_filename"] == record["stored_filename"]
    assert db.search_chunks(document_id=record["id"]) == old_chunks
    assert original_path.read_bytes() == original
    assert not list(processor.uploads_dir.glob(".*.tmp"))


def test_script_language_overrides_default_ui_language(rag):
    hindi = rag.answer("सिविल मुकदमे की समय सीमा क्या है?", lang="en")
    telugu = rag.answer("సివిల్ కేసు దాఖలు చేయడానికి కాల పరిమితి ఎంత?", lang="en")
    assert hindi["language"] == "hi"
    assert telugu["language"] == "te"
    assert "वर्तमान अनुक्रमित" in hindi["answer"]
    assert "సరిపడ ఆధార" in telugu["answer"]
