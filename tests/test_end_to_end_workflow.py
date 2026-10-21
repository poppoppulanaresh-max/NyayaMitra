from __future__ import annotations

from database import Database
from document_processor import DocumentProcessor
from rag_engine import NyayMitraRAG
from tests.pdf_builder import text_pdf_bytes


def test_synthetic_pdf_to_grounded_answer_and_removal(tmp_path):
    db_path = tmp_path / "workflow.db"
    uploads = tmp_path / "uploads"
    db = Database(db_path)
    processor = DocumentProcessor(db, uploads_dir=uploads)
    pdf = text_pdf_bytes(
        "Section 45 Water testing procedure. Any city water supplier must publish "
        "monthly water quality testing results for public review. " * 8
    )
    record = processor.ingest(
        "synthetic_water_fixture.pdf",
        pdf,
        act_name="Synthetic Water Fixture (not law)",
        source_url="Synthetic test fixture",
    )
    assert record["indexing_status"] == "indexed"

    # Reopen the SQLite database to verify the indexed document survives restart.
    restarted_db = Database(db_path)
    restarted_processor = DocumentProcessor(restarted_db, uploads_dir=uploads)
    rag = NyayMitraRAG(restarted_db)
    supported = rag.answer("What are the monthly water quality testing results?")
    assert supported["sources"]
    assert any(source["document_id"] == record["id"] for source in supported["sources"])
    assert any(source["page_number"] == "1" for source in supported["sources"])

    unsupported = rag.answer("What is the filing deadline for a Mars visa appeal?")
    assert not unsupported["sources"]
    assert "could not find sufficient" in unsupported["answer"].lower()

    restarted_processor.remove(record["id"])
    rag.reload()
    assert not rag.search("monthly water quality testing results")
