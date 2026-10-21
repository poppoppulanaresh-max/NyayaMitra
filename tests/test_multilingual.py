from __future__ import annotations

from translations import t, suggested_questions


def test_english_ui_and_query(processor, rag):
    from tests.pdf_builder import text_pdf_bytes

    processor.ingest(
        "en.pdf",
        text_pdf_bytes("Section 21 No person shall be deprived of his life or personal liberty except according to procedure established by law. " * 4),
        act_name="Constitution of India",
        language="en",
    )
    rag.reload()
    result = rag.answer("personal liberty", lang="en")
    assert result["sources"]
    assert t("en", "home") == "Home"


def test_hindi_ui_and_query(processor, rag, monkeypatch):
    from tests.pdf_builder import text_pdf_bytes

    processor.ingest(
        "hi.pdf",
        text_pdf_bytes("Section 21 No person shall be deprived of his life or personal liberty except according to procedure established by law. " * 4),
        act_name="Constitution of India",
        language="en",
    )
    rag.reload()
    monkeypatch.setattr(rag, "_llm", lambda: None)
    assert t("hi", "home") == "होम"
    result = rag.answer("व्यक्तिगत स्वतंत्रता personal liberty", lang="hi")
    assert result["sources"]
    assert "personal liberty" in result["sources"][0]["text"].lower()
    assert result["answer"].startswith("प्राप्त स्रोतों")


def test_telugu_ui_and_query(processor, rag, monkeypatch):
    from tests.pdf_builder import text_pdf_bytes

    processor.ingest(
        "te.pdf",
        text_pdf_bytes("Section 21 No person shall be deprived of his life or personal liberty except according to procedure established by law. " * 4),
        act_name="Constitution of India",
        language="en",
    )
    rag.reload()
    monkeypatch.setattr(rag, "_llm", lambda: None)
    assert t("te", "home") == "హోమ్"
    result = rag.answer("personal liberty", lang="te")
    assert result["sources"]
    assert "personal liberty" in result["sources"][0]["text"].lower()
    assert result["answer"].startswith("సేకరించిన మూలాల ఆధారంగా")


def test_mixed_language_question(processor, rag):
    from tests.pdf_builder import text_pdf_bytes

    processor.ingest(
        "mix.pdf",
        text_pdf_bytes("Section 3 all citizens shall have the right to information. " * 8),
        act_name="Right to Information Act, 2005",
        language="en",
    )
    rag.reload()
    result = rag.answer("RTI धारा 3 right to information", lang="hi")
    assert result["sources"] or "could not find sufficient" in result["answer"].lower()


def test_cross_language_transparency(rag):
    result = rag.answer("FIR क्या होती है?", lang="hi")
    # Empty index: must not pretend multilingual coverage
    assert result["sources"] == []


def test_suggested_questions_are_examples_only():
    qs = suggested_questions()
    assert len(qs) >= 6
    assert any("FIR" in q for q in qs)
