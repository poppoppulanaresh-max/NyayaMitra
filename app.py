from __future__ import annotations

import base64
import json
import logging
import re
import uuid
from html import escape
from pathlib import Path
from typing import Any

import streamlit as st

import config
from auth import bootstrap_admin, hash_password, safe_compare
from config import DB_PATH, KB_SEED_PATH, QUIZ_SEED_PATH, openai_configured
from database import Database
from document_processor import DocumentProcessingError, DocumentProcessor, sha256_bytes
from legal_search import LegalSearch
from quiz import QuizService
from rag_engine import NyayMitraRAG
from translations import LANGS, detect_response_language, suggested_questions, suggested_question_prompts, t as translate

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("nyaya.app")
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
LEGAL_HERO_IMAGE = ASSETS_DIR / "courthouse-hero.jpg"
LAWS_IMAGE = ASSETS_DIR / "bengaluru-high-court.jpg"
CHAT_IMAGE = ASSETS_DIR / "legal-books.jpg"
SDG_16_IMAGE = ASSETS_DIR / "sdg-16.jpg"
LOGO_IMAGE = ASSETS_DIR / "nyaya-mitra-mark.png"


def t(lang: str, key: str) -> str:
    """Never show an untranslated underscore key as interface text."""
    value = translate(lang, key)
    if value == key or re.fullmatch(r"[a-z0-9]+(?:_[a-z0-9]+)+", value):
        return " ".join(part.capitalize() for part in value.replace("_", " ").split())
    return value


st.set_page_config(
    page_title="Nyaya Mitra",
    page_icon=str(LEGAL_HERO_IMAGE),
    layout="wide",
    initial_sidebar_state="expanded",
)


def load_json(path: Path) -> list:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not read seed file %s", path)
    return []


def seed_bundled_pdfs(db: Database, uploads_dir: Path) -> None:
    """Index the official Act PDFs bundled with the app for every user profile."""
    act_by_filename = {
        "0ae7f82ab5b7_CP_Act_2019_1732700731.pdf": "The Consumer Protection Act, 2019",
        "0b305c1ed9b5_1709101314.pdf": "The Protection of Children from Sexual Offences Act, 2012",
        "e6688c668ee1_1710219616.pdf": "The Protection of Women from Domestic Violence Act, 2005",
        "e71725fa32e8_it_act_2000_updated.pdf": "The Information Technology Act, 2000",
        "ff92dcc72778_a202345.pdf": "The Bharatiya Nyaya Sanhita, 2023",
        "A187209.pdf": "The Indian Contract Act, 1872",
        "a1908-05.pdf": "The Code of Civil Procedure, 1908",
        "A1963-36.pdf": "The Limitation Act, 1963",
        "a1989-33.pdf": "The Scheduled Castes and the Scheduled Tribes (Prevention of Atrocities) Act, 1989",
        "A2000-21.pdf": "The Information Technology Act, 2000",
        "A2005-22.pdf": "The Right to Information Act, 2005",
        "A2012-32.pdf": "The Protection of Children from Sexual Offences Act, 2012",
        "A2023-46.pdf": "The Bharatiya Nagarik Suraksha Sanhita, 2023",
        "a2023-47.pdf": "The Bharatiya Sakshya Adhiniyam, 2023",
        "a1882-04.pdf": "The Transfer of Property Act, 1882",
        "a1899-2_.pdf": "The Indian Stamp Act, 1899",
        "a1908-16.pdf": "The Registration Act, 1908",
        "A1925-39.pdf": "The Indian Succession Act, 1925",
        "a1954-43.pdf": "The Special Marriage Act, 1954",
        "A1956-30.pdf": "The Hindu Succession Act, 1956",
        "A1956-32.pdf": "The Hindu Minority and Guardianship Act, 1956",
        "A1961-28.pdf": "The Dowry Prohibition Act, 1961",
        "A1987-39.pdf": "The Legal Services Authorities Act, 1987",
        "A1988-59.pdf": "The Motor Vehicles Act, 1988",
        "A2007-06.pdf": "The Prohibition of Child Marriage Act, 2006",
        "A2007-56.pdf": "The Maintenance and Welfare of Parents and Senior Citizens Act, 2007",
        "A2013-14.pdf": "The Sexual Harassment of Women at Workplace (Prevention, Prohibition and Redressal) Act, 2013",
        "a1881-26.pdf": "The Negotiable Instruments Act, 1881",
        "a2023-22.pdf": "The Digital Personal Data Protection Act, 2023",
        "A1940-23.pdf": "The Drugs and Cosmetics Act, 1940",
        "a1955-22.pdf": "The Protection of Civil Rights Act, 1955",
        "A1985-61.pdf": "The Narcotic Drugs and Psychotropic Substances Act, 1985",
        "a1986-61.pdf": "The Child and Adolescent Labour (Prohibition and Regulation) Act, 1986",
        "a1988-49.pdf": "The Prevention of Corruption Act, 1988",
        "a1994-10.pdf": "The Protection of Human Rights Act, 1993",
        "A2003-15.pdf": "The Prevention of Money-Laundering Act, 2002",
        "A2013-20.pdf": "The National Food Security Act, 2013",
        "A2016-49.pdf": "The Rights of Persons with Disabilities Act, 2016",
    }
    official_sources = {
        "A187209.pdf": "https://www.indiacode.nic.in/bitstream/123456789/2187/2/A187209.pdf",
        "a1908-05.pdf": "https://www.indiacode.nic.in/indiacode/bitstream/123456789/2191/1/aA1908-05.pdf",
        "A1963-36.pdf": "https://www.indiacode.nic.in/bitstream/123456789/1565/5/A1963-36.pdf",
        "a1989-33.pdf": "https://www.indiacode.nic.in/bitstream/123456789/1920/1/aA1989-33.pdf",
        "A2000-21.pdf": "https://www.indiacode.nic.in/bitstream/123456789/13116/1/it_act_2000_updated.pdf",
        "A2005-22.pdf": "https://www.indiacode.nic.in/bitstream/123456789/2065/1/aa2005.pdf",
        "A2012-32.pdf": "https://www.indiacode.nic.in/handle/123456789/2079?view_type=browse",
        "A2023-46.pdf": "https://www.indiacode.nic.in/bitstream/123456789/21920/1/the_bharatiya_nagarik_suraksha_sanhita%2C_2023.pdf",
        "a2023-47.pdf": "https://www.indiacode.nic.in/bitstream/123456789/20063/1/aa202347.pdf",
        "0ae7f82ab5b7_CP_Act_2019_1732700731.pdf": "https://www.indiacode.nic.in/",
        "0b305c1ed9b5_1709101314.pdf": "https://www.indiacode.nic.in/",
        "e6688c668ee1_1710219616.pdf": "https://www.indiacode.nic.in/",
        "e71725fa32e8_it_act_2000_updated.pdf": "https://www.indiacode.nic.in/",
        "ff92dcc72778_a202345.pdf": "https://www.indiacode.nic.in/",
        "a1882-04.pdf": "https://www.indiacode.nic.in/bitstream/123456789/2338/1/A1882-04.pdf",
        "a1899-2_.pdf": "https://www.indiacode.nic.in/bitstream/123456789/20095/1/the_indian_stamp_act%2C_1899.pdf",
        "a1908-16.pdf": "https://www.indiacode.nic.in/bitstream/123456789/18914/1/a1908-16.pdf",
        "A1925-39.pdf": "https://www.indiacode.nic.in/indiacode/handle/123456789/2385?view_type=browse",
        "a1954-43.pdf": "https://www.indiacode.nic.in/bitstream/123456789/1387/1/A1954-43E.pdf",
        "A1956-30.pdf": "https://www.indiacode.nic.in/bitstream/123456789/1713/1/AAA1956suc___30.pdf",
        "A1956-32.pdf": "https://www.indiacode.nic.in/bitstream/123456789/1649/1/195632.pdf",
        "A1961-28.pdf": "https://www.indiacode.nic.in/bitstream/123456789/16243/1/196128.pdf",
        "A1987-39.pdf": "https://www.indiacode.nic.in/bitstream/123456789/9316/1/slsa198739.pdf",
        "A1988-59.pdf": "https://www.indiacode.nic.in/bitstream/123456789/9460/1/a1988-59.pdf",
        "A2007-06.pdf": "https://www.indiacode.nic.in/bitstream/123456789/2055/4/a2007-06.pdf",
        "A2007-56.pdf": "https://www.indiacode.nic.in/bitstream/123456789/18950/1/act_200756.pdf",
        "A2013-14.pdf": "https://www.indiacode.nic.in/bitstream/123456789/2104/1/A2013-14.pdf",
        "a1881-26.pdf": "https://www.indiacode.nic.in/bitstream/123456789/2189/1/a1881-26.pdf",
        "a2023-22.pdf": "https://www.indiacode.nic.in/bitstream/123456789/22037/1/a2023-22.pdf",
        "A1940-23.pdf": "https://www.indiacode.nic.in/bitstream/123456789/2409/5/A1940-23.pdf",
        "a1955-22.pdf": "https://www.indiacode.nic.in/indiacode/handle/123456789/1544?view_type=browse",
        "A1985-61.pdf": "https://www.indiacode.nic.in/indiacode/handle/123456789/1791?col=123456789%2F1362&view_type=search",
        "a1986-61.pdf": "https://www.indiacode.nic.in/bitstream/123456789/19582/1/the_child_and_adolescent_labour_%28prohibition_and_regulation%29_act%2C_1986_no._61_of_1986_date_23.12.1986.pdf",
        "a1988-49.pdf": "https://www.indiacode.nic.in/bitstream/123456789/1558/1/aA1988-49.pdf",
        "a1994-10.pdf": "https://www.indiacode.nic.in/indiacode/handle/123456789/15709?col=123456789%2F1362&view_type=search",
        "A2003-15.pdf": "https://www.indiacode.nic.in/indiacode/handle/123456789/2036?view_type=browse",
        "A2013-20.pdf": "https://www.indiacode.nic.in/bitstream/123456789/2113/1/201320.pdf",
        "A2016-49.pdf": "https://www.indiacode.nic.in/bitstream/123456789/13684/1/a2016-49_act.pdf",
    }
    version_by_filename = {
        "a1908-05.pdf": "As on 10 January 2026",
        "a1989-33.pdf": "As on 21 September 2025",
        "A2000-21.pdf": "As on 27 June 2025",
        "A2005-22.pdf": "As on 18 November 2025",
        "A2012-32.pdf": "As on 1 July 2026",
        "A2023-46.pdf": "As on 6 October 2025",
        "a2023-47.pdf": "As on 6 October 2025",
        "A1925-39.pdf": "As on 19 June 2026",
        "a1954-43.pdf": "As on 15 April 2026",
        "A1956-30.pdf": "As on 1 June 2026",
        "A1956-32.pdf": "As on 1 June 2026",
        "A1961-28.pdf": "As on 30 July 2026",
        "A1987-39.pdf": "As on 1 July 2026",
        "A1988-59.pdf": "As on 15 August 2026",
        "A2007-06.pdf": "As on 15 April 2026",
        "A2007-56.pdf": "As on 13 April 2026",
        "A2013-14.pdf": "As on 1 August 2026",
        "a1882-04.pdf": "India Code PDF; consolidation date not printed",
        "a1899-2_.pdf": "India Code PDF; consolidation date not printed",
        "a1908-16.pdf": "India Code PDF; consolidation date not printed",
        "a1881-26.pdf": "India Code PDF; consolidation date not printed",
        "a2023-22.pdf": "As on 19 November 2025",
        "A1940-23.pdf": "As on 1 July 2026",
        "a1955-22.pdf": "As on 15 August 2026",
        "A1985-61.pdf": "As on 1 July 2026",
        "a1986-61.pdf": "India Code PDF; consolidation date not printed",
        "a1988-49.pdf": "As on 21 May 2025",
        "a1994-10.pdf": "India Code PDF; consolidation date not printed",
        "A2003-15.pdf": "As on 27 July 2025",
        "A2013-20.pdf": "As on 1 July 2026",
        "A2016-49.pdf": "As on 1 July 2026",
    }
    processor = DocumentProcessor(db, uploads_dir)
    bundled_uploads = Path(__file__).resolve().parent / "uploads"
    bundled_filenames = set(act_by_filename)
    # Replace only the app's previous bundled copy when a newer supplied PDF exists.
    bundled_replacements = {
        "A2000-21.pdf": "e71725fa32e8_it_act_2000_updated.pdf",
        "A2012-32.pdf": "0b305c1ed9b5_1709101314.pdf",
    }
    active_docs = db.list_documents(active_only=True)
    for pdf_path in sorted(bundled_uploads.glob("*.pdf")):
        if pdf_path.name not in bundled_filenames:
            continue
        if pdf_path.name in set(bundled_replacements.values()) and any(
            (bundled_uploads / new_name).is_file()
            for new_name, old_name in bundled_replacements.items()
            if old_name == pdf_path.name
        ):
            continue
        try:
            data = pdf_path.read_bytes()
            if db.find_document_by_hash(sha256_bytes(data)):
                continue
            replacement_name = bundled_replacements.get(pdf_path.name)
            replacement_doc = next(
                (doc for doc in active_docs if doc.get("original_filename") == replacement_name),
                None,
            ) if replacement_name else None
            if replacement_doc is None:
                normalized_act_name = re.sub(r"^the\s+", "", act_by_filename[pdf_path.name].strip().casefold())
                replacement_doc = next(
                    (
                        doc for doc in active_docs
                        if re.sub(r"^the\s+", "", str(doc.get("act_name") or "").strip().casefold()) == normalized_act_name
                        and str(doc.get("original_filename") or "").lower().endswith(".pdf")
                    ),
                    None,
                )
            record = processor.ingest(
                filename=pdf_path.name,
                data=data,
                act_name=act_by_filename[pdf_path.name],
                source_url=official_sources[pdf_path.name],
                version_or_date=version_by_filename.get(pdf_path.name, "Official India Code PDF"),
                document_id=str(replacement_doc["id"]) if replacement_doc else None,
            )
            active_docs = [doc for doc in active_docs if str(doc.get("id")) != str(record["id"])]
            active_docs.append(record)
            logger.info("Indexed bundled law PDF %s", pdf_path.name)
        except (OSError, DocumentProcessingError):
            logger.exception("Could not index bundled law PDF %s", pdf_path.name)

@st.cache_resource
def get_auth_db() -> Database:
    db = Database(DB_PATH)
    ensure_account_schema(db)
    bootstrap_admin(db)
    if config.ADMIN_PASSWORD:
        stored_hash = db.get_admin_hash(config.ADMIN_USERNAME)
        if stored_hash:
            sync_admin_account(db, config.ADMIN_USERNAME, stored_hash)
    return db


@st.cache_resource
def get_law_library_db() -> Database:
    """Index bundled public law PDFs once and share them read-only by default."""
    library_dir = config.DATA_DIR / "law_library"
    uploads_dir = library_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    db = Database(library_dir / "nyaya_mitra.db", uploads_dir=uploads_dir)
    seed_bundled_pdfs(db, uploads_dir)
    return db


def ensure_account_schema(db: Database) -> None:
    """Create the account table for both current and older SQLite app databases."""
    with db.connect() as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS accounts (
                user_id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )


def get_admin_account(db: Database, username: str) -> dict[str, Any] | None:
    with db.connect() as con:
        row = con.execute(
            "SELECT user_id, username, is_admin FROM accounts WHERE username = ? COLLATE NOCASE",
            (username.strip(),),
        ).fetchone()
        return dict(row) if row else None


def create_admin_account(db: Database, user_id: str, username: str, password_hash: str) -> None:
    with db.connect() as con:
        con.execute(
            "INSERT INTO accounts(user_id, username, password_hash, is_admin) VALUES(?, ?, ?, 1)",
            (user_id, username.strip(), password_hash),
        )


def sync_admin_account(db: Database, username: str, password_hash: str) -> None:
    with db.connect() as con:
        con.execute(
            "UPDATE accounts SET password_hash = ?, is_admin = 1 WHERE username = ? COLLATE NOCASE",
            (password_hash, username.strip()),
        )


@st.cache_resource
def get_profile_db(profile_id: str) -> Database:
    profile_dir = config.DATA_DIR / "profiles" / profile_id
    uploads_dir = profile_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    db = Database(
        profile_dir / "nyaya_mitra.db",
        library_db=get_law_library_db(),
        uploads_dir=uploads_dir,
    )
    db.seed_knowledge(load_json(KB_SEED_PATH))
    db.seed_quiz(load_json(QUIZ_SEED_PATH))
    return db


def get_db() -> Database:
    profile_id = st.session_state.get("user_id") or st.session_state.get("guest_profile_id")
    if not profile_id:
        profile_id = "guest-" + str(uuid.uuid4())
        st.session_state.guest_profile_id = profile_id
    return get_profile_db(str(profile_id))


def profile_upload_dir(db: Database) -> Path:
    uploads_dir = db.uploads_dir
    uploads_dir.mkdir(parents=True, exist_ok=True)
    return uploads_dir


def document_pdf_path(db: Database, stored_filename: str) -> Path:
    local_path = profile_upload_dir(db) / stored_filename
    if local_path.is_file():
        return local_path
    if db.library_db:
        return db.library_db.uploads_dir / stored_filename
    return local_path


def publish_legacy_admin_pdfs(profile_db: Database, library_db: Database) -> bool:
    """Move PDFs uploaded by the former profile-local admin flow to the shared library."""
    with profile_db.connect() as con:
        legacy_docs = [
            dict(row) for row in con.execute(
                "SELECT * FROM documents WHERE active = 1 AND lower(original_filename) LIKE '%.pdf'"
            ).fetchall()
        ]
    processor = DocumentProcessor(library_db, library_db.uploads_dir)
    changed = False
    for doc in legacy_docs:
        # Bundled/shared documents are already visible to every profile.
        if library_db.get_document(str(doc["id"])):
            continue
        path = profile_db.uploads_dir / str(doc.get("stored_filename") or "")
        if not path.is_file():
            logger.warning("Legacy admin PDF is missing from profile storage: %s", doc.get("original_filename"))
            continue
        try:
            existing = library_db.find_document_by_hash(str(doc.get("file_hash") or ""))
            if not existing:
                processor.ingest(
                    filename=str(doc.get("original_filename") or path.name),
                    data=path.read_bytes(),
                    act_name=str(doc.get("act_name") or ""),
                    source_url=str(doc.get("source_url") or ""),
                    language=str(doc.get("language") or "en"),
                    version_or_date=str(doc.get("version_or_date") or ""),
                )
            profile_db.deactivate_document(str(doc["id"]))
            changed = True
        except (DocumentProcessingError, OSError):
            logger.exception("Could not publish legacy admin PDF %s", doc.get("original_filename"))
    return changed


@st.cache_resource
def get_rag(profile_id: str, _db: Database) -> NyayMitraRAG:
    return NyayMitraRAG(_db)


def refresh_rag(db: Database) -> NyayMitraRAG:
    get_rag.clear()
    return get_rag(db.db_path.parent.name, db)


def inject_css() -> None:
    st.markdown(
        """
<style>
:root{--red:#b51f35;--red-dark:#98182b;--navy:#14243a;--muted:#617185;--line:#e2e7ed;--bg:#f4f6f8;--card:#fff;--shadow:0 5px 18px rgba(22,38,58,.055)}
html,body,[class*="css"]{font-family:"Noto Sans Telugu","Noto Sans Devanagari",system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--navy)}
html,body,.stApp{overflow-x:hidden}
.stApp{background:var(--bg);min-height:100vh}
.block-container{padding:1.15rem clamp(1rem,2vw,2rem) 2rem;max-width:1680px;width:100%;box-sizing:border-box}
header[data-testid="stHeader"]{display:flex!important;align-items:center;height:2.4rem;background:transparent!important}
div[data-testid="stToolbar"]{display:flex!important;align-items:center;height:2.4rem;background:transparent!important}
[data-testid="stExpandSidebarButton"]{display:flex!important;visibility:visible!important;position:fixed!important;left:8px;top:6px;z-index:1001;width:30px;height:30px;align-items:center;justify-content:center;border:1px solid var(--line);border-radius:8px;background:#fff;color:var(--navy);box-shadow:var(--shadow)}
[data-testid="stSidebarCollapseButton"]{display:inline-flex!important;visibility:visible!important}
#MainMenu{display:none!important}
[data-testid="stSidebar"]{background:#fff;border-right:1px solid var(--line);width:212px!important;min-width:212px!important;max-width:212px!important}
[data-testid="stSidebar"]>div:first-child{padding-top:1rem}
[data-testid="stSidebar"] [data-testid="stVerticalBlock"]{gap:.45rem}
[data-testid="stSidebar"] div.stButton>button{min-height:38px;padding:.35rem .6rem;text-align:left;font-size:13px;border-radius:9px}
.brand{display:flex;align-items:center;gap:12px;background:#fff;padding:11px 14px;border:1px solid var(--line);border-radius:15px;box-shadow:var(--shadow);min-height:64px}
.brand-mark{width:44px;height:44px;object-fit:contain;flex:none}
.brand-centered{justify-content:center}
.admin-auth-title{display:flex;align-items:center;justify-content:center;gap:13px;margin:0 0 18px;text-align:center}
.centered-section-title{text-align:center;margin:18px 0 14px}
.law-news-headline{display:grid;grid-template-columns:140px 1fr;gap:18px;align-items:center;max-width:1040px;padding:17px 18px;background:#fff;border:1px solid var(--line);border-left:4px solid var(--red);border-radius:12px;margin:10px auto;box-shadow:0 2px 8px rgba(22,38,58,.035)}
.law-news-date{font-size:11px;line-height:1.5;color:var(--muted);font-weight:700;text-transform:uppercase;letter-spacing:.06em}
.law-news-headline h3{font-size:17px;margin:0;color:var(--navy);line-height:1.4}
.law-news-headline p{font-size:12px;color:var(--muted);margin:4px 0 0}
.admin-auth-title img{width:54px;height:54px;object-fit:contain}
.admin-auth-title h1{font-family:'Source Serif 4',Georgia,serif;font-size:26px;line-height:1.15;margin:0;color:var(--navy)}
.st-key-admin_auth form{max-width:390px;margin:0 auto}
.st-key-admin_auth div[data-testid="stTextInput"]{margin-bottom:.25rem}
.brand-name{font-size:25px;font-weight:760;letter-spacing:-.7px;color:var(--navy);line-height:1}
.brand-name span{color:var(--red)}
.brand-sub{color:var(--muted);font-size:12px;margin-top:4px;font-weight:500}
.flag{font-size:18px;text-align:right}
.panel{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:20px;margin-bottom:14px;box-shadow:var(--shadow)}
.hero h1{font-family:'Source Serif 4',Georgia,serif;font-size:28px;margin:0;color:var(--navy)}
.hero p{margin:6px 0 0;color:var(--muted);font-size:14px;line-height:1.5}
.kicker{font-size:11px;letter-spacing:.12em;font-weight:700;color:var(--red);text-transform:uppercase;margin-bottom:6px}
.disclaimer{font-size:12px;color:#5a6b80;border:1px solid #eadfe2;background:#fffafa;border-radius:10px;padding:10px 12px;margin-top:10px}
.quick{border:1px solid var(--line);border-radius:14px;padding:16px;background:#fff;min-height:112px;box-shadow:0 2px 8px rgba(22,38,58,.035)}
.quick h4{margin:8px 0 4px;font-size:14px;color:var(--navy)}
.quick p{margin:0;color:var(--muted);font-size:12px}
.badge{display:inline-block;background:#fff4f5;color:var(--red);border:1px solid #f0d5d9;border-radius:999px;padding:2px 8px;font-size:11px;font-weight:600}
div.stButton>button{border-radius:10px;font-weight:600;border:1px solid var(--line);transition:all .15s ease}
div.stButton>button:hover{border-color:#d99aa5;color:var(--red);transform:translateY(-1px)}
.stButton>button[kind="primary"],.stFormSubmitButton>button[kind="primary"]{background:var(--red);border-color:var(--red);color:#fff}
.stButton>button[kind="primary"]:hover,.stFormSubmitButton>button[kind="primary"]:hover{background:var(--red-dark);color:#fff}
div[data-testid="stTextInput"] input,div[data-testid="stTextArea"] textarea,div[data-testid="stSelectbox"] div{border-radius:10px}
.nav-note{font-size:11px;color:#8a97a8;font-weight:700;letter-spacing:.1em;padding:4px 4px 10px;text-transform:uppercase}
.user-msg,.bot-msg{border-radius:12px;padding:12px 14px;margin:8px 0;font-size:14px;line-height:1.55}
.user-msg{background:#f3f6fb;border:1px solid var(--line)}
.bot-msg{background:#fff;border:1px solid #f0dfe2}
.cite{font-size:12px;color:var(--muted)}
.chat-heading{display:flex;align-items:center;justify-content:space-between;gap:14px;background:#fff;border:1px solid var(--line);border-radius:16px;padding:18px 20px;margin:0 0 14px;box-shadow:var(--shadow)}
.chat-heading h1{font-family:'Source Serif 4',Georgia,serif;font-size:26px;margin:0;color:var(--navy)}
.chat-heading p{margin:3px 0 0;color:var(--muted);font-size:13px}
.chat-status{display:flex;align-items:center;gap:8px;background:#f7f9fb;border:1px solid var(--line);border-radius:10px;padding:10px 12px;color:#34445b;font-size:12px;white-space:normal}
.chat-status-mark{color:var(--red);font-size:17px}
.topbar-copy{font-size:11px;color:var(--muted);letter-spacing:.08em;text-transform:uppercase;font-weight:700}
.home-hero{max-width:1180px;margin:0 auto 18px;text-align:center}
.home-hero-title{font-family:'Source Serif 4',Georgia,serif;font-size:clamp(30px,4vw,48px);font-weight:700;letter-spacing:-.035em;color:var(--navy);margin:12px 0 18px}
.home-hero-image{max-width:1180px;margin:0 auto 24px}
.home-hero-image img{width:100%;height:clamp(280px,42vw,470px);object-fit:cover;object-position:center 46%;border-radius:20px;border:1px solid var(--line);box-shadow:var(--shadow)}
.module-banner{display:grid;grid-template-columns:1.3fr 1fr;gap:20px;align-items:center;background:#fff;border:1px solid var(--line);border-radius:16px;padding:18px;margin:0 0 18px;box-shadow:var(--shadow)}
.module-banner img{width:100%;height:150px;object-fit:cover;object-position:center;border-radius:12px}
.module-banner h1{font-family:'Source Serif 4',Georgia,serif;font-size:28px;color:var(--navy);margin:0}
.sdg-attribution{font-size:10px;color:#718096;line-height:1.35;margin-top:4px}
div[data-testid="stImage"] img{display:block;width:100%;object-fit:cover;border-radius:13px;border:1px solid var(--line)}
.chat-hero-image img{height:112px}
.chat-surface{background:#fff;border:1px solid var(--line);border-radius:14px;padding:16px;min-height:400px;box-shadow:0 1px 3px rgba(20,33,61,.04)}
[data-testid="stVerticalBlockBorderWrapper"]{border:1px solid var(--line)!important;border-radius:16px!important;background:#fff;box-shadow:var(--shadow)}
.chat-welcome{background:linear-gradient(120deg,#fffafa,#fff 72%);border:1px solid #f1dfe2;border-radius:15px;padding:20px;margin:0 0 16px;line-height:1.7}
.chat-welcome strong{font-size:17px;color:var(--navy)}
.chat-actions-title{font-size:12px;font-weight:700;color:var(--muted);margin:12px 2px 6px}
.chat-action-card{background:#fff;border:1px solid var(--line);border-radius:13px;padding:13px 12px;margin:0 0 8px;min-height:84px;box-shadow:0 2px 7px rgba(22,38,58,.035)}
.chat-action-card strong{font-size:13px;color:var(--navy)}
.chat-action-card span{display:block;font-size:11px;color:var(--muted);margin-top:4px;line-height:1.35}
.rail-card{background:#fff;border:1px solid var(--line);border-radius:14px;padding:14px;margin-bottom:12px;box-shadow:var(--shadow)}
.rail-title{font-size:16px;font-weight:700;color:var(--navy);margin:0 0 10px}
.law-news-card{background:#fff;border:1px solid var(--line);border-radius:15px;padding:18px;min-height:135px;box-shadow:var(--shadow)}
.law-news-card h3{font-size:17px;line-height:1.4;margin:4px 0 8px;color:var(--navy)}
.law-news-card p{font-size:13px;color:var(--muted);margin:0}
.act-directory-meta span{padding:3px 8px;background:#f4f6f8;border:1px solid var(--line);border-radius:999px}
.law-year-heading{font-size:20px;font-weight:750;color:var(--navy);margin:20px 0 10px;padding-bottom:8px;border-bottom:1px solid var(--line)}
.rail-card div[data-testid="stButton"]>button{min-height:52px;text-align:left;white-space:normal;line-height:1.3;background:#fffafa}
[data-testid="stChatInput"]>div{border-radius:999px!important;background:#fff}
.chat-scroll-note{font-size:11px;color:#8190a3;margin:-4px 0 8px 2px}
footer{visibility:hidden}
@media(max-width:1100px){.block-container{padding-left:.7rem;padding-right:.7rem}.chat-heading{align-items:flex-start;flex-direction:column}.chat-status{width:100%}}
@media(max-width:1000px){.block-container{padding-left:1rem;padding-right:1rem}div[data-testid="stHorizontalBlock"]{flex-wrap:wrap!important}div[data-testid="stHorizontalBlock"]>div[data-testid="column"]{min-width:min(100%,620px)!important;width:100%!important;flex:1 1 100%!important}.module-banner{grid-template-columns:1fr}.module-banner img{height:190px}}
@media(max-width:620px){.law-news-headline{grid-template-columns:1fr;gap:4px}}
@media(max-width:760px){[data-testid="stSidebar"]{width:min(84vw,280px)!important;min-width:min(84vw,280px)!important;max-width:min(84vw,280px)!important}.brand-name{font-size:21px}.block-container{padding:.5rem .55rem 1rem}.chat-surface{padding:10px;min-height:0}.panel{padding:14px}.chat-heading h1{font-size:22px}.home-hero-image img{height:240px}}
@media(max-height:820px){.block-container{padding-top:.8rem}}
button:focus,input:focus,textarea:focus,select:focus{outline:2px solid var(--red)!important;outline-offset:2px}
</style>
""",
        unsafe_allow_html=True,
    )


def init_state() -> None:
    defaults = {
        "language": "English",
        "page": "chat",
        "messages": [],
        "pending_question": "",
        "is_admin": False,
        "user_id": "",
        "username": "",
        "guest_profile_id": "guest-" + str(uuid.uuid4()),
        "chat_session_id": str(uuid.uuid4()),
        "confirm_clear": False,
        "delete_chat_id": "",
        "show_all_chats": False,
        "quiz_index": 0,
        "quiz_answers": {},
        "quiz_submitted_current": False,
        "quiz_finished": False,
        "quiz_details": [],
        "quiz_score": 0,
        "quiz_act_id": "",
        "quiz_round_index": 0,
        "quiz_round_questions": [],
        "quiz_round_language": "en",
        "quiz_active": False,
        "quiz_completed_rounds": {},
        "laws_query": "",
        "laws_category": "All Categories",
        "laws_search_mode": "name",
        "laws_search_mode_widget": "name",
        "act_search_input": "",
        "detail_chunk": None,
        "last_error": "",
        "act_q": "",
        "section_q": "",
        "title_q": "",
        "keyword_q": "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def act_year(act_name: str) -> int | None:
    match = re.search(r"\b(?:18|19|20)\d{2}\b", str(act_name or ""))
    return int(match.group(0)) if match else None


def display_act_title(value: Any) -> str:
    """Clean filename-style titles for display while preserving common legal acronyms."""
    original = str(value or "").strip()
    raw = re.sub(r"\s+", " ", original.replace("_", " "))
    if "_" not in original:
        return raw
    small_words = {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to"}
    acronyms = {"BNS": "BNS", "CIN": "CIN", "CPC": "CPC", "CRPC": "CrPC", "FIR": "FIR", "GST": "GST", "IPC": "IPC", "IT": "IT", "KYC": "KYC", "NCRB": "NCRB", "NDPS": "NDPS", "NIA": "NIA", "POCSO": "POCSO", "RBI": "RBI", "RTI": "RTI", "SC": "SC", "SEBI": "SEBI", "ST": "ST", "UIDAI": "UIDAI"}

    def title_word(match: re.Match[str]) -> str:
        word = match.group(0)
        upper = word.upper()
        if upper in acronyms:
            return acronyms[upper]
        if match.start() > 0 and word.lower() in small_words:
            return word.lower()
        return word[:1].upper() + word[1:].lower()

    return re.sub(r"[A-Za-z]+", title_word, raw)


def button_choices(
    choices: list[tuple[Any, str]], selected: Any, state_key: str, horizontal: bool = True,
    disabled: bool = False,
) -> Any:
    """Render a colored, clickable choice group instead of radio controls."""
    valid_values = {value for value, _ in choices}
    if state_key not in st.session_state or (
        st.session_state[state_key] is not None and st.session_state[state_key] not in valid_values
    ):
        st.session_state[state_key] = selected
    columns = st.columns(len(choices)) if horizontal else [None] * len(choices)
    for index, (value, label) in enumerate(choices):
        target = columns[index]
        if target is None:
            clicked = st.button(
                label, key=f"{state_key}_option_{index}", use_container_width=True,
                type="primary" if st.session_state[state_key] == value else "secondary",
                disabled=disabled,
            )
        else:
            with target:
                clicked = st.button(
                    label, key=f"{state_key}_option_{index}", use_container_width=True,
                    type="primary" if st.session_state[state_key] == value else "secondary",
                    disabled=disabled,
                )
        if clicked:
            st.session_state[state_key] = value
            st.rerun()
    return st.session_state[state_key]


def extract_act_number(document: dict[str, Any], chunks: list[dict[str, Any]]) -> str:
    first_pages = "\n".join(
        str(row.get("text") or "") for row in chunks
        if str(row.get("page_number") or "").isdigit() and int(row["page_number"]) <= 8
    )
    match = re.search(r"\b(?:act\s*)?(?:no\.?\s*)?(\d{1,3})\s+of\s+(\d{4})\b", first_pages, re.IGNORECASE)
    return f"{match.group(1)} of {match.group(2)}" if match else ""


def header(lang: str) -> None:
    hide_global_search = st.session_state.get("page") in {"admin_portal", "home", "laws"}
    h1, h2, h3 = st.columns([2.1, 5.0, 1.1], vertical_alignment="center")
    with h1:
        with st.container(border=True):
            logo_col, name_col = st.columns([.34, 1.66], vertical_alignment="center")
            logo_col.markdown(
                '<svg viewBox="0 0 64 64" width="44" height="44" role="img" aria-label="Nyaya Mitra logo" xmlns="http://www.w3.org/2000/svg"><circle cx="32" cy="32" r="29" fill="#fff8f0" stroke="#b51f35" stroke-width="2.5"/><path d="M32 12v36M22 50h20M25 18h14M15 23h34M32 18l-15 5m15-5 15 5M17 24l-7 14h14zm30 0-7 14h14zM25 45h14" fill="none" stroke="#14243a" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/><path d="M10 38h14m16 0h14" stroke="#b51f35" stroke-width="2"/></svg>',
                unsafe_allow_html=True,
            )
            name_col.markdown(
                f'<div class="brand-name">Nyaya <span>Mitra</span></div><div class="brand-sub">{t(lang, "brand_sub")}</div>',
                unsafe_allow_html=True,
            )
    if not hide_global_search:
        with h2:
            with st.form("global_search", clear_on_submit=False):
                q1, q2, q3 = st.columns([3.2, 1.5, 1.0], vertical_alignment="center")
                term = q1.text_input(t(lang, "search"), placeholder=t(lang, "search_placeholder"), label_visibility="collapsed")
                cats = [t(lang, "act_name_option"), t(lang, "act_number_option")]
                cat_en = ["name", "number"]
                cat_label = q2.selectbox(t(lang, "all_categories"), cats, label_visibility="collapsed")
                submitted = q3.form_submit_button(t(lang, "search"), type="primary", use_container_width=True)
            if submitted and (term or "").strip():
                if not config.PUBLIC_MODE:
                    get_db().log_search(term.strip(), cat_en[cats.index(cat_label)])
                st.session_state.laws_query = term.strip()
                st.session_state.laws_search_mode = cat_en[cats.index(cat_label)]
                st.session_state.laws_search_mode_widget = cat_en[cats.index(cat_label)]
                st.session_state.act_search_input = term.strip()
                st.session_state.page = "laws"
                st.rerun()
    with h3:
        st.selectbox(
            t(lang, "language"), list(LANGS.keys()), key="language",
            format_func=lambda choice: choice, label_visibility="collapsed",
        )


def sidebar_nav(lang: str) -> None:
    with st.sidebar:
        st.markdown(f'<div class="nav-note">{t(lang, "nav_label")}</div>', unsafe_allow_html=True)
        items = [
            ("home", t(lang, "home")),
            ("laws", t(lang, "laws")),
            ("chat", t(lang, "chat")),
            ("quiz", t(lang, "quiz")),
            ("admin_portal", "Admin Portal"),
        ]
        if st.session_state.is_admin:
            items.append(("upload", t(lang, "upload")))
        if st.session_state.is_admin:
            items.append(("admin", t(lang, "admin")))
        for key, label in items:
            active = st.session_state.page == key
            if st.button(label, key=f"nav_{key}", use_container_width=True, type="primary" if active else "secondary"):
                st.session_state.page = key
                st.rerun()
        if st.session_state.user_id:
            st.markdown("---")
            st.success(f"{t(lang, 'signed_in_as')} {st.session_state.username}")
            if st.button(t(lang, "sign_out"), use_container_width=True):
                st.session_state.is_admin = False
                st.session_state.user_id = ""
                st.session_state.username = ""
                st.session_state.messages = []
                st.session_state.pending_question = ""
                st.session_state.quiz_answers = {}
                st.session_state.quiz_details = []
                st.session_state.quiz_round_questions = []
                st.session_state.quiz_completed_rounds = {}
                st.session_state.quiz_active = False
                st.session_state.quiz_finished = False
                st.session_state.quiz_score = 0
                if st.session_state.page in {"admin", "upload", "admin_portal"}:
                    st.session_state.page = "home"
                st.rerun()


def require_admin(lang: str) -> bool:
    if st.session_state.is_admin:
        return True
    st.error(t(lang, "auth_required"))
    return False


def require_account(lang: str) -> bool:
    if st.session_state.get("user_id"):
        return True
    st.warning(t(lang, "auth_required"))
    if st.button("Admin Portal", key="upload_sign_in_link"):
        st.session_state.page = "admin_portal"
        st.rerun()
    return False


def establish_account_session(user_id: str, username: str, is_admin: bool) -> None:
    """Bind the browser session to one profile and discard any guest UI state."""
    st.session_state.user_id = user_id
    st.session_state.username = username
    st.session_state.is_admin = is_admin
    st.session_state.messages = []
    st.session_state.pending_question = ""
    st.session_state.chat_session_id = str(uuid.uuid4())
    st.session_state.quiz_answers = {}
    st.session_state.quiz_index = 0
    st.session_state.quiz_submitted_current = False
    st.session_state.quiz_act_id = ""
    st.session_state.quiz_round_index = 0
    st.session_state.quiz_details = []
    st.session_state.quiz_round_questions = []
    st.session_state.quiz_completed_rounds = {}
    st.session_state.quiz_active = False
    st.session_state.quiz_finished = False
    st.session_state.quiz_score = 0
    st.session_state.page = "admin" if is_admin else "home"


def page_home(lang: str, db: Database, searcher: LegalSearch) -> None:
    st.markdown(f'<div class="home-hero"><div class="kicker">Indian legal information</div><h1 class="home-hero-title">{t(lang, "welcome_title")}</h1></div>', unsafe_allow_html=True)
    if LEGAL_HERO_IMAGE.exists():
        hero_uri = "data:image/jpeg;base64," + base64.b64encode(LEGAL_HERO_IMAGE.read_bytes()).decode("ascii")
        st.markdown(f'<div class="home-hero-image"><img src="{hero_uri}" alt="Allahabad High Court building" /></div>', unsafe_allow_html=True)
    st.markdown('<h2 class="centered-section-title">Recently Updated Laws</h2>', unsafe_allow_html=True)
    docs = [
        doc for doc in db.list_documents(active_only=True)
        if str(doc.get("original_filename") or "").lower().endswith(".pdf")
        and doc.get("indexing_status") == "indexed"
    ]
    docs.sort(key=lambda doc: str(doc.get("upload_date") or ""), reverse=True)
    if not docs:
        st.info(t(lang, "no_documents"))
        return
    for doc in docs[:12]:
        title = display_act_title(doc.get("act_name") or Path(str(doc.get("original_filename") or "")).stem)
        year = act_year(title)
        date_label = display_act_title(doc.get("version_or_date") or doc.get("upload_date") or "Recently added")
        detail = f"Added to the legal information library{f' · {year}' if year else ''}"
        st.markdown(
            f'<article class="law-news-headline"><div class="law-news-date">{escape(date_label)}</div>'
            f'<div><h3>{escape(title)}</h3><p>{escape(detail)}</p></div></article>',
            unsafe_allow_html=True,
        )


def render_pdf_law_library(lang: str, db: Database, query: str = "") -> None:
    """List indexed Act PDFs with expandable text and a direct PDF download."""
    docs = [
        doc for doc in db.list_documents(active_only=True)
        if str(doc.get("original_filename") or "").lower().endswith(".pdf")
        and doc.get("indexing_status") == "indexed"
    ]
    chunks_by_doc: dict[str, list[dict[str, Any]]] = {str(doc["id"]): [] for doc in docs}
    for chunk in db.active_chunks():
        if str(chunk.get("document_id")) in chunks_by_doc:
            chunks_by_doc[str(chunk["document_id"])].append(chunk)
    for doc in docs:
        doc["act_number"] = extract_act_number(doc, chunks_by_doc.get(str(doc["id"]), []))
        doc["year"] = act_year(doc.get("act_name", ""))

    st.caption(f"{len(docs)} indexed legal PDFs")
    if not docs:
        st.info(t(lang, "no_documents"))
        return
    search = (query or "").strip().casefold()
    if search:
        search_terms = re.sub(r"[^a-z0-9]+", " ", search).strip()
        number_terms = re.sub(r"^act\s+", "", search_terms)
        docs = [
            doc for doc in docs
            if any(term and term in re.sub(
                r"[^a-z0-9]+", " ",
                " ".join(str(doc.get(field) or "") for field in ("act_name", "act_number", "original_filename", "year")).casefold(),
            ) for term in {search_terms, number_terms})
        ]
    if not docs:
        st.info(t(lang, "no_match"))
        return

    for doc in sorted(docs, key=lambda row: str(row.get("upload_date") or ""), reverse=True):
        chunks = chunks_by_doc.get(str(doc["id"]), [])
        raw_title = str(doc.get("act_name") or doc.get("original_filename") or t(lang, "uploaded_pdf"))
        title = display_act_title(raw_title)
        label = f"{title} · Act {doc['act_number']} ({doc['year']})" if doc.get("act_number") else title
        with st.expander(label, expanded=False):
            st.caption(
                f"{doc.get('page_count') or 0} {t(lang, 'page')} · "
                f"{len(chunks)} {t(lang, 'indexed_passages')} · "
                f"{t(lang, 'verification')}: {localized_verification_status(lang, str(doc.get('verification_status') or 'unverified'))}"
            )
            if doc.get("version_or_date"):
                st.caption(str(doc["version_or_date"]))
            stored_pdf = document_pdf_path(db, str(doc.get("stored_filename") or ""))
            if stored_pdf.is_file():
                pdf_data = stored_pdf.read_bytes()
                st.download_button(
                    "Download PDF",
                    data=pdf_data,
                    file_name=str(doc.get("original_filename") or "legal_document.pdf"),
                    mime="application/pdf",
                    key=f"laws_download_act_{doc['id']}",
                    use_container_width=True,
                )
                pdf_b64 = base64.b64encode(pdf_data).decode("ascii")
                st.iframe(
                    f"data:application/pdf;base64,{pdf_b64}",
                    height=690,
                )
            first_chunks = chunks[:2]
            if first_chunks:
                st.caption(t(lang, "act_text_preview"))
                for chunk in first_chunks:
                    if chunk.get("section_number") and chunk.get("section_number") != "unknown":
                        provision_label = t(lang, "article") if chunk.get("provision_type") == "article" else t(lang, "section")
                        st.markdown(f"**{provision_label} {escape(str(chunk['section_number']))}**")
                    st.write(chunk.get("text") or "")
            official_url = str(doc.get("source_url") or "").strip()
            if official_url:
                st.link_button("Open official source", official_url)
            if chunks:
                st.markdown("#### Full Act Text")
                for chunk in chunks:
                    section = chunk.get("section_number")
                    page = chunk.get("page_number")
                    heading = []
                    if section and section != "unknown":
                        heading.append(f"{t(lang, 'section')} {section}")
                    if page:
                        heading.append(f"{t(lang, 'page')} {page}")
                    if heading:
                        st.caption(" · ".join(heading))
                    st.write(chunk.get("text") or "")


def localized_verification_status(lang: str, status: str) -> str:
    return {
        "unverified_upload": t(lang, "verification_unverified_upload"),
        "unverified": t(lang, "verification_unverified_upload"),
        "verified": t(lang, "verification_verified"),
    }.get(status, status)


def render_sources(lang: str, sources: list) -> None:
    if not sources:
        return
    source = sources[0]
    provision_label = t(lang, "article") if source.get("provision_type") == "article" else t(lang, "section")
    section = source.get("section_number") or source.get("section") or t(lang, "unknown_section")
    page = f" · {t(lang, 'page')} {source.get('page_number')}" if source.get("page_number") else ""
    st.caption(f"{source.get('act_name')} — {provision_label} {section}{page}")
    source_url = source.get("source_url") or source.get("source") or ""
    if source_url.startswith(("https://", "http://")):
        st.markdown(f"[{t(lang, 'source')}: {source_url}]({source_url})")
    with st.expander(t(lang, "sources"), expanded=False):
        st.caption(t(lang, "translated_note"))
        for s in sources:
            provision_label = t(lang, "article") if s.get("provision_type") == "article" else t(lang, "section")
            st.markdown(
                f"**{s.get('act_name')} — {provision_label} {s.get('section_number') or s.get('section') or t(lang, 'unknown_section')}**"
                + (f" · {s.get('section_title')}" if s.get("section_title") else "")
            )
            meta = []
            if s.get("page_number"):
                meta.append(f"{t(lang, 'page')} {s.get('page_number')}")
            if s.get("source_url") or s.get("source"):
                meta.append(f"{t(lang, 'source')}: {s.get('source_url') or s.get('source')}")
            if s.get("verification_status"):
                status = localized_verification_status(lang, str(s.get("verification_status")))
                meta.append(f"{t(lang, 'verification')}: {status}")
            if s.get("score") is not None:
                meta.append(f"{t(lang, 'retrieval_score')}: {float(s.get('score') or 0):.3f}")
            st.caption(" · ".join(meta))
            st.markdown(f"**{t(lang, 'answer_source_original')} · {t(lang, 'original_text')}**")
            st.write(s.get("text") or "")
            if lang in {"hi", "te"}:
                st.markdown(f"**{t(lang, 'translated_source_passage')}**")
                st.write(s.get("translated_text") or t(lang, "translation_unavailable"))


def page_chat(lang: str, db: Database, rag: NyayMitraRAG) -> None:
    for index, msg in enumerate(st.session_state.messages):
        if msg.get("role") != "assistant":
            continue
        prior_user = next(
            (row.get("content", "") for row in reversed(st.session_state.messages[:index]) if row.get("role") == "user"),
            "",
        )
        response_lang = detect_response_language(prior_user, lang)
        if msg.get("language", "en") == response_lang:
            continue
        sources = msg.get("sources") or []
        msg["content"] = rag.compose_answer(prior_user, sources, response_lang)[0] if sources else t(response_lang, "insufficient")
        msg["language"] = response_lang

    center, right = st.columns([7.1, 2.9], gap="medium")
    with center:
        chat_uri = "data:image/jpeg;base64," + base64.b64encode(CHAT_IMAGE.read_bytes()).decode("ascii") if CHAT_IMAGE.exists() else ""
        st.markdown(f'<div class="module-banner"><h1>{t(lang, "chat_title")}</h1><img src="{chat_uri}" alt="Historic law books" /></div>' if chat_uri else f'<div class="module-banner"><h1>{t(lang, "chat_title")}</h1></div>', unsafe_allow_html=True)
        with st.container(border=True):
            if not st.session_state.messages:
                st.markdown(
                    f'<div class="chat-welcome"><strong>{t(lang, "greeting")}</strong></div>',
                    unsafe_allow_html=True,
                )
            for i, msg in enumerate(st.session_state.messages):
                # A one-letter avatar is treated as a media path by Streamlit.
                # Use its built-in role avatar to avoid MediaFileStorageError.
                message_lang = msg.get("language", lang)
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])
                    if msg.get("sources"):
                        render_sources(message_lang, msg["sources"])
                    if msg["role"] == "assistant":
                        st.download_button(
                            t(message_lang, "copy_answer"),
                            data=msg["content"],
                            file_name="nyaya_mitra_answer.txt",
                            mime="text/plain",
                            key=f"dl_{i}",
                        )
            question = st.chat_input(t(lang, "placeholder"))
            if st.session_state.pending_question:
                question = st.session_state.pending_question
                st.session_state.pending_question = ""
            if question:
                st.session_state.messages.append({"role": "user", "content": question})
                if not config.PUBLIC_MODE:
                    db.ensure_session(st.session_state.chat_session_id, lang, question)
                    db.add_message(st.session_state.chat_session_id, "user", question, None)
                try:
                    with st.spinner(t(lang, "loading")):
                        result = rag.answer(question, lang)
                    answer = result.get("answer") or t(lang, "insufficient")
                    sources = result.get("sources") or []
                    response_lang = result.get("language") or detect_response_language(question, lang)
                except Exception:
                    logger.exception("Chat answer failed")
                    response_lang = detect_response_language(question, lang)
                    answer = t(response_lang, "error_generic")
                    sources = []
                st.session_state.messages.append({"role": "assistant", "content": answer, "sources": sources, "language": response_lang})
                if not config.PUBLIC_MODE:
                    db.add_message(st.session_state.chat_session_id, "assistant", answer, sources)
                st.rerun()
        cols = st.columns(3)
        if cols[0].button(t(lang, "clear_chat")):
            st.session_state.confirm_clear = True
        if st.session_state.confirm_clear:
            st.warning(t(lang, "confirm_clear"))
            if cols[1].button(t(lang, "confirm_clear"), type="primary"):
                st.session_state.messages = []
                st.session_state.chat_session_id = str(uuid.uuid4())
                st.session_state.confirm_clear = False
                st.rerun()
            if cols[2].button(t(lang, "cancel")):
                st.session_state.confirm_clear = False
                st.rerun()
    with right:
        with st.container():
            st.markdown(f'<div class="rail-title">{t(lang, "suggested")}</div>', unsafe_allow_html=True)
            for i, (label, prompt) in enumerate(zip(suggested_questions(lang)[:4], suggested_question_prompts()[:4])):
                if st.button(label, key=f"sug_{i}", use_container_width=True):
                    st.session_state.pending_question = prompt
                    st.rerun()
            if not config.PUBLIC_MODE:
                recent_header, view_header = st.columns([4, 1])
                recent_header.markdown(f'<div class="rail-title">{t(lang, "recent_chats")}</div>', unsafe_allow_html=True)
                total_recent = db.list_chat_sessions(100)
                if len(total_recent) > 4:
                    if view_header.button(t(lang, "less") if st.session_state.show_all_chats else t(lang, "all"), key="toggle_recent_chats", help=t(lang, "recent_chats")):
                        st.session_state.show_all_chats = not st.session_state.show_all_chats
                        st.rerun()
                recents = total_recent if st.session_state.show_all_chats else total_recent[:4]
                if not recents:
                    st.caption(t(lang, "no_recent"))
                for row in recents:
                    label = (row.get("title") or t(lang, "new_chat"))[:70]
                    open_col, delete_col = st.columns([5, 1])
                    if open_col.button(label, key=f"open_chat_{row['id']}", use_container_width=True):
                        st.session_state.chat_session_id = row["id"]
                        st.session_state.messages = [
                            {"role": m["role"], "content": m["content"], "sources": m.get("sources") or [], "language": "en"}
                            for m in db.chat_messages(row["id"])
                        ]
                        st.session_state.confirm_clear = False
                        st.rerun()
                    if delete_col.button("×", key=f"delete_chat_{row['id']}", help=t(lang, "delete_conversation")):
                        st.session_state.delete_chat_id = row["id"]
                if st.session_state.delete_chat_id:
                    st.warning(t(lang, "delete_chat_confirm"))
                    yes_col, no_col = st.columns(2)
                    if yes_col.button(t(lang, "delete_conversation"), key="confirm_delete_chat", type="primary"):
                        target_id = st.session_state.delete_chat_id
                        db.delete_chat_session(target_id)
                        if st.session_state.chat_session_id == target_id:
                            st.session_state.chat_session_id = str(uuid.uuid4())
                            st.session_state.messages = []
                        st.session_state.delete_chat_id = ""
                        st.rerun()
                    if no_col.button(t(lang, "cancel"), key="cancel_delete_chat"):
                        st.session_state.delete_chat_id = ""
                        st.rerun()
            if st.button(t(lang, "new_chat"), use_container_width=True):
                st.session_state.messages = []
                st.session_state.chat_session_id = str(uuid.uuid4())
                st.rerun()


def page_laws(lang: str, searcher: LegalSearch) -> None:
    laws_uri = "data:image/jpeg;base64," + base64.b64encode(LAWS_IMAGE.read_bytes()).decode("ascii") if LAWS_IMAGE.exists() else ""
    st.markdown(f'<div class="module-banner"><h1>{t(lang, "laws_title")}</h1><img src="{laws_uri}" alt="Bengaluru High Court" /></div>' if laws_uri else f'<div class="module-banner"><h1>{t(lang, "laws_title")}</h1></div>', unsafe_allow_html=True)
    st.markdown('<h2 class="centered-section-title">Browse All Laws</h2>', unsafe_allow_html=True)
    st.caption("Search Acts by title or Act number. Select a law to expand its PDF and extracted text.")
    query = st.text_input(
        "Search laws",
        placeholder="Enter an Act name or Act number",
        key="laws_indexed_pdf_search",
    )
    render_pdf_law_library(lang, searcher.db, query)


def page_quiz(lang: str, quiz: QuizService) -> None:
    sdg_uri = "data:image/jpeg;base64," + base64.b64encode(SDG_16_IMAGE.read_bytes()).decode("ascii") if SDG_16_IMAGE.exists() else ""
    st.markdown(f'<div class="module-banner"><h1>{t(lang, "quiz_title")}</h1><img src="{sdg_uri}" alt="United Nations Sustainable Development Goal 16: Peace, Justice and Strong Institutions" /></div>', unsafe_allow_html=True)
    if sdg_uri:
        st.markdown('<div class="sdg-attribution"><a href="https://www.un.org/sustainabledevelopment/" target="_blank">United Nations Sustainable Development Goals</a>. The content of this publication has not been approved by the United Nations and does not reflect the views of the United Nations or its officials or Member States.</div>', unsafe_allow_html=True)
    docs = quiz.law_documents()
    if not docs:
        st.info(t(lang, "no_documents"))
        return
    doc_by_id = {str(doc["id"]): doc for doc in docs}
    doc_ids = list(doc_by_id)
    selected_id = st.selectbox(
        t(lang, "quiz_select_act"), doc_ids,
        format_func=lambda value: display_act_title(doc_by_id[value].get("act_name") or value),
        key="quiz_document_select",
    )
    selected_doc = doc_by_id[selected_id]
    pool = quiz.law_question_pool(selected_id, lang)
    total_questions = len(pool)
    total_rounds = (total_questions + 9) // 10
    done_by_doc = st.session_state.quiz_completed_rounds
    completed = done_by_doc.get(selected_id, [])
    st.caption(t(lang, "quiz_questions_in_act").format(count=total_questions))
    if not total_questions:
        st.info(t(lang, "quiz_no_act_questions"))
        return

    def begin_round(round_index: int) -> None:
        st.session_state.quiz_act_id = selected_id
        st.session_state.quiz_round_index = round_index
        st.session_state.quiz_round_questions = quiz.round_questions(selected_id, round_index, lang)
        st.session_state.quiz_round_language = lang
        st.session_state.quiz_answers = {}
        st.session_state.quiz_index = 0
        st.session_state.quiz_submitted_current = False
        st.session_state.quiz_details = []
        st.session_state.quiz_finished = False
        st.session_state.quiz_active = bool(st.session_state.quiz_round_questions)
        profile_scope = st.session_state.user_id or st.session_state.guest_profile_id
        for item in st.session_state.quiz_round_questions:
            state_key = f"qradio_{selected_id}_{round_index}_{item['id']}"
            st.session_state.pop(state_key, None)
            st.session_state.pop(f"quiz_answer_{profile_scope}_{selected_id}_{round_index}_{item['id']}", None)

    viewing_finished = st.session_state.quiz_finished and st.session_state.quiz_act_id == selected_id
    viewing_active = st.session_state.quiz_active and st.session_state.quiz_act_id == selected_id
    if viewing_finished:
        st.success(f"{t(lang, 'quiz_set_score')}: {st.session_state.quiz_score}/{len(st.session_state.quiz_details)}")
        for row in st.session_state.quiz_details:
            mark = t(lang, "correct") if row["is_correct"] else t(lang, "incorrect")
            st.markdown(f"**{row['id']}. {row['question']}** — {mark}")
            st.caption(row.get("explanation") or "")
            if row.get("source"):
                st.caption(f"{t(lang, 'source')}: {row['source']}")
        if len(completed) < total_rounds:
            next_count = min(10, total_questions - (len(completed) * 10))
            if st.button(t(lang, "quiz_continue_count").format(count=next_count), type="primary"):
                begin_round(len(completed))
                st.rerun()
        else:
            st.success(t(lang, "quiz_all_complete"))
        if st.button(t(lang, "quiz_retake_act")):
            done_by_doc[selected_id] = []
            st.session_state.quiz_completed_rounds = done_by_doc
            begin_round(0)
            st.rerun()
        return

    if not viewing_active:
        if len(completed) >= total_rounds:
            st.success(t(lang, "quiz_all_complete"))
            if st.button(t(lang, "quiz_retake_act"), type="primary"):
                done_by_doc[selected_id] = []
                st.session_state.quiz_completed_rounds = done_by_doc
                begin_round(0)
                st.rerun()
            return
        round_index = len(completed)
        count = min(10, total_questions - round_index * 10)
        st.markdown(f"### {t(lang, 'quiz_round_ready').format(round=round_index + 1, count=count)}")
        if st.button(t(lang, "quiz_start"), type="primary"):
            begin_round(round_index)
            st.rerun()
        return

    questions = st.session_state.quiz_round_questions
    if st.session_state.quiz_round_language != lang:
        questions = quiz.round_questions(selected_id, st.session_state.quiz_round_index, lang)
        st.session_state.quiz_round_questions = questions
        st.session_state.quiz_round_language = lang
    idx = st.session_state.quiz_index
    q = questions[idx]
    st.markdown(f"### {t(lang, 'quiz_set_progress').format(current=st.session_state.quiz_round_index + 1, total=total_rounds)}")
    st.progress((idx + 1) / max(len(questions), 1))
    st.markdown(f"**{idx + 1}/{len(questions)}. {q['question']}**")
    options = [f"A. {q['choice_a']}", f"B. {q['choice_b']}", f"C. {q['choice_c']}", f"D. {q['choice_d']}"]
    answer_state_key = (
        f"quiz_answer_{st.session_state.user_id or st.session_state.guest_profile_id}_"
        f"{selected_id}_{st.session_state.quiz_round_index}_{q['id']}"
    )
    st.caption(t(lang, "choose_answer"))
    choice = button_choices(
        list(enumerate(options)), None, answer_state_key, horizontal=False,
        disabled=st.session_state.quiz_submitted_current,
    )
    choice = options[choice] if choice is not None else None
    if not st.session_state.quiz_submitted_current:
        if st.button(t(lang, "submit_answer"), type="primary", disabled=choice is None):
            st.session_state.quiz_answers[int(q["id"])] = (choice or "")[:1]
            st.session_state.quiz_submitted_current = True
            st.rerun()
    else:
        selected = st.session_state.quiz_answers.get(int(q["id"]), "")
        correct = str(q["answer"]).strip().upper()[:1]
        st.success(t(lang, "correct") if selected == correct else t(lang, "incorrect"))
        st.info(f"{t(lang, 'explanation')}: {q.get('explanation') or ''}")
        if q.get("source"):
            st.caption(f"{t(lang, 'source')}: {q['source']}")
        if st.button(t(lang, "see_results") if idx + 1 >= len(questions) else t(lang, "next_question"), type="primary"):
            if idx + 1 >= len(questions):
                score, total, details = quiz.score_items(questions, st.session_state.quiz_answers)
                if not config.PUBLIC_MODE:
                    quiz.persist(score, total, st.session_state.quiz_answers)
                st.session_state.quiz_score = score
                st.session_state.quiz_details = details
                done_by_doc.setdefault(selected_id, []).append(st.session_state.quiz_round_index)
                st.session_state.quiz_completed_rounds = done_by_doc
                st.session_state.quiz_active = False
                st.session_state.quiz_finished = True
            else:
                st.session_state.quiz_index = idx + 1
                st.session_state.quiz_submitted_current = False
            st.rerun()


def page_admin_portal(lang: str, auth_db: Database) -> None:
    st.markdown(f'<div class="panel hero centered-section-title"><h1>{t(lang, "admin_portal")}</h1></div>', unsafe_allow_html=True)
    if st.session_state.user_id:
        st.success(f"{t(lang, 'signed_in_as')} {st.session_state.username}")
        if st.session_state.is_admin:
            dashboard_col, upload_col = st.columns(2)
            if dashboard_col.button(t(lang, "admin"), type="primary", use_container_width=True):
                st.session_state.page = "admin"
                st.rerun()
            if upload_col.button(t(lang, "upload"), use_container_width=True):
                st.session_state.page = "upload"
                st.rerun()
        return

    _, auth_col, _ = st.columns([1, 1.1, 1])
    with auth_col:
        st.markdown(
            f'<div class="admin-auth-title"><svg viewBox="0 0 64 64" width="54" height="54" role="img" aria-label="Nyaya Mitra logo" xmlns="http://www.w3.org/2000/svg"><circle cx="32" cy="32" r="29" fill="#fff8f0" stroke="#b51f35" stroke-width="2.5"/><path d="M32 12v36M22 50h20M25 18h14M15 23h34M32 18l-15 5m15-5 15 5M17 24l-7 14h14zm30 0-7 14h14zM25 45h14" fill="none" stroke="#14243a" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/><path d="M10 38h14m16 0h14" stroke="#b51f35" stroke-width="2"/></svg><h1>{t(lang, "admin_portal")}</h1></div>',
            unsafe_allow_html=True,
        )
        with st.form("admin_login"):
            username = st.text_input(t(lang, "username"), value=config.ADMIN_USERNAME or "NyayaMitra")
            password = st.text_input(t(lang, "password"), type="password")
            submitted = st.form_submit_button(t(lang, "admin_portal_access"), type="primary", use_container_width=True)
        if submitted:
            clean_username = username.strip()
            configured_username = config.ADMIN_USERNAME.strip()
            if not config.ADMIN_PASSWORD:
                st.error(
                    "Admin login is not configured. Set ADMIN_USERNAME and ADMIN_PASSWORD in the app's Secrets, then restart it."
                )
            elif clean_username.casefold() == configured_username.casefold():
                # Refresh this hash on login: get_auth_db is cached by Streamlit,
                # so changed deployment secrets could leave an old hash in memory.
                bootstrap_admin(auth_db)
                account = get_admin_account(auth_db, clean_username)
                # The configured secret is authoritative; the database hash is kept
                # in sync for account records, but a stale hash must not lock out the owner.
                password_matches = safe_compare(password, config.ADMIN_PASSWORD)
                if password_matches:
                    stored_hash = auth_db.get_admin_hash(clean_username) or hash_password(password)
                    if account:
                        sync_admin_account(auth_db, clean_username, stored_hash)
                        user_id = str(account["user_id"])
                    else:
                        user_id = uuid.uuid4().hex
                        create_admin_account(auth_db, user_id, clean_username, stored_hash)
                    establish_account_session(user_id, clean_username, True)
                    st.rerun()
                else:
                    st.error('The username or password does not match the configured admin credentials. In Streamlit Cloud, check App settings → Secrets for ADMIN_USERNAME = "NyayaMitra" and the intended ADMIN_PASSWORD. Environment variables override Secrets. Save the settings and reboot the app.')
            else:
                st.error('The username or password does not match the configured admin credentials. In Streamlit Cloud, check App settings → Secrets for ADMIN_USERNAME = "NyayaMitra" and the intended ADMIN_PASSWORD. Environment variables override Secrets. Save the settings and reboot the app.')


def page_admin(lang: str, db: Database, processor: DocumentProcessor, rag: NyayMitraRAG) -> None:
    if not require_admin(lang):
        return
    st.markdown(
        f'<div class="panel hero"><h1>{t(lang, "admin_title")}</h1><p>{t(lang, "admin_intro")}</p></div>',
        unsafe_allow_html=True,
    )
    counts = processor.db.counts()
    c1, c2, c3 = st.columns(3)
    c1.metric(t(lang, "metric_docs"), counts["documents"])
    c2.metric(t(lang, "metric_chunks"), counts["chunks"])
    c3.metric(t(lang, "metric_llm"), t(lang, "yes") if openai_configured() else t(lang, "no"))
    llm_error = rag.status().get("llm_last_error") or {}
    if llm_error:
        detail = str(llm_error.get("type") or "Provider error")
        if llm_error.get("status_code"):
            detail += f" · HTTP {llm_error['status_code']}"
        if llm_error.get("provider_code"):
            detail += f" · {llm_error['provider_code']}"
        st.error(f"AI request failed: {detail}. Check the provider key, model access, quota, and deployment logs.")
    upload_form(lang, processor, rag)
    st.subheader(t(lang, "indexed_documents"))
    docs = processor.db.list_documents(active_only=True)
    if not docs:
        st.info(t(lang, "no_documents"))
    for doc in docs:
        with st.expander(
            f"{display_act_title(doc.get('act_name'))} — {display_act_title(doc.get('original_filename'))}"
        ):
            metadata = {
                "ID": doc.get("id"),
                "Original Filename": doc.get("original_filename"),
                "Act Name": display_act_title(doc.get("act_name")),
                "Source URL": doc.get("source_url"),
                "Language": doc.get("language"),
                "Version or Date": doc.get("version_or_date"),
                "Upload Date": doc.get("upload_date"),
                "File Hash": doc.get("file_hash"),
                "Extraction Status": doc.get("extraction_status"),
                "Verification Status": localized_verification_status(
                    lang, str(doc.get("verification_status") or "unverified_upload")
                ),
                "Indexing Status": display_act_title(doc.get("indexing_status")),
                "Processing Error": doc.get("processing_error"),
                "Page Count": doc.get("page_count"),
                "Chunk Count": doc.get("chunk_count"),
            }
            st.json(metadata)
            b1, b2 = st.columns(2)
            if b1.button(t(lang, "reprocess"), key=f"re_{doc['id']}"):
                try:
                    processor.reprocess(doc["id"])
                    rag.reload()
                    st.success(t(lang, "processed_ok"))
                    st.rerun()
                except DocumentProcessingError as exc:
                    st.error(str(exc))
                except Exception:
                    logger.exception("Admin PDF reprocessing failed")
                    st.error(t(lang, "processing_error"))
            if b2.button(t(lang, "remove"), key=f"rm_{doc['id']}"):
                processor.remove(doc["id"])
                rag.reload()
                st.rerun()
    if st.button(t(lang, "rebuild_index"), type="primary"):
        rag.reload()
        st.success(t(lang, "processed_ok"))
    st.subheader(t(lang, "quiz_management"))
    questions = db.quiz_questions()
    selected_id = st.selectbox(
        t(lang, "edit_existing_question"),
        [None, *[int(q["id"]) for q in questions]],
        format_func=lambda value: t(lang, "add_new_question") if value is None else next(
            (f"{value}. {q['question'][:70]}" for q in questions if int(q["id"]) == value), str(value)
        ),
        key="admin_quiz_selected",
    )
    selected = next((q for q in questions if int(q["id"]) == selected_id), {}) if selected_id is not None else {}
    with st.form("admin_quiz_editor"):
        q_text = st.text_area(t(lang, "question"), value=selected.get("question", ""))
        a, b = st.columns(2)
        with a:
            choice_a = st.text_input(t(lang, "choice_a"), value=selected.get("choice_a", ""))
            choice_b = st.text_input(t(lang, "choice_b"), value=selected.get("choice_b", ""))
        with b:
            choice_c = st.text_input(t(lang, "choice_c"), value=selected.get("choice_c", ""))
            choice_d = st.text_input(t(lang, "choice_d"), value=selected.get("choice_d", ""))
        answer = st.selectbox(t(lang, "correct_answer"), ["A", "B", "C", "D"], index=["A", "B", "C", "D"].index(selected.get("answer", "A")))
        explanation = st.text_area(t(lang, "explanation"), value=selected.get("explanation", ""))
        source_ref = st.text_input(t(lang, "source_reference"), value=selected.get("source", ""))
        educational = st.checkbox(t(lang, "label_educational"), value=bool(selected.get("educational_label", 1)))
        save_question = st.form_submit_button(t(lang, "save_question"), type="primary")
    if save_question:
        try:
            saved_id = db.save_quiz_question({
                "id": selected_id, "question": q_text, "choice_a": choice_a, "choice_b": choice_b,
                "choice_c": choice_c, "choice_d": choice_d, "answer": answer,
                "explanation": explanation, "source": source_ref, "educational_label": educational,
            })
            st.success(f"{t(lang, 'question_saved')} ({saved_id})")
            st.rerun()
        except Exception as exc:
            logger.exception("Quiz question save failed")
            st.error(t(lang, "question_save_error"))
    if selected_id is not None and st.button(t(lang, "delete_selected_question"), key="delete_quiz_question"):
        db.delete_quiz_question(selected_id)
        st.rerun()


def upload_form(lang: str, processor: DocumentProcessor, rag: NyayaMitraRAG) -> None:
    st.subheader(t(lang, "upload"))
    existing_docs = processor.db.list_documents(active_only=True)
    mode_options = [t(lang, "add_new_pdf")]
    if existing_docs:
        mode_options.append(t(lang, "update_existing_pdf"))
    profile_scope = processor.db.db_path.parent.name
    upload_action_key = f"pdf_library_action_{profile_scope}"
    current_action = st.session_state.get(upload_action_key, mode_options[0])
    if current_action not in mode_options:
        current_action = mode_options[0]
    button_choices(
        [(option, option) for option in mode_options], current_action,
        upload_action_key, horizontal=True,
    )
    mode = st.session_state[upload_action_key]
    selected_doc: dict[str, Any] | None = None
    if len(mode_options) > 1 and mode == t(lang, "update_existing_pdf"):
        doc_ids = [str(doc["id"]) for doc in existing_docs]
        selected_id = st.selectbox(
            t(lang, "filter_document"),
            doc_ids,
            format_func=lambda value: next(
                (f"{display_act_title(doc.get('act_name'))} · {display_act_title(doc.get('original_filename'))}" for doc in existing_docs if str(doc["id"]) == value),
                value,
            ),
            key="pdf_update_document_id",
        )
        selected_doc = next((doc for doc in existing_docs if str(doc["id"]) == selected_id), None)

    selected_language = (selected_doc or {}).get("language", "en")
    language_index = next((i for i, code in enumerate(LANGS.values()) if code == selected_language), 0)
    with st.form("legal_pdf_upload_form", clear_on_submit=True):
        upload = st.file_uploader(t(lang, "choose_pdf"), type=["pdf"], key="legal_pdf_file")
        name = st.text_input(t(lang, "act_or_document"), value=(selected_doc or {}).get("act_name", ""))
        source = st.text_input(t(lang, "source_url"), value=(selected_doc or {}).get("source_url", ""))
        version = st.text_input(t(lang, "version_date"), value=(selected_doc or {}).get("version_or_date", ""))
        doc_lang_label = st.selectbox(t(lang, "doc_language"), list(LANGS.keys()), index=language_index)
        submitted = st.form_submit_button(t(lang, "process_pdf"), type="primary")
    if not submitted:
        return
    if not upload:
        st.error(t(lang, "choose_pdf"))
        return
    try:
        record = processor.ingest(
            filename=upload.name,
            data=upload.getvalue(),
            act_name=name,
            source_url=source,
            language=LANGS[doc_lang_label],
            version_or_date=version,
            document_id=str(selected_doc["id"]) if selected_doc else None,
        )
        rag.reload()
        st.success(f"{t(lang, 'processed_ok')} {record.get('chunk_count', 0)} {t(lang, 'chunks_created')}")
    except DocumentProcessingError as exc:
        st.error(str(exc))
    except Exception:
        logger.exception("PDF upload or indexing failed")
        st.error(t(lang, "processing_error"))


def page_upload(lang: str, processor: DocumentProcessor) -> None:
    if not require_admin(lang):
        return
    st.markdown(
        f'<div class="panel hero"><h1>{t(lang, "upload")}</h1><p>{t(lang, "admin_intro")}</p></div>',
        unsafe_allow_html=True,
    )
    profile_id = str(st.session_state.get("user_id") or "")
    rag = get_rag(profile_id, get_db())
    upload_form(lang, processor, rag)


def main() -> None:
    inject_css()
    init_state()
    auth_db = get_auth_db()
    db = get_db()
    profile_id = st.session_state.get("user_id") or st.session_state.guest_profile_id
    rag = get_rag(str(profile_id), db)
    processor = DocumentProcessor(db, profile_upload_dir(db))
    searcher = LegalSearch(db)
    quiz = QuizService(db)
    header(LANGS[st.session_state.language])
    lang = LANGS[st.session_state.language]
    sidebar_nav(lang)
    page = st.session_state.page
    if page == "home":
        page_home(lang, db, searcher)
    elif page == "chat":
        page_chat(lang, db, rag)
    elif page == "laws":
        page_laws(lang, searcher)
    elif page == "quiz":
        page_quiz(lang, quiz)
    elif page == "admin_portal":
        page_admin_portal(lang, auth_db)
    elif page == "admin":
        library_db = get_law_library_db()
        if publish_legacy_admin_pdfs(db, library_db):
            rag.reload()
        shared_processor = DocumentProcessor(library_db, library_db.uploads_dir)
        page_admin(lang, db, shared_processor, rag)
    elif page == "upload":
        if st.session_state.is_admin:
            library_db = get_law_library_db()
            if publish_legacy_admin_pdfs(db, library_db):
                rag.reload()
            shared_processor = DocumentProcessor(library_db, library_db.uploads_dir)
            page_upload(lang, shared_processor)
        else:
            require_admin(lang)
    else:
        page_home(lang, db, searcher)


main()
