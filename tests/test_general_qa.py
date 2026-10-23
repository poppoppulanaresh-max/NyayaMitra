from __future__ import annotations

from unittest.mock import MagicMock

from document_processor import is_explanatory_page, pages_to_chunks, structure_headings
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
                        content = "లిమిటేషన్ చట్టంలోని ఆర్టికల్ 113 ప్రకారం, ఇతర చోట్ల గడువు పేర్కొనని దావాలకు మూడు సంవత్సరాల గడువు వర్తిస్తుంది."
                    mock.choices = [MagicMock(message=MagicMock(content=content))]
                    return mock

    monkeypatch.setattr(rag, "_llm", lambda: TranslationClient())
    result = rag.answer("సివిల్ కేసు దాఖలు చేయడానికి కాల పరిమితి ఎంత?", lang="te")
    assert result["sources"]
    assert result["llm_used"] is True
    assert "మూడు సంవత్సరాల గడువు" in result["answer"]
    assert "The retrieved excerpt" not in result["answer"]
    assert result["sources"][0]["act_name"] == "The Limitation Act, 1963"
    assert result["sources"][0]["section_number"] == "113"


def test_every_retrieved_passage_gets_hindi_or_telugu_translation(rag, monkeypatch):
    calls = []

    class PassageTranslationClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    calls.append(kwargs)
                    from unittest.mock import MagicMock

                    response = MagicMock()
                    response.choices = [MagicMock(message=MagicMock(content=(
                        '<TRANSLATION id="0">पहला अनुवाद</TRANSLATION>\n'
                        '<TRANSLATION id="1">दूसरा अनुवाद</TRANSLATION>'
                    )))]
                    return response

    monkeypatch.setattr(rag, "_llm", lambda: PassageTranslationClient())
    original_sources = [
        {"act_name": "Sample Act", "section_number": "1", "text": "First legal passage."},
        {"act_name": "Sample Act", "section_number": "2", "text": "Second legal passage."},
    ]

    for language, expected in (("hi", ["पहला अनुवाद", "दूसरा अनुवाद"]), ("te", ["మొదటి అనువాదం", "రెండవ అనువాదం"])):
        # Give each language its own exact translations while also ensuring
        # that every source excerpt is independently paired with a translation.
        if language == "te":
            class TeluguPassageTranslationClient:
                class chat:
                    class completions:
                        @staticmethod
                        def create(**kwargs):
                            from unittest.mock import MagicMock

                            response = MagicMock()
                            response.choices = [MagicMock(message=MagicMock(content=(
                                '<TRANSLATION id="0">మొదటి అనువాదం</TRANSLATION>\n'
                                '<TRANSLATION id="1">రెండవ అనువాదం</TRANSLATION>'
                            )))]
                            return response

            monkeypatch.setattr(rag, "_llm", lambda: TeluguPassageTranslationClient())
        translated = rag._translate_source_passages(original_sources, language)
        assert [source["translated_text"] for source in translated] == expected
        assert [source["text"] for source in translated] == ["First legal passage.", "Second legal passage."]

    assert len(calls) == 1


def test_each_passage_has_localized_fallback_when_translation_provider_is_unavailable(rag, monkeypatch):
    monkeypatch.setattr(rag, "_llm", lambda: None)
    sources = [
        {"text": "First passage."},
        {"text": "Second passage."},
    ]
    translated = rag._translate_source_passages(sources, "hi")
    assert len(translated) == 2
    assert all(source["translated_text"] for source in translated)
    assert translated[0]["translated_text"] == translated[1]["translated_text"]
    assert translated[0]["translated_text"] != "First passage."


def test_offline_answer_is_concise_and_keeps_citation_source(processor, rag, monkeypatch):
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
    assert "OPENAI_API_KEY" in result["answer"]
    assert "free consent" in result["sources"][0]["text"].lower()


def test_answer_prompt_sets_detail_steps_escalation_and_language(processor, rag):
    sources = [{
        "act_name": "The Indian Contract Act, 1872",
        "section_number": "10",
        "page_number": "7",
        "text": "All agreements are contracts if made by free consent of parties competent to contract.",
        "source_url": "https://example.test/act.pdf",
    }]
    prompt = rag._prompt("ఈ ఒప్పందం చెల్లుబాటు అవుతుందా?", sources, "te")
    assert "What the law is about" in prompt
    assert "Steps to take" in prompt
    assert "When to contact an authority" in prompt
    assert "entire answer" in prompt and "Telugu" in prompt
    assert "Do not repeat a Sources list or URL" in prompt
    assert "Do not use numbered headings" in prompt
    assert "unofficial translation immediately after every retrieved passage" in prompt
    assert "same layout for every question" in prompt
    assert "never numbered steps" in prompt


def test_civil_suit_limitation_question_retrieves_exact_schedule_article(processor, rag):
    processor.ingest(
        "limitation.pdf",
        text_pdf_bytes(
            "PART X. SUITS FOR WHICH THERE IS NO PRESCRIBED PERIOD\n"
            "113. Any suit for which no period of limitation is provided elsewhere in this Schedule.\n"
            "Three years. When the right to sue accrues.\n114. Appeal from an order of acquittal."
        ),
        act_name="The Limitation Act, 1963",
        source_url="https://example.test/limitation.pdf",
    )
    rag.reload()
    sources = rag.search("What is the time limit for filing a civil suit under the Limitation Act?", 5)
    assert sources
    assert sources[0]["section_number"] == "113"
    assert sources[0]["provision_type"] == "article"
    assert "Three years" in sources[0]["text"]
    assert "When the right to sue accrues" in sources[0]["text"]


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


def test_explanatory_bill_material_does_not_inherit_a_statutory_section(processor, rag):
    record = processor.ingest(
        "bill.pdf",
        text_pdf_bytes(
            "63. Admissibility of electronic records. operative text.\n"
            "STATEMENT OF OBJECTS AND REASONS\n"
            "The proposed legislation, inter alia, provides as under: evidence includes electronic records."
        ),
        act_name="The Bharatiya Sakshya Adhiniyam, 2023",
    )
    rag.reload()
    chunks = [row for row in rag.items if row["document_id"] == record["id"]]
    explanatory = next(row for row in chunks if "proposed legislation" in row["text"].casefold())
    assert is_explanatory_page(explanatory["text"])
    assert explanatory["section_number"] == "unknown"
    assert explanatory["is_explanatory_page"] is True
    assert all(not row.get("is_explanatory_page") for row in rag.search("proposed legislation electronic records"))


def test_generated_answer_with_unretrieved_section_is_rejected(rag, monkeypatch):
    class BadCitationClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    from unittest.mock import MagicMock

                    response = MagicMock()
                    response.choices = [MagicMock(message=MagicMock(content="Section 527 of this Act governs contracts."))]
                    return response

    monkeypatch.setattr(rag, "_llm", lambda: BadCitationClient())
    sources = [{
        "act_name": "The Indian Contract Act, 1872",
        "section_number": "1",
        "text": "This Act may be called the Indian Contract Act, 1872.",
        "page_number": "10",
    }]
    answer, used_llm = rag.compose_answer("What does the Act say?", sources)
    assert used_llm is False
    assert "not present in the retrieved source citations" in answer
    assert not rag._citations_match_sources("Section 527 applies.", sources)
    assert rag._citations_match_sources("Section 1 applies.", [{**sources[0], "section_number": "1"}])


def test_section_boundaries_split_chunks_and_ignore_editorial_footnotes():
    chunks = pages_to_chunks(
        [(1, "1. Short title.—This Act may be called the Sample Act. 1. For the Statement of Objects and Reasons, see the Gazette. 2. Interpretation.—In this Act the following words have the meanings below.")],
        {"document_id": "sections", "act_name": "Sample Act"},
    )
    section_chunks = [chunk for chunk in chunks if chunk["section_number"] != "unknown"]
    assert [chunk["section_number"] for chunk in section_chunks] == ["1", "2"]
    assert section_chunks[0]["section_title"].startswith("Short title")
    assert section_chunks[1]["section_title"].startswith("Interpretation")


def test_amendment_history_footnotes_are_not_mislabeled_as_act_sections():
    text = (
        "1. Short title. This Act may be called the Sample Act.\n"
        "2. Interpretation. Words have the meanings stated here.\n"
        "3. Panth Piploda—The Central Government may extend this Act.\n"
        "p. 527. It has been amended in certain territories.\n"
        "4. The words in the Schedule are repealed by a later Act."
    )
    headings = structure_headings(text)
    assert [(number, title) for _, kind, number, title in headings if kind == "section"] == [
        ("1", "Short title"), ("2", "Interpretation")
    ]


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
