from __future__ import annotations

import json
import logging
import re
import uuid
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import streamlit as st

import config
from auth import authenticate, bootstrap_admin
from config import DB_PATH, KB_SEED_PATH, QUIZ_SEED_PATH, openai_configured
from database import Database
from document_processor import DocumentProcessingError, DocumentProcessor, sha256_bytes
from legal_search import LegalSearch
from quiz import QuizService
from rag_engine import NyayMitraRAG
from translations import LANGS, suggested_questions, suggested_question_prompts, t

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("nyaya.app")

st.set_page_config(
    page_title="Nyaya Mitra",
    page_icon="⚖️",
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


def seed_bundled_pdfs(db: Database) -> None:
    """Index PDFs shipped in uploads/ once, copying them into persistent storage."""
    known_acts = (
        ("1709101314", "The Protection of Children from Sexual Offences Act, 2012"),
        ("1710219616", "The Protection of Women from Domestic Violence Act, 2005"),
        ("a202345", "The Bharatiya Nyaya Sanhita, 2023"),
        ("cp act 2019", "The Consumer Protection Act, 2019"),
        ("it_act_2000", "The Information Technology Act, 2000"),
    )
    processor = DocumentProcessor(db, config.UPLOADS_DIR)
    bundled_uploads = Path(__file__).resolve().parent / "uploads"
    for pdf_path in sorted(bundled_uploads.glob("*.pdf")):
        try:
            data = pdf_path.read_bytes()
            if db.find_document_by_hash(sha256_bytes(data)):
                continue
            file_stem = pdf_path.stem
            act_name = next((name for marker, name in known_acts if marker in file_stem.lower()), file_stem)
            processor.ingest(filename=pdf_path.name, data=data, act_name=act_name)
            logger.info("Indexed bundled law PDF %s", pdf_path.name)
        except (OSError, DocumentProcessingError):
            logger.exception("Could not index bundled law PDF %s", pdf_path.name)


@st.cache_resource
def get_db() -> Database:
    db = Database(DB_PATH)
    db.seed_knowledge(load_json(KB_SEED_PATH))
    db.seed_quiz(load_json(QUIZ_SEED_PATH))
    bootstrap_admin(db)
    seed_bundled_pdfs(db)
    return db


@st.cache_resource
def get_rag(_db: Database) -> NyayMitraRAG:
    return NyayMitraRAG(_db)


def refresh_rag(db: Database) -> NyayMitraRAG:
    get_rag.clear()
    return get_rag(db)


def inject_css() -> None:
    st.markdown(
        """
<style>
:root{--red:#b51f35;--red-dark:#98182b;--navy:#14243a;--muted:#617185;--line:#e2e7ed;--bg:#f4f6f8;--card:#fff;--shadow:0 5px 18px rgba(22,38,58,.055)}
html,body,[class*="css"]{font-family:"Noto Sans Telugu","Noto Sans Devanagari",system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--navy)}
html,body,.stApp{overflow-x:hidden}
.stApp{background:var(--bg);min-height:100vh}
.block-container{padding:1.15rem clamp(1rem,2vw,2rem) 2rem;max-width:1680px;width:100%;box-sizing:border-box}
header[data-testid="stHeader"],div[data-testid="stToolbar"],#MainMenu{display:none!important}
[data-testid="stSidebar"]{background:#fff;border-right:1px solid var(--line);min-width:232px;max-width:270px}
[data-testid="stSidebar"]>div:first-child{padding-top:1rem}
.brand{display:flex;align-items:center;gap:12px;background:#fff;padding:11px 14px;border:1px solid var(--line);border-radius:15px;box-shadow:var(--shadow);min-height:64px}
.brand-mark{width:42px;height:42px;border-radius:13px;background:#fff4f5;color:var(--red);display:flex;align-items:center;justify-content:center;font-size:22px;border:1px solid #f3d6db}
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
div[data-testid="stRadio"] div[role="radiogroup"]{gap:.15rem;justify-content:flex-end;flex-wrap:wrap}
div[data-testid="stRadio"] label{border-radius:9px;padding:5px 8px}
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
.law-year-heading{font-size:20px;font-weight:750;color:var(--navy);margin:20px 0 10px;padding-bottom:8px;border-bottom:1px solid var(--line)}
.rail-card div[data-testid="stButton"]>button{min-height:52px;text-align:left;white-space:normal;line-height:1.3;background:#fffafa}
[data-testid="stChatInput"]>div{border-radius:999px!important;background:#fff}
.chat-scroll-note{font-size:11px;color:#8190a3;margin:-4px 0 8px 2px}
footer{visibility:hidden}
@media(max-width:1100px){.block-container{padding-left:.7rem;padding-right:.7rem}.chat-heading{align-items:flex-start;flex-direction:column}.chat-status{width:100%}}
@media(max-width:1000px){.block-container{padding-left:1rem;padding-right:1rem}div[data-testid="stHorizontalBlock"]{flex-wrap:wrap!important}div[data-testid="stHorizontalBlock"]>div[data-testid="column"]{min-width:min(100%,620px)!important;width:100%!important;flex:1 1 100%!important}}
@media(max-width:760px){.brand-name{font-size:21px}.block-container{padding:.5rem .55rem 1rem}.chat-surface{padding:10px;min-height:0}.panel{padding:14px}.chat-heading h1{font-size:22px}}
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


def extract_act_number(document: dict[str, Any], chunks: list[dict[str, Any]]) -> str:
    first_pages = "\n".join(
        str(row.get("text") or "") for row in chunks
        if str(row.get("page_number") or "").isdigit() and int(row["page_number"]) <= 8
    )
    match = re.search(r"\b(?:act\s*)?(?:no\.?\s*)?(\d{1,3})\s+of\s+(\d{4})\b", first_pages, re.IGNORECASE)
    return f"{match.group(1)} of {match.group(2)}" if match else ""


def header(lang: str) -> None:
    h1, h2, h3 = st.columns([2.0, 4.5, 1.5], vertical_alignment="center")
    with h1:
        st.markdown(
            '<div class="brand"><div class="brand-mark">⚖</div><div><div class="brand-name">Nyaya <span>Mitra</span></div>'
            f'<div class="brand-sub">{t(lang, "brand_sub")}</div></div></div>',
            unsafe_allow_html=True,
        )
    with h2:
        with st.form("global_search", clear_on_submit=False):
            q1, q2, q3 = st.columns([3.2, 1.5, 1.0], vertical_alignment="center")
            term = q1.text_input(t(lang, "search"), placeholder=t(lang, "search_placeholder"), label_visibility="collapsed")
            cats = [t(lang, "act_name_option"), t(lang, "act_number_option")]
            cat_en = ["name", "number"]
            cat_label = q2.selectbox(t(lang, "all_categories"), cats, label_visibility="collapsed")
            submitted = q3.form_submit_button("🔍 " + t(lang, "search"), type="primary", use_container_width=True)
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
            format_func=lambda choice: f"🌐  {choice}", label_visibility="collapsed",
        )


def sidebar_nav(lang: str, db: Database) -> None:
    with st.sidebar:
        st.markdown(f'<div class="nav-note">{t(lang, "nav_label")}</div>', unsafe_allow_html=True)
        items = [
            ("home", t(lang, "home")),
            ("laws", t(lang, "laws")),
            ("chat", t(lang, "chat")),
            ("quiz", t(lang, "quiz")),
        ]
        if st.session_state.is_admin:
            items.extend([("admin", t(lang, "admin")), ("upload", t(lang, "upload"))])
        for key, label in items:
            active = st.session_state.page == key
            if st.button(label, key=f"nav_{key}", use_container_width=True, type="primary" if active else "secondary"):
                st.session_state.page = key
                st.rerun()
        st.markdown("---")
        counts = db.counts()
        st.caption(f"{t(lang, 'metric_docs')}: {counts['documents']} · {t(lang, 'metric_chunks')}: {counts['chunks']}")
        st.caption(t(lang, "shared_history_note"))
        st.markdown("---")
        if st.session_state.is_admin:
            st.success(f"{t(lang, 'signed_in_as')} {config.ADMIN_USERNAME}")
            if st.button(t(lang, "sign_out"), use_container_width=True):
                st.session_state.is_admin = False
                if st.session_state.page in {"admin", "upload"}:
                    st.session_state.page = "home"
                st.rerun()
        else:
            st.markdown(f"**{t(lang, 'admin_signin')}**")
            if db.admin_count() == 0:
                st.caption(t(lang, "admin_not_configured"))
            else:
                with st.form("admin_login"):
                    user = st.text_input(t(lang, "username"))
                    pw = st.text_input(t(lang, "password"), type="password")
                    if st.form_submit_button(t(lang, "sign_in"), use_container_width=True):
                        if authenticate(db, user, pw):
                            st.session_state.is_admin = True
                            st.rerun()
                        else:
                            st.error(t(lang, "invalid_credentials"))


def require_admin(lang: str) -> bool:
    if st.session_state.is_admin:
        return True
    st.error(t(lang, "auth_required"))
    return False


def page_home(lang: str, db: Database, searcher: LegalSearch) -> None:
    st.markdown(
        f'<div class="panel hero"><div class="kicker">Nyaya Mitra</div><h1>{t(lang, "welcome_title")}</h1>'
        f'<p>{t(lang, "welcome_body")}</p></div>',
        unsafe_allow_html=True,
    )
    docs = [d for d in db.list_documents(active_only=True) if str(d.get("original_filename") or "").lower().endswith(".pdf")]
    docs.sort(key=lambda d: (act_year(d.get("act_name", "")) or 0, d.get("upload_date", "")), reverse=True)
    st.subheader(t(lang, "home_updates_title"))
    st.caption(t(lang, "home_updates_note"))
    india_link, gazette_link = st.columns(2)
    india_link.link_button(t(lang, "india_code_link"), "https://www.indiacode.nic.in/indiacode/home.jsp", use_container_width=True)
    gazette_link.link_button(t(lang, "gazette_link"), "https://egazette.gov.in/", use_container_width=True)
    if not docs:
        st.info(t(lang, "no_documents"))
    else:
        for start in range(0, len(docs), 2):
            cols = st.columns(2, gap="medium")
            for col, doc in zip(cols, docs[start:start + 2]):
                year = act_year(doc.get("act_name", ""))
                version = (doc.get("version_or_date") or "").strip()
                safe_act_name = escape(str(doc.get("act_name") or ""))
                safe_version = escape(version or t(lang, "uploaded_pdf"))
                with col:
                    st.markdown(
                        f'<div class="law-news-card"><div class="kicker">{t(lang, "law_year")} {year or "—"}</div>'
                        f'<h3>{safe_act_name}</h3><p>{safe_version}</p></div>',
                        unsafe_allow_html=True,
                    )
                    if st.button(t(lang, "browse_act"), key=f"home_law_{doc['id']}", use_container_width=True):
                        st.session_state.laws_query = str(doc.get("act_name") or "")
                        st.session_state.laws_search_mode = "name"
                        st.session_state.laws_search_mode_widget = "name"
                        st.session_state.act_search_input = str(doc.get("act_name") or "")
                        st.session_state.page = "laws"
                        st.rerun()
    st.markdown(f'<div class="disclaimer">⚖️ {t(lang, "library_updates_only")}</div>', unsafe_allow_html=True)


def localized_verification_status(lang: str, status: str) -> str:
    return {
        "unverified_upload": t(lang, "verification_unverified_upload"),
        "unverified": t(lang, "verification_unverified_upload"),
        "verified": t(lang, "verification_verified"),
    }.get(status, status)


def render_sources(lang: str, sources: list) -> None:
    if not sources:
        return
    with st.expander(t(lang, "sources"), expanded=False):
        st.caption(t(lang, "translated_note"))
        for s in sources:
            st.markdown(
                f"**{s.get('act_name')} — {t(lang, 'section')} {s.get('section_number') or s.get('section') or t(lang, 'unknown_section')}**"
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


def page_chat(lang: str, db: Database, rag: NyayMitraRAG) -> None:
    for index, msg in enumerate(st.session_state.messages):
        if msg.get("role") != "assistant" or msg.get("language", "en") == lang:
            continue
        prior_user = next(
            (row.get("content", "") for row in reversed(st.session_state.messages[:index]) if row.get("role") == "user"),
            "",
        )
        sources = msg.get("sources") or []
        msg["content"] = rag.compose_answer(prior_user, sources, lang)[0] if sources else t(lang, "insufficient")
        msg["language"] = lang

    if config.PUBLIC_MODE:
        st.caption(t(lang, "public_data_notice"))

    center, right = st.columns([7.1, 2.9], gap="medium")
    with center:
        st.markdown(
            f'<div class="chat-heading"><div><h1>🤖 {t(lang, "chat_title")}</h1>'
            f'<p>{t(lang, "chat_subtitle")}</p></div>'
            f'<div class="chat-status"><span class="chat-status-mark">✦</span> {t(lang, "powered")}</div></div>',
            unsafe_allow_html=True,
        )
        with st.container(border=True):
            if not st.session_state.messages:
                st.markdown(
                    f'<div class="chat-welcome"><strong>⚖️ {t(lang, "greeting")}</strong><br>'
                    f'{t(lang, "welcome")}</div>',
                    unsafe_allow_html=True,
                )
                actions = [
                    ("📖 " + t(lang, "action_explain_title"), t(lang, "action_explain_example"), "Explain section 3 of the Protection of Women from Domestic Violence Act, 2005 using only the indexed text."),
                    ("📄 " + t(lang, "action_summarize_title"), t(lang, "action_summarize_example"), "Summarize the purpose and structure of the Bharatiya Nyaya Sanhita, 2023 using only the indexed text."),
                    ("⚖️ " + t(lang, "action_compare_title"), t(lang, "action_compare_example"), "Compare the subjects covered by the Consumer Protection Act, 2019 and the Information Technology Act, 2000 using indexed text."),
                    ("💡 " + t(lang, "action_general_title"), t(lang, "action_general_example"), "What is an FIR? Answer only from the indexed documents and say if they do not contain enough information."),
                ]
                st.markdown(f'<div class="chat-actions-title">{t(lang, "common_task")}</div>', unsafe_allow_html=True)
                action_cols = st.columns(4, gap="small")
                for index, (title, example, prompt) in enumerate(actions):
                    with action_cols[index]:
                        st.markdown(f'<div class="chat-action-card"><strong>{title}</strong><span>{example}</span></div>', unsafe_allow_html=True)
                        if st.button(t(lang, "ask"), key=f"chat_action_{index}", use_container_width=True, help=prompt):
                            st.session_state.pending_question = prompt
                            st.rerun()
            for i, msg in enumerate(st.session_state.messages):
                with st.chat_message(msg["role"], avatar="⚖️" if msg["role"] == "assistant" else "👤"):
                    st.markdown(msg["content"])
                    if msg.get("sources"):
                        render_sources(lang, msg["sources"])
                    if msg["role"] == "assistant":
                        st.download_button(
                            t(lang, "copy_answer"),
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
                except Exception:
                    logger.exception("Chat answer failed")
                    answer = t(lang, "error_generic")
                    sources = []
                st.session_state.messages.append({"role": "assistant", "content": answer, "sources": sources, "language": lang})
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
        st.markdown(f'<div class="disclaimer">🛡️ {t(lang, "disclaimer")}<br>{t(lang, "disclaimer_full")}</div>', unsafe_allow_html=True)
    with right:
        with st.container():
            st.markdown(f'<div class="rail-title">💡 {t(lang, "suggested")}</div>', unsafe_allow_html=True)
            for i, (label, prompt) in enumerate(zip(suggested_questions(lang)[:4], suggested_question_prompts()[:4])):
                if st.button(label, key=f"sug_{i}", use_container_width=True):
                    st.session_state.pending_question = prompt
                    st.rerun()
            if not config.PUBLIC_MODE:
                recent_header, view_header = st.columns([4, 1])
                recent_header.markdown(f'<div class="rail-title">🕒 {t(lang, "recent_chats")}</div>', unsafe_allow_html=True)
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
            if not config.PUBLIC_MODE:
                st.caption(t(lang, "shared_history_note"))


def page_laws(lang: str, searcher: LegalSearch) -> None:
    st.markdown(
        f'<div class="panel hero"><h1>{t(lang, "laws_title")}</h1><p>{t(lang, "laws_intro")}</p></div>',
        unsafe_allow_html=True,
    )
    pending = (st.session_state.get("laws_query") or "").strip()
    if pending:
        st.session_state["act_search_input"] = pending
    mode_labels = {"name": t(lang, "act_name_option"), "number": t(lang, "act_number_option")}
    mode_keys = list(mode_labels)
    mode_default = st.session_state.get("laws_search_mode", "name")
    if mode_default not in mode_keys:
        mode_default = "name"
    chosen_mode = st.radio(
        t(lang, "act_search_mode"), mode_keys, horizontal=True,
        format_func=lambda key: mode_labels[key],
        index=mode_keys.index(mode_default),
        key="laws_search_mode_widget",
    )
    st.session_state.laws_search_mode = chosen_mode
    query = st.text_input(t(lang, "act_search"), placeholder=t(lang, "act_search_placeholder"), key="act_search_input")
    if pending:
        st.session_state.laws_query = ""

    st.caption(t(lang, "official_law_sources_note"))
    india_link, gazette_link = st.columns(2)
    india_code_url = "https://www.indiacode.nic.in/indiacode/home.jsp"
    if query.strip():
        india_code_url = "https://www.indiacode.nic.in/handle/123456789/1362/simple-search?query=" + quote_plus(query.strip())
    india_link.link_button(t(lang, "india_code_search"), india_code_url, use_container_width=True)
    gazette_link.link_button(t(lang, "gazette_link"), "https://egazette.gov.in/", use_container_width=True)

    docs = [d for d in searcher.db.list_documents(active_only=True) if str(d.get("original_filename") or "").lower().endswith(".pdf")]
    chunks_by_doc: dict[str, list[dict[str, Any]]] = {str(d["id"]): [] for d in docs}
    for chunk in searcher.db.active_chunks():
        if str(chunk.get("document_id")) in chunks_by_doc:
            chunks_by_doc[str(chunk["document_id"])].append(chunk)
    for doc in docs:
        doc["act_number"] = extract_act_number(doc, chunks_by_doc.get(str(doc["id"]), []))
        doc["year"] = act_year(doc.get("act_name", ""))

    def matches(doc: dict[str, Any]) -> bool:
        if not query.strip():
            return False
        if chosen_mode == "name":
            return query.casefold() in str(doc.get("act_name") or "").casefold()
        return query.casefold().replace("act no.", "").replace("no.", "").strip() in str(doc.get("act_number") or "").casefold()

    matches_found = [doc for doc in docs if matches(doc)]
    if query.strip():
        st.subheader(t(lang, "search_results"))
        if not matches_found:
            st.info(t(lang, "no_match"))
        else:
            for doc in matches_found:
                st.markdown(f"- **{doc['act_name']}** · {t(lang, 'act_number')}: {doc['act_number'] or t(lang, 'no_act_number')}")

    st.subheader(t(lang, "all_available_laws"))
    docs.sort(key=lambda d: (d.get("year") or 0, d.get("act_name") or ""), reverse=True)
    years = sorted({doc.get("year") or 0 for doc in docs}, reverse=True)
    if not docs:
        st.info(t(lang, "no_documents"))
    for year in years:
        st.markdown(f'<div class="law-year-heading">{t(lang, "law_year")} {year or "—"}</div>', unsafe_allow_html=True)
        year_docs = [d for d in docs if (d.get("year") or 0) == year]
        cols = st.columns(2, gap="medium")
        for col, doc in zip(cols, year_docs):
            with col:
                with st.expander(f"{doc['act_name']}  ·  Act No. {doc['act_number']}" if doc.get("act_number") else doc["act_name"]):
                    if doc.get("version_or_date"):
                        st.caption(str(doc["version_or_date"]))
                    chunks = chunks_by_doc.get(str(doc["id"]), [])
                    pages = sorted({str(c.get("page_number") or "") for c in chunks if str(c.get("page_number") or "").isdigit()}, key=int)
                    st.caption(f"{len(chunks)} · {t(lang, 'indexed_passages')} · {t(lang, 'page')} {pages[0] if pages else t(lang, 'none')}–{pages[-1] if pages else t(lang, 'none')}")
                    if pages:
                        page = st.selectbox(t(lang, "browse_pdf_page"), pages, key=f"law_page_{doc['id']}")
                        for chunk in (c for c in chunks if str(c.get("page_number")) == page):
                            st.write(chunk.get("text") or "")
                    st.caption(f"{t(lang, 'verification')}: {localized_verification_status(lang, str(doc.get('verification_status') or 'unverified'))}")


def page_quiz(lang: str, quiz: QuizService) -> None:
    st.markdown(
        f'<div class="panel hero"><h1>{t(lang, "quiz_title")}</h1><p>{t(lang, "quiz_intro")}</p></div>',
        unsafe_allow_html=True,
    )
    docs = quiz.law_documents()
    if not docs:
        st.info(t(lang, "no_documents"))
        return
    doc_by_id = {str(doc["id"]): doc for doc in docs}
    doc_ids = list(doc_by_id)
    selected_id = st.selectbox(
        t(lang, "quiz_select_act"), doc_ids,
        format_func=lambda value: doc_by_id[value].get("act_name") or value,
        key="quiz_document_select",
    )
    selected_doc = doc_by_id[selected_id]
    pool = quiz.law_question_pool(selected_id, lang)
    total_questions = len(pool)
    total_rounds = (total_questions + 9) // 10
    done_by_doc = st.session_state.quiz_completed_rounds
    completed = done_by_doc.get(selected_id, [])
    st.caption(t(lang, "quiz_source_note"))
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
        for item in st.session_state.quiz_round_questions:
            state_key = f"qradio_{selected_id}_{round_index}_{item['id']}"
            st.session_state.pop(state_key, None)

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
    choice = st.radio(t(lang, "choose_answer"), options, index=None, key=f"qradio_{selected_id}_{st.session_state.quiz_round_index}_{q['id']}")
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


def page_admin(lang: str, db: Database, processor: DocumentProcessor, rag: NyayMitraRAG) -> None:
    if not require_admin(lang):
        return
    st.markdown(
        f'<div class="panel hero"><h1>{t(lang, "admin_title")}</h1><p>{t(lang, "admin_intro")}</p></div>',
        unsafe_allow_html=True,
    )
    counts = db.counts()
    c1, c2, c3 = st.columns(3)
    c1.metric(t(lang, "metric_docs"), counts["documents"])
    c2.metric(t(lang, "metric_chunks"), counts["chunks"])
    c3.metric(t(lang, "metric_llm"), t(lang, "yes") if openai_configured() else t(lang, "no"))
    upload_form(lang, processor)
    st.subheader(t(lang, "indexed_documents"))
    docs = db.list_documents(active_only=True)
    if not docs:
        st.info(t(lang, "no_documents"))
    for doc in docs:
        with st.expander(f"{doc.get('act_name')} — {doc.get('original_filename')}"):
            st.json(
                {
                    "id": doc.get("id"),
                    "original_filename": doc.get("original_filename"),
                    "act_name": doc.get("act_name"),
                    "source_url": doc.get("source_url"),
                    "language": doc.get("language"),
                    "version_or_date": doc.get("version_or_date"),
                    "upload_date": doc.get("upload_date"),
                    "file_hash": doc.get("file_hash"),
                    "extraction_status": doc.get("extraction_status"),
                    "verification_status": doc.get("verification_status"),
                    "indexing_status": doc.get("indexing_status"),
                    "processing_error": doc.get("processing_error"),
                    "page_count": doc.get("page_count"),
                    "chunk_count": doc.get("chunk_count"),
                }
            )
            b1, b2 = st.columns(2)
            if b1.button(t(lang, "reprocess"), key=f"re_{doc['id']}"):
                try:
                    processor.reprocess(doc["id"])
                    refresh_rag(db)
                    st.success(t(lang, "processed_ok"))
                    st.rerun()
                except DocumentProcessingError as exc:
                    st.error(str(exc))
            if b2.button(t(lang, "remove"), key=f"rm_{doc['id']}"):
                processor.remove(doc["id"])
                refresh_rag(db)
                st.rerun()
    if st.button(t(lang, "rebuild_index"), type="primary"):
        refresh_rag(db)
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


def upload_form(lang: str, processor: DocumentProcessor) -> None:
    st.subheader(t(lang, "upload"))
    upload = st.file_uploader(t(lang, "choose_pdf"), type=["pdf"])
    name = st.text_input(t(lang, "act_or_document"))
    source = st.text_input(t(lang, "source_url"))
    version = st.text_input(t(lang, "version_date"))
    doc_lang_label = st.selectbox(t(lang, "doc_language"), list(LANGS.keys()))
    if st.button(t(lang, "process_pdf"), type="primary"):
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
            )
            refresh_rag(get_db())
            st.success(f"{t(lang, 'processed_ok')} {record.get('chunk_count', 0)} {t(lang, 'chunks_created')}")
        except DocumentProcessingError as exc:
            st.error(str(exc))


def page_upload(lang: str, processor: DocumentProcessor) -> None:
    if not require_admin(lang):
        return
    st.markdown(
        f'<div class="panel hero"><h1>{t(lang, "upload")}</h1><p>{t(lang, "admin_intro")}</p></div>',
        unsafe_allow_html=True,
    )
    upload_form(lang, processor)


def main() -> None:
    inject_css()
    init_state()
    db = get_db()
    rag = get_rag(db)
    processor = DocumentProcessor(db)
    searcher = LegalSearch(db)
    quiz = QuizService(db)
    header(LANGS[st.session_state.language])
    lang = LANGS[st.session_state.language]
    sidebar_nav(lang, db)
    page = st.session_state.page
    if page == "home":
        page_home(lang, db, searcher)
    elif page == "chat":
        page_chat(lang, db, rag)
    elif page == "laws":
        page_laws(lang, searcher)
    elif page == "quiz":
        page_quiz(lang, quiz)
    elif page == "admin":
        page_admin(lang, db, processor, rag)
    elif page == "upload":
        page_upload(lang, processor)
    else:
        page_home(lang, db, searcher)


main()
