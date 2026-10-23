from __future__ import annotations

from types import SimpleNamespace

from config import INSUFFICIENT_EVIDENCE_MESSAGE
from legal_search import LegalSearch
from tests.pdf_builder import text_pdf_bytes


def _ingest(processor, name, text, act):
    return processor.ingest(name, text_pdf_bytes(text), act_name=act, source_url="https://example.test/fixture")


def test_revision_signature_supports_legacy_database_objects(tmp_path):
    from rag_engine import NyayMitraRAG

    profile_db = tmp_path / "profile.db"
    library_db = tmp_path / "library.db"
    profile_db.write_bytes(b"profile")
    library_db.write_bytes(b"library")
    legacy_db = SimpleNamespace(
        db_path=profile_db,
        library_db=SimpleNamespace(db_path=library_db),
    )
    rag = object.__new__(NyayMitraRAG)
    rag.db = legacy_db

    before = rag._revision_signature()
    with library_db.open("ab") as file:
        file.write(b"updated")
    after = rag._revision_signature()

    assert before != after


def test_exact_section_and_act_keyword(processor, rag, db):
    _ingest(
        processor,
        "rti.pdf",
        "Section 3 Right to information. Subject to the provisions of this Act, all citizens shall have the right to information. extra padding " * 4,
        "Right to Information Act, 2005",
    )
    rag.reload()
    searcher = LegalSearch(db)
    by_section = searcher.search(section_number="3")
    assert by_section
    assert any("3" in str(r.get("section_number")) for r in by_section)
    by_act = searcher.search(act_name="Right to Information")
    assert by_act
    by_kw = searcher.search(query="citizens", category="Keywords")
    assert by_kw


def test_semantic_retrieval(processor, rag):
    _ingest(
        processor,
        "art21.pdf",
        "Section 21 Protection of life and personal liberty. No person shall be deprived of his life or personal liberty except according to procedure established by law. " * 4,
        "Constitution of India",
    )
    rag.reload()
    hits = rag.search("personal liberty procedure established by law")
    assert hits
    assert hits[0]["act_name"] == "Constitution of India"


def test_empty_index(rag):
    assert rag.search("anything at all") == []
    result = rag.answer("What is an FIR?")
    assert result["sources"] == []
    assert INSUFFICIENT_EVIDENCE_MESSAGE in result["answer"]


def test_irrelevant_and_low_relevance(processor, rag):
    _ingest(
        processor,
        "narrow.pdf",
        "Section 1 Short title. This fixture Act may be called the Unique Quokka Demonstration Act. " * 6,
        "Unique Quokka Demonstration Act",
    )
    rag.reload()
    result = rag.answer("What is the current penalty schedule for an unrelated maritime collision in Antarctica?")
    # Fake embeddings may still match something; require either insufficient or transparent fixture citation
    if result["sources"]:
        for s in result["sources"]:
            assert s.get("text")
            assert s.get("document_id")
    else:
        assert INSUFFICIENT_EVIDENCE_MESSAGE in result["answer"]


def test_deleted_document_not_returned(processor, rag):
    rec = _ingest(
        processor,
        "gone.pdf",
        "Section 12 Unique wallaby phrase for deletion testing. " * 8,
        "Wallaby Act",
    )
    rag.reload()
    assert rag.search("wallaby")
    processor.remove(rec["id"])
    rag.reload()
    assert all("wallaby" not in (h.get("text") or "").lower() for h in rag.search("wallaby phrase"))


def test_missing_metadata_and_citation_mapping(processor, rag):
    processor.ingest(
        "meta.pdf",
        text_pdf_bytes("Paragraph without a labelled section heading. Official wording remains unknown. " * 8),
        act_name="",
        source_url="",
    )
    rag.reload()
    hits = rag.search("paragraph without a labelled section")
    assert hits
    for h in hits:
        assert h["section_number"] in {"unknown", "1"}  # never invent a real section
        assert "text" in h
        result = rag.answer("labelled section heading")
        ids = {c.get("document_id") for c in result["sources"]}
        assert h["document_id"] in ids or not result["sources"]
