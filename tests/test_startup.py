from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def test_modules_import():
    for name in (
        "config",
        "translations",
        "database",
        "auth",
        "document_processor",
        "legal_search",
        "quiz",
        "rag_engine",
    ):
        importlib.import_module(name)


def test_config_without_api_key(monkeypatch):
    import config

    monkeypatch.setattr(config, "OPENAI_API_KEY", "")
    assert config.openai_configured() is False
    assert config.LLM_MODEL


def test_blank_environment_value_does_not_mask_streamlit_secret(monkeypatch):
    import config

    monkeypatch.setenv("OPENAI_API_KEY", "   ")
    monkeypatch.setitem(
        sys.modules,
        "streamlit",
        SimpleNamespace(secrets={"OPENAI_API_KEY": "test-secret-value"}),
    )
    assert config._setting("OPENAI_API_KEY") == "test-secret-value"


def test_disabled_embeddings_do_not_import_sentence_transformers(monkeypatch):
    import rag_engine

    rag = object.__new__(rag_engine.NyayMitraRAG)
    rag.encode_fn = None
    rag.embedder = None
    monkeypatch.setattr(rag_engine, "USE_EMBEDDINGS", False)
    monkeypatch.setattr(
        rag_engine,
        "_load_sentence_transformer",
        lambda: (_ for _ in ()).throw(AssertionError("must stay lazy")),
    )
    assert rag._get_embedder() is None


def test_database_init_clean_directory(tmp_path):
    from database import Database

    db = Database(tmp_path / "nested" / "app.db")
    assert db.counts() == {"documents": 0, "chunks": 0}
    db2 = Database(tmp_path / "nested" / "app.db")
    assert db2.counts()["chunks"] == 0


def test_app_py_compiles():
    path = ROOT / "app.py"
    compile(path.read_text(encoding="utf-8"), str(path), "exec")


def test_translations_cover_en_hi_te():
    from translations import UI, t

    keys = set(UI["en"])
    assert keys
    assert t("hi", "home")
    assert t("te", "home")
    assert t("en", "search_placeholder")
    missing_hi = [k for k in ("home", "chat", "disclaimer", "insufficient") if k not in UI["hi"]]
    assert missing_hi == []
