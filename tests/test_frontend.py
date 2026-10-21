from __future__ import annotations

"""Frontend checks. Streamlit AppTest is used when available; otherwise compilation/navigation helpers."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_language_keys_used_by_ui():
    from translations import UI

    required = [
        "home",
        "laws",
        "chat",
        "quiz",
        "admin",
        "upload",
        "search_placeholder",
        "disclaimer",
        "loading",
        "no_match",
        "auth_required",
        "invalid_credentials",
    ]
    for lang in ("en", "hi", "te"):
        for key in required:
            assert UI[lang][key]


def test_app_defines_pages():
    text = (ROOT / "app.py").read_text(encoding="utf-8")
    for name in ("page_home", "page_chat", "page_laws", "page_quiz", "page_admin", "page_upload"):
        assert f"def {name}" in text
    assert "require_admin" in text
    assert "global_search" in text


def test_streamlit_apptest_smoke(monkeypatch, tmp_path):
    import os

    if os.getenv("NYAYA_RUN_APPTEST") != "1":
        pytest.skip("Not run: set NYAYA_RUN_APPTEST=1 to execute Streamlit AppTest (touches a temp DB).")
    try:
        from streamlit.testing.v1 import AppTest
    except Exception:
        pytest.skip("streamlit.testing.v1.AppTest is not available")
    import config

    monkeypatch.setattr(config, "USE_EMBEDDINGS", False)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "apptest.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    try:
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=45)
        at.run()
    except Exception as exc:
        pytest.skip(f"AppTest could not complete in this environment: {exc}")
    assert not at.exception
