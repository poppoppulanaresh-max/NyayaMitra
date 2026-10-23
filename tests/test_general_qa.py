from __future__ import annotations

from unittest.mock import MagicMock

from document_processor import pages_to_chunks
from tests.pdf_builder import text_pdf_bytes


def test_bare_section_and_chapter_metadata_are_extracted(processor, rag, monkeypatch):
    monkeypatch.setattr(rag, "_llm", lambda: None)
    record = processor.ingest(
        "contract.pdf",
        text_pdf_bytes(
            "CHAPTER II\nOF CONTRACTS\n10. What agreements are contracts.—All agreements are contracts if made by free consent of parties competent to contract. "
            * 4
        ),
        act_name="The Indian Contract Act, 1872",
        source_url="https://example.test/contract",
    )
    rag.reload()
    chunks = [row for row in rag.items if row["document_id"] == record["id"]]
    assert chunks
    assert chunks[0]["section_number"] == "10"
    assert "agreements are contracts" in chunks[0]["section_title"].lower()
    assert chunks[0]["chapter"] == "II"
    result = rag.answer("What agreements are contracts under the Indian Contract Act?")
    assert result["sources"]
    assert result["sources"][0]["section_number"] == "10"
    assert result["sources"][0]["chapter"] == "II"


def test_section_metadata_is_recovered_for_previously_indexed_chunks(processor, db, rag):
    record = processor.ingest(
        "legacy.pdf",
        text_pdf_bytes("CHAPTER I\nPRELIMINARY\n1. Short title.—This is an example section heading. " * 5),
        act_name="Legacy Metadata Act",
    )
    with db.connect() as con:
        con.execute("UPDATE chunks SET section_number='unknown', section_title='', chapter='', chapter_title='' WHERE document_id=?", (record["id"],))
    rag.reload()
    chunk = next(row for row in rag.items if row["document_id"] == record["id"])
    assert chunk["section_number"] == "1"
    assert chunk["section_title"].lower().startswith("short title")
    assert chunk["chapter"] == "I"


def test_query_translation_expands_telugu_for_english_index(processor, rag, monkeypatch):
    processor.ingest(
        "limitation.pdf",
        text_pdf_bytes(
            "113. Any suit for which no period of limitation is provided elsewhere in this Schedule, the period of limitation shall be three years. " * 6
        ),
        act_name="The Limitation Act, 1963",
        source_url="https://example.test/limitation",
    )
    rag.reload()

    class TranslationClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    mock = MagicMock()
                    messages = kwargs.get("messages", [])
                    if messages and "Translate the user's legal question" in messages[0]["content"]:
                        content = "What is the time limit for filing a civil suit? limitation period article 113 three years Limitation Act"
                    else:
                        content = "The retrieved excerpt says the period is three years where no other period is specified."
                    mock.choices = [MagicMock(message=MagicMock(content=content))]
                    return mock

    monkeypatch.setattr(rag, "_llm", lambda: TranslationClient())
    result = rag.answer("సివిల్ కేసు దాఖలు చేయడానికి కాల పరిమితి ఎంత?", lang="te")
    assert result["sources"]
    assert result["sources"][0]["act_name"] == "The Limitation Act, 1963"
    assert result["sources"][0]["section_number"] == "113"


def test_offline_answer_contains_retrieved_excerpt_and_citation(processor, rag, monkeypatch):
    processor.ingest(
        "contract.pdf",
        text_pdf_bytes("10. What agreements are contracts.—All agreements are contracts if made by free consent of parties competent to contract. " * 5),
        act_name="The Indian Contract Act, 1872",
        source_url="https://example.test/contract",
    )
    rag.reload()
    monkeypatch.setattr(rag, "_llm", lambda: None)
    result = rag.answer("What are the key provisions of the Indian Contract Act, 1872?")
    assert result["sources"]
    assert "Retrieved PDF text" in result["answer"]
    assert "free consent" in result["answer"].lower()
    assert "page" in result["answer"].lower()


def test_pages_to_chunks_carries_section_through_continuation():
    chunks = pages_to_chunks(
        [(1, "CHAPTER II\nOF CONTRACTS\n10. What agreements are contracts. First part."),
         (2, "Second part continues the rule without repeating its heading.")],
        {"document_id": "d", "act_name": "Sample Act", "original_filename": "sample.pdf"},
    )
    assert len(chunks) == 2
    assert chunks[0]["section_number"] == chunks[1]["section_number"] == "10"
    assert chunks[1]["chapter"] == "II"
    assert chunks[1]["original_filename"] == "sample.pdf"


def test_arrangement_of_sections_is_not_mislabeled_as_a_statutory_section():
    chunks = pages_to_chunks(
        [(1, "THE SAMPLE ACT\nARRANGEMENT OF SECTIONS\nSECTIONS\n1. Short title.\n2. Definitions.\n3. Application of Act.")],
        {"document_id": "toc", "act_name": "Sample Act"},
    )
    assert chunks
    assert all(chunk["section_number"] == "unknown" for chunk in chunks)
    assert all(chunk["section_title"] == "Arrangement of Sections" for chunk in chunks)


def test_section_boundaries_split_chunks_and_ignore_editorial_footnotes():
    chunks = pages_to_chunks(
        [(1, "1. Short title.—This Act may be called the Sample Act. 1. For the Statement of Objects and Reasons, see the Gazette. 2. Interpretation.—In this Act the following words have the meanings below.")],
        {"document_id": "sections", "act_name": "Sample Act"},
    )
    section_chunks = [chunk for chunk in chunks if chunk["section_number"] != "unknown"]
    assert [chunk["section_number"] for chunk in section_chunks] == ["1", "2"]
    assert section_chunks[0]["section_title"].startswith("Short title")
    assert section_chunks[1]["section_title"].startswith("Interpretation")


def test_article_headings_keep_article_citation_type(processor, rag, monkeypatch):
    monkeypatch.setattr(rag, "_llm", lambda: None)
    record = processor.ingest(
        "constitution.pdf",
        text_pdf_bytes("Article 21. Protection of life and personal liberty. No person shall be deprived of life or liberty except according to procedure established by law. " * 4),
        act_name="Constitution of India",
    )
    rag.reload()
    chunk = next(row for row in rag.items if row["document_id"] == record["id"])
    assert chunk["section_number"] == "21"
    assert chunk["provision_type"] == "article"
    result = rag.answer("What does Article 21 say about personal liberty?")
    assert result["sources"]
    assert result["sources"][0]["provision_type"] == "article"


def test_representative_questions_retrieve_across_legal_topics(processor, rag, monkeypatch):
    monkeypatch.setattr(rag, "_llm", lambda: None)
    documents = [
        ("contract.pdf", "10. What agreements are contracts.—All agreements are contracts when made by free consent of parties competent to contract. 73. Compensation for loss caused by breach of contract.", "The Indian Contract Act, 1872", "agreements are contracts"),
        ("limitation.pdf", "113. Any suit for which no period of limitation is provided elsewhere in this Schedule has a period of limitation of three years.", "The Limitation Act, 1963", "suit period of limitation"),
        ("bnss.pdf", "173. Information in cognizable cases may be given orally or by electronic communication to an officer in charge of a police station.", "The Bharatiya Nagarik Suraksha Sanhita, 2023", "cognizable cases"),
        ("bsa.pdf", "63. Admissibility of electronic records. Electronic records may be admitted in evidence when the conditions in this section are satisfied.", "The Bharatiya Sakshya Adhiniyam, 2023", "electronic records"),
        ("consumer.pdf", "Section 35. Manner in which complaint shall be made. A consumer complaint may be filed before the District Commission.", "The Consumer Protection Act, 2019", "consumer complaint"),
        ("it.pdf", "Section 66C. Punishment for identity theft. Whoever fraudulently or dishonestly makes use of another person's electronic signature, password, or other unique identification feature is punishable under this section.", "The Information Technology Act, 2000", "identity theft"),
    ]
    for filename, text, act, _ in documents:
        processor.ingest(filename, text_pdf_bytes((text + " ") * 5), act_name=act, source_url=f"https://example.test/{filename}")
    rag.reload()
    questions = [
        ("What are the key provisions of the Indian Contract Act, 1872?", "Indian Contract Act"),
        ("What is the limitation period for a civil suit?", "Limitation Act"),
        ("How do I report a cognizable offence to the police?", "Nagarik Suraksha Sanhita"),
        ("How are electronic records admitted as evidence?", "Sakshya Adhiniyam"),
        ("How can a consumer make a complaint?", "Consumer Protection Act"),
        ("What does Indian law say about identity theft?", "Information Technology Act"),
    ]
    for question, expected_act in questions:
        result = rag.answer(question)
        assert result["sources"], question
        assert any(expected_act.casefold() in source["act_name"].casefold() for source in result["sources"]), question
