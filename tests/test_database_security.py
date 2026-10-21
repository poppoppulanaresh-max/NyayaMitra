from __future__ import annotations

import pytest

from auth import authenticate, bootstrap_admin, verify_password
from document_processor import DocumentProcessingError
from quiz import QuizService
from tests.pdf_builder import text_pdf_bytes


def test_chat_history_persistence(db):
    db.ensure_session("s1", "en", "hello")
    db.add_message("s1", "user", "What is Article 21?", None)
    db.add_message("s1", "assistant", "See retrieved text.", [])
    rows = db.recent_chats()
    assert rows
    assert rows[0]["question"] == "What is Article 21?"


def test_saved_chat_sessions_can_be_reopened_and_deleted(db):
    db.ensure_session("saved-1", "en", "What is Article 21?")
    db.add_message("saved-1", "user", "What is Article 21?", None)
    db.add_message("saved-1", "assistant", "A retrieved answer.", [{"act_name": "Fixture"}])
    sessions = db.list_chat_sessions()
    assert sessions[0]["id"] == "saved-1"
    messages = db.chat_messages("saved-1")
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["sources"] == [{"act_name": "Fixture"}]
    db.delete_chat_session("saved-1")
    assert db.chat_messages("saved-1") == []
    assert all(row["id"] != "saved-1" for row in db.list_chat_sessions())


def test_admin_quiz_question_create_update_delete(db):
    qid = db.save_quiz_question({
        "question": "Fixture question?", "choice_a": "A", "choice_b": "B",
        "choice_c": "C", "choice_d": "D", "answer": "b",
        "explanation": "Fixture explanation", "source": "Fixture source",
    })
    row = next(q for q in db.quiz_questions() if q["id"] == qid)
    assert row["answer"] == "B"
    assert row["educational_label"] == 1
    db.save_quiz_question({**row, "id": qid, "question": "Updated fixture question?"})
    assert next(q for q in db.quiz_questions() if q["id"] == qid)["question"] == "Updated fixture question?"
    db.delete_quiz_question(qid)
    assert all(q["id"] != qid for q in db.quiz_questions())


def test_admin_quiz_question_rejects_incomplete_content(db):
    with pytest.raises(ValueError):
        db.save_quiz_question({"question": "Incomplete"})


def test_quiz_score_persistence(db):
    db.seed_quiz(
        [
            {
                "id": 1,
                "question": "Educational fixture question?",
                "choice_a": "No",
                "choice_b": "Yes",
                "choice_c": "Maybe",
                "choice_d": "Never",
                "answer": "B",
                "explanation": "Educational",
                "source": "Educational sample",
                "educational_label": True,
            }
        ]
    )
    quiz = QuizService(db)
    score, total, details = quiz.score({1: "B"})
    assert score == 1 and total == 1 and details[0]["is_correct"]
    aid = quiz.persist(score, total, {1: "B"})
    assert aid >= 1
    assert quiz.recent()[0]["score"] == 1


def test_parameterized_query_does_not_run_injection(db):
    db.ensure_session("s2", "en", "q")
    payload = "x'; DROP TABLE chat_messages; --"
    db.add_message("s2", "user", payload, None)
    rows = db.recent_chats()
    assert any(payload in r["question"] for r in rows)
    with db.connect() as con:
        exists = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='chat_messages'"
        ).fetchone()
    assert exists is not None


def test_invalid_credentials_rejected(db, monkeypatch):
    monkeypatch.setattr("config.ADMIN_USERNAME", "admin")
    monkeypatch.setattr("config.ADMIN_PASSWORD", "correct-horse")
    bootstrap_admin(db)
    assert authenticate(db, "admin", "correct-horse") is True
    assert authenticate(db, "admin", "wrong") is False
    assert authenticate(db, "other", "correct-horse") is False


def test_unauthorized_means_no_admin_row_guess(db):
    assert authenticate(db, "admin", "admin") is False
    assert db.admin_count() == 0


def test_passwords_hashed(db, monkeypatch):
    monkeypatch.setattr("config.ADMIN_PASSWORD", "secret-value")
    monkeypatch.setattr("config.ADMIN_USERNAME", "admin")
    bootstrap_admin(db)
    stored = db.get_admin_hash("admin")
    assert stored and stored.startswith("pbkdf2_sha256$")
    assert "secret-value" not in stored
    assert verify_password("secret-value", stored)


def test_file_upload_validation(processor):
    with pytest.raises(DocumentProcessingError):
        processor.ingest("../etc/passwd.pdf", b"notpdf")
    from document_processor import safe_filename

    name = safe_filename("..\\..\\windows\\system32\\evil.pdf", "abc123def456")
    assert ".." not in name
    assert name.endswith(".pdf")
    assert name.startswith("abc123def456")


def test_secrets_not_in_status(rag, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-for-display")
    status = rag.status()
    dumped = str(status)
    assert "sk-test-not-for-display" not in dumped
