from __future__ import annotations

from translations import detect_response_language, t, suggested_questions


def test_response_language_detection_is_independent_of_rag_version():
    assert detect_response_language("ఎలక్ట్రానిక్ రికార్డుల చట్టం ఏది?", "en") == "te"
    assert detect_response_language("ऑनलाइन धोखाधड़ी पर कौन सा कानून है?", "en") == "hi"
    assert detect_response_language("Which law covers contracts?", "te") == "te"
    assert detect_response_language("Hello", "unsupported") == "en"


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
    assert result["answer"].startswith("अनुक्रमित अंशों के आधार पर")


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
    assert result["answer"].startswith("సూచికలోని భాగాల ఆధారంగా")


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


def test_hindi_fir_retrieves_bnss_173(processor, rag, monkeypatch):
    from tests.pdf_builder import text_pdf_bytes

    processor.ingest(
        "bnss_sample.pdf",
        text_pdf_bytes(
            "CHAPTER XIII INFORMATION TO THE POLICE 173. Information in cognizable cases. "
            "(1) Every information relating to the commission of a cognizable offence may be given orally "
            "or by electronic communication to an officer in charge of a police station. " * 4
        ),
        act_name="The Bharatiya Nagarik Suraksha Sanhita, 2023",
        language="en",
    )
    rag.reload()
    monkeypatch.setattr(rag, "_llm", lambda: None)
    result = rag.answer("एफआईआर दर्ज करने की प्रक्रिया क्या है?", lang="hi")
    assert result["sources"]
    assert "Bharatiya Nagarik Suraksha Sanhita" in result["sources"][0]["act_name"]
    assert result["sources"][0]["section_number"] == "173"
    assert "173" in result["answer"]
    assert "भारतीय नागरिक सुरक्षा संहिता" in result["answer"]


def test_telugu_fir_retrieves_bnss_173(processor, rag, monkeypatch):
    from tests.pdf_builder import text_pdf_bytes

    processor.ingest(
        "bnss_sample.pdf",
        text_pdf_bytes(
            "CHAPTER XIII INFORMATION TO THE POLICE 173. Information in cognizable cases. "
            "(1) Every information relating to the commission of a cognizable offence may be given orally "
            "or by electronic communication to an officer in charge of a police station. " * 4
        ),
        act_name="The Bharatiya Nagarik Suraksha Sanhita, 2023",
        language="en",
    )
    rag.reload()
    monkeypatch.setattr(rag, "_llm", lambda: None)
    result = rag.answer("ఎఫ్ఐఆర్ ఎలా నమోదు చేయాలి?", lang="te")
    assert result["sources"]
    assert "Bharatiya Nagarik Suraksha Sanhita" in result["sources"][0]["act_name"]
    assert result["sources"][0]["section_number"] == "173"
    assert "173" in result["answer"]
    assert "భారతీయ నాగరిక్ సురక్ష సంహిత" in result["answer"]


def test_multilingual_consumer_and_dv_retrieval(processor, rag):
    from tests.pdf_builder import text_pdf_bytes

    processor.ingest(
        "cp.pdf",
        text_pdf_bytes("Section 2 consumer dispute and complaint for defective goods or deficiency in service. " * 6),
        act_name="The Consumer Protection Act, 2019",
        language="en",
    )
    processor.ingest(
        "dv.pdf",
        text_pdf_bytes("Section 18 protection orders for aggrieved person in domestic violence. " * 6),
        act_name="The Protection of Women from Domestic Violence Act, 2005",
        language="en",
    )
    rag.reload()
    res_hi = rag.answer("उपभोक्ता शिकायत और दोषपूर्ण सामान", lang="hi")
    assert res_hi["sources"]
    assert "Consumer Protection" in res_hi["sources"][0]["act_name"]

    res_te = rag.answer("గృహ హింస రక్షణ ఉత్తర్వు", lang="te")
    assert res_te["sources"]
    assert "Domestic Violence" in res_te["sources"][0]["act_name"]
