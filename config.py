"""Central configuration for local, Render, and Streamlit Cloud deployments."""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def _setting(name: str, default: str = "") -> str:
    """Read a non-empty environment value, then Streamlit secrets, then default.

    Deployment platforms may define an environment variable with an empty value
    even when the real value is stored in Streamlit Secrets. Treat blank values
    as unset so they do not mask the configured secret.
    """
    value = os.getenv(name)
    if value is not None and value.strip():
        return value
    try:
        import streamlit as st

        value = st.secrets.get(name)
    except Exception:
        # Streamlit is optional for utility scripts/tests, and local runs need
        # not have a secrets.toml file.
        value = None
    if value is not None and str(value).strip():
        return str(value)
    return default

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("NYAYA_DATA_DIR", BASE_DIR / "data"))
UPLOADS_DIR = Path(os.getenv("NYAYA_UPLOADS_DIR", BASE_DIR / "uploads"))
KB_SEED_PATH = Path(os.getenv("NYAYA_KB_SEED", DATA_DIR / "legal_knowledge.json"))
QUIZ_SEED_PATH = DATA_DIR / "quiz_seed.json"
DB_PATH = Path(os.getenv("NYAYA_DB_PATH", DATA_DIR / "nyay_mitra.db"))

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
# Keep startup fast and independent of a model download. Enable explicitly in
# .env when semantic retrieval is desired; keyword retrieval works offline.
USE_EMBEDDINGS = os.getenv("NYAYA_USE_EMBEDDINGS", "0") == "1"
LLM_MODEL = _setting("LLM_MODEL", "gpt-4.1-mini")
OPENAI_API_KEY = _setting("OPENAI_API_KEY")
OPENAI_BASE_URL = _setting("OPENAI_BASE_URL") or None
LLM_TIMEOUT_SECONDS = float(_setting("LLM_TIMEOUT_SECONDS", "45"))

ADMIN_USERNAME = _setting("ADMIN_USERNAME", "NyayaMitra").strip() or "NyayaMitra"
ADMIN_PASSWORD = _setting("ADMIN_PASSWORD")
PUBLIC_MODE = _setting("NYAYA_PUBLIC_MODE", "0").strip().lower() in {"1", "true", "yes", "on"}

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))
MIN_EXTRACT_CHARS = int(os.getenv("MIN_EXTRACT_CHARS", "80"))
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "900"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "150"))
RETRIEVAL_TOP_K = int(os.getenv("RETRIEVAL_TOP_K", "5"))
RELEVANCE_THRESHOLD = float(os.getenv("RELEVANCE_THRESHOLD", "0.28"))
MAX_QUERY_CHARS = int(os.getenv("MAX_QUERY_CHARS", "2000"))
PBKDF2_ITERATIONS = int(os.getenv("PBKDF2_ITERATIONS", "200000"))

INSUFFICIENT_EVIDENCE_MESSAGE = (
    "I could not find sufficient supporting text in the currently indexed legal "
    "documents to answer this reliably. Please consult the relevant official legal "
    "source or a qualified legal professional."
)

DISCLAIMER = (
    "Nyaya Mitra provides general legal information and citizen guidance only. "
    "It is not a substitute for a qualified lawyer, court, or official legal advice. "
    "Indexed documents may be incomplete, unofficial, or out of date. Verify important "
    "matters with India Code or another official source, and with a legal professional."
)


def openai_configured() -> bool:
    return bool(OPENAI_API_KEY.strip())
