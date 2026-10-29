"""SQLite persistence with parameterized queries and safe migrations."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

SCHEMA_VERSION = 3
DOCUMENT_ROW_COLUMNS = (
    "id", "original_filename", "stored_filename", "act_name", "source_url",
    "language", "version_or_date", "upload_date", "file_hash", "extraction_status",
    "verification_status", "indexing_status", "processing_error", "page_count",
    "chunk_count", "active",
)
CHUNK_ROW_COLUMNS = (
    "id", "chunk_key", "document_id", "act_name", "section_number", "section_title",
    "provision_type", "chapter", "chapter_title", "page_number", "source_url",
    "language", "verification_status", "text", "active", "original_filename",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _row_to_dict(row: Any, columns: list[str] | tuple[str, ...] = ()) -> dict[str, Any]:
    """Normalize sqlite rows and legacy tuple-like rows into a plain mapping.

    Streamlit can keep cached Database instances alive across a code reload. A
    row may therefore come from a connection configured differently by an old
    cached instance. Use cursor column names as a safe fallback instead of
    assuming every fetched row supports ``dict(row)``.
    """
    if isinstance(row, dict):
        return dict(row)
    try:
        keys = row.keys()
        return {str(key): row[key] for key in keys}
    except (AttributeError, KeyError, TypeError, IndexError):
        pass
    if isinstance(row, (tuple, list)):
        if not columns:
            raise TypeError("Tuple database rows require cursor column names")
        return dict(zip(columns, row))
    try:
        return dict(row)
    except (AttributeError, KeyError, TypeError, ValueError):
        return {
            name: getattr(row, name)
            for name in columns
            if hasattr(row, name)
        }


class Database:
    def __init__(
        self,
        db_path: Path,
        library_db: "Database | None" = None,
        uploads_dir: Path | None = None,
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.library_db = library_db if library_db and library_db.db_path.resolve() != self.db_path.resolve() else None
        self.uploads_dir = Path(uploads_dir or self.db_path.parent / "uploads")
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(str(self.db_path))
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def init_schema(self) -> None:
        with self.connect() as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            con.execute(
                """CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    original_filename TEXT NOT NULL,
                    stored_filename TEXT NOT NULL,
                    act_name TEXT,
                    source_url TEXT,
                    language TEXT,
                    version_or_date TEXT,
                    upload_date TEXT NOT NULL,
                    file_hash TEXT UNIQUE,
                    extraction_status TEXT,
                    verification_status TEXT,
                    indexing_status TEXT,
                    processing_error TEXT,
                    page_count INTEGER,
                    chunk_count INTEGER,
                    active INTEGER NOT NULL DEFAULT 1
                )"""
            )
            con.execute(
                """CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chunk_key TEXT UNIQUE,
                    document_id TEXT NOT NULL,
                    act_name TEXT,
                    section_number TEXT,
                    section_title TEXT,
                    provision_type TEXT,
                    chapter TEXT,
                    chapter_title TEXT,
                    page_number TEXT,
                    source_url TEXT,
                    language TEXT,
                    verification_status TEXT,
                    text TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY(document_id) REFERENCES documents(id)
                )"""
            )
            chunk_columns = {
                str(row["name"]) for row in con.execute("PRAGMA table_info(chunks)").fetchall()
            }
            for column in ("provision_type", "chapter", "chapter_title"):
                if column not in chunk_columns:
                    con.execute(f"ALTER TABLE chunks ADD COLUMN {column} TEXT")
            con.execute(
                """CREATE TABLE IF NOT EXISTS chat_sessions (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    language TEXT,
                    title TEXT
                )"""
            )
            con.execute(
                """CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    sources_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES chat_sessions(id)
                )"""
            )
            con.execute(
                """CREATE TABLE IF NOT EXISTS quiz_questions (
                    id INTEGER PRIMARY KEY,
                    question TEXT NOT NULL,
                    choice_a TEXT NOT NULL,
                    choice_b TEXT NOT NULL,
                    choice_c TEXT NOT NULL,
                    choice_d TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    explanation TEXT,
                    source TEXT,
                    educational_label INTEGER NOT NULL DEFAULT 1
                )"""
            )
            con.execute(
                """CREATE TABLE IF NOT EXISTS quiz_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    score INTEGER NOT NULL,
                    total INTEGER NOT NULL,
                    answers_json TEXT,
                    created_at TEXT NOT NULL
                )"""
            )
            con.execute(
                """CREATE TABLE IF NOT EXISTS admins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL
                )"""
            )
            con.execute(
                """CREATE TABLE IF NOT EXISTS accounts (
                    user_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )"""
            )
            con.execute(
                """CREATE TABLE IF NOT EXISTS search_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query TEXT NOT NULL,
                    category TEXT,
                    created_at TEXT NOT NULL
                )"""
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(document_id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_chunks_act ON chunks(act_name)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_chunks_section ON chunks(section_number)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_chunks_active ON chunks(active)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_docs_hash ON documents(file_hash)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON chat_messages(session_id)")
            self._migrate_legacy_quiz(con)
            con.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES(?, ?)",
                ("version", str(SCHEMA_VERSION)),
            )
            con.execute(
                "INSERT OR IGNORE INTO schema_meta(key, value) VALUES(?, ?)",
                ("content_revision", "0"),
            )

    @staticmethod
    def _bump_content_revision(con: sqlite3.Connection) -> None:
        row = con.execute(
            "SELECT value FROM schema_meta WHERE key = 'content_revision'"
        ).fetchone()
        revision = int(row["value"]) + 1 if row else 1
        con.execute(
            "INSERT INTO schema_meta(key, value) VALUES('content_revision', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(revision),),
        )

    def content_revision(self) -> int:
        with self.connect() as con:
            row = con.execute(
                "SELECT value FROM schema_meta WHERE key = 'content_revision'"
            ).fetchone()
        return int(row["value"]) if row else 0

    def _migrate_legacy_quiz(self, con: sqlite3.Connection) -> None:
        row = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='quiz'"
        ).fetchone()
        if not row:
            return
        count = con.execute("SELECT COUNT(*) AS c FROM quiz_questions").fetchone()["c"]
        if count:
            return
        try:
            legacy = con.execute("SELECT * FROM quiz").fetchall()
        except sqlite3.Error:
            return
        for r in legacy:
            keys = r.keys() if hasattr(r, "keys") else []
            # Support old schema: id, question, a, b, c, d, answer, explanation
            try:
                con.execute(
                    """INSERT OR IGNORE INTO quiz_questions
                    (id, question, choice_a, choice_b, choice_c, choice_d, answer, explanation, source, educational_label)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                    (
                        r["id"] if "id" in keys else r[0],
                        r["question"] if "question" in keys else r[1],
                        r["a"] if "a" in keys else r[2],
                        r["b"] if "b" in keys else r[3],
                        r["c"] if "c" in keys else r[4],
                        r["d"] if "d" in keys else r[5],
                        r["answer"] if "answer" in keys else r[6],
                        r["explanation"] if "explanation" in keys else r[7],
                        "Educational sample",
                    ),
                )
            except (sqlite3.Error, IndexError, KeyError):
                continue

    def seed_quiz(self, questions: list[dict[str, Any]]) -> None:
        with self.connect() as con:
            existing = con.execute("SELECT COUNT(*) AS c FROM quiz_questions").fetchone()["c"]
            if existing:
                return
            for q in questions:
                con.execute(
                    """INSERT INTO quiz_questions
                    (id, question, choice_a, choice_b, choice_c, choice_d, answer, explanation, source, educational_label)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        q["id"],
                        q["question"],
                        q["choice_a"],
                        q["choice_b"],
                        q["choice_c"],
                        q["choice_d"],
                        q["answer"],
                        q.get("explanation", ""),
                        q.get("source", "Educational sample"),
                        1 if q.get("educational_label", True) else 0,
                    ),
                )

    def seed_knowledge(self, items: list[dict[str, Any]]) -> None:
        with self.connect() as con:
            existing = con.execute("SELECT COUNT(*) AS c FROM chunks").fetchone()["c"]
            if existing:
                return
            if not items:
                return
            doc_id = "seed-educational"
            con.execute(
                """INSERT OR IGNORE INTO documents
                (id, original_filename, stored_filename, act_name, source_url, language,
                 version_or_date, upload_date, file_hash, extraction_status, verification_status,
                 indexing_status, processing_error, page_count, chunk_count, active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (
                    doc_id,
                    "legal_knowledge.json",
                    "legal_knowledge.json",
                    "Starter educational records",
                    "Educational sample — not official verified law",
                    "en",
                    "seed",
                    utc_now(),
                    "seed-educational",
                    "ok",
                    "educational_sample",
                    "indexed",
                    None,
                    None,
                    len(items),
                ),
            )
            for i, item in enumerate(items):
                con.execute(
                    """INSERT OR IGNORE INTO chunks
                    (chunk_key, document_id, act_name, section_number, section_title, provision_type,
                     chapter, chapter_title, page_number, source_url, language, verification_status, text, active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                    (
                        f"seed-{item.get('id', i)}",
                        doc_id,
                        item.get("act_name") or "Unknown",
                        item.get("section") or "unknown",
                        item.get("title") or "",
                        item.get("provision_type") or "section",
                        item.get("chapter") or "",
                        item.get("chapter_title") or "",
                        item.get("page") or "",
                        item.get("source") or "",
                        item.get("language") or "en",
                        item.get("verification_status") or "educational_sample",
                        item.get("text") or "",
                    ),
                )

    def get_admin_hash(self, username: str) -> Optional[str]:
        with self.connect() as con:
            row = con.execute(
                "SELECT password_hash FROM admins WHERE username = ?", (username,)
            ).fetchone()
            return row["password_hash"] if row else None

    def upsert_admin(self, username: str, password_hash: str) -> None:
        with self.connect() as con:
            con.execute(
                """INSERT INTO admins(username, password_hash) VALUES(?, ?)
                   ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash""",
                (username, password_hash),
            )

    def admin_count(self) -> int:
        with self.connect() as con:
            return con.execute("SELECT COUNT(*) AS c FROM admins").fetchone()["c"]

    def create_account(self, user_id: str, username: str, password_hash: str, is_admin: bool = False) -> None:
        with self.connect() as con:
            con.execute(
                "INSERT INTO accounts(user_id, username, password_hash, is_admin, created_at) VALUES(?, ?, ?, ?, ?)",
                (user_id, username.strip(), password_hash, int(is_admin), utc_now()),
            )

    def get_account(self, username: str) -> Optional[dict[str, Any]]:
        with self.connect() as con:
            row = con.execute(
                "SELECT user_id, username, password_hash, is_admin, created_at FROM accounts WHERE username = ? COLLATE NOCASE",
                (username.strip(),),
            ).fetchone()
            return dict(row) if row else None

    def account_count(self) -> int:
        with self.connect() as con:
            return con.execute("SELECT COUNT(*) AS c FROM accounts").fetchone()["c"]

    def sync_admin_account(self, username: str, password_hash: str) -> None:
        with self.connect() as con:
            con.execute(
                "UPDATE accounts SET password_hash = ?, is_admin = 1 WHERE username = ? COLLATE NOCASE",
                (password_hash, username.strip()),
            )

    def find_document_by_hash(self, file_hash: str) -> Optional[sqlite3.Row]:
        with self.connect() as con:
            row = con.execute(
                "SELECT * FROM documents WHERE file_hash = ? AND active = 1", (file_hash,)
            ).fetchone()
            overridden = con.execute("SELECT id, active FROM documents WHERE file_hash = ?", (file_hash,)).fetchone()
        if row:
            return row
        if self.library_db and not (overridden and not overridden["active"]):
            return self.library_db.find_document_by_hash(file_hash)
        return None

    def get_document(self, document_id: str) -> Optional[dict[str, Any]]:
        with self.connect() as con:
            row = con.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        if row:
            return dict(row)
        return self.library_db.get_document(document_id) if self.library_db else None

    def list_documents(self, active_only: bool = True) -> list[dict[str, Any]]:
        sql = "SELECT * FROM documents"
        params: tuple[Any, ...] = ()
        if active_only:
            sql += " WHERE active = 1"
        sql += " ORDER BY upload_date DESC"
        with self.connect() as con:
            cursor = con.execute(sql, params)
            local = [_row_to_dict(row, DOCUMENT_ROW_COLUMNS) for row in cursor.fetchall()]
            local_cursor = con.execute("SELECT id, file_hash FROM documents")
            local_all = [
                _row_to_dict(row, ("id", "file_hash"))
                for row in local_cursor.fetchall()
            ]
        if not self.library_db:
            return local
        overridden_ids = {str(row.get("id")) for row in local_all}
        local_hashes = {
            str(row.get("file_hash")) for row in local_all if row.get("file_hash")
        }
        shared_rows = self.library_db.list_documents(active_only=active_only)
        shared_docs = [
            _row_to_dict(row, DOCUMENT_ROW_COLUMNS) for row in (shared_rows or [])
        ]
        shared = [
            row for row in shared_docs
            if str(row.get("id")) not in overridden_ids
            and (not row.get("file_hash") or str(row.get("file_hash")) not in local_hashes)
        ]
        return sorted(local + shared, key=lambda row: str(row.get("upload_date") or ""), reverse=True)

    def upsert_document(self, record: dict[str, Any]) -> None:
        keys = [
            "id",
            "original_filename",
            "stored_filename",
            "act_name",
            "source_url",
            "language",
            "version_or_date",
            "upload_date",
            "file_hash",
            "extraction_status",
            "verification_status",
            "indexing_status",
            "processing_error",
            "page_count",
            "chunk_count",
            "active",
        ]
        placeholders = ",".join("?" for _ in keys)
        assignments = ",".join(f"{k}=excluded.{k}" for k in keys if k != "id")
        values = [record.get(k) for k in keys]
        if record.get("active") is None:
            values[keys.index("active")] = 1
        with self.connect() as con:
            con.execute(
                f"INSERT INTO documents ({','.join(keys)}) VALUES ({placeholders}) "
                f"ON CONFLICT(id) DO UPDATE SET {assignments}",
                values,
            )
            self._bump_content_revision(con)

    def replace_chunks(self, document_id: str, chunks: list[dict[str, Any]]) -> None:
        with self.connect() as con:
            con.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
            for ch in chunks:
                con.execute(
                    """INSERT INTO chunks
                    (chunk_key, document_id, act_name, section_number, section_title, provision_type,
                     chapter, chapter_title, page_number, source_url, language, verification_status, text, active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                    (
                        ch["chunk_key"],
                        document_id,
                        ch.get("act_name"),
                        ch.get("section_number") or "unknown",
                        ch.get("section_title") or "",
                        ch.get("provision_type") or "section",
                        ch.get("chapter") or "",
                        ch.get("chapter_title") or "",
                        ch.get("page_number") or "",
                        ch.get("source_url") or "",
                        ch.get("language") or "en",
                        ch.get("verification_status") or "unverified_upload",
                        ch.get("text") or "",
                    ),
                )
            self._bump_content_revision(con)

    def save_document_index(self, record: dict[str, Any], chunks: list[dict[str, Any]]) -> None:
        """Atomically replace one document record and its chunks."""
        keys = [
            "id", "original_filename", "stored_filename", "act_name", "source_url",
            "language", "version_or_date", "upload_date", "file_hash", "extraction_status",
            "verification_status", "indexing_status", "processing_error", "page_count",
            "chunk_count", "active",
        ]
        placeholders = ",".join("?" for _ in keys)
        assignments = ",".join(f"{key}=excluded.{key}" for key in keys if key != "id")
        values = [record.get(key) for key in keys]
        if record.get("active") is None:
            values[keys.index("active")] = 1
        with self.connect() as con:
            con.execute(
                f"INSERT INTO documents ({','.join(keys)}) VALUES ({placeholders}) "
                f"ON CONFLICT(id) DO UPDATE SET {assignments}",
                values,
            )
            con.execute("DELETE FROM chunks WHERE document_id = ?", (record["id"],))
            for chunk in chunks:
                con.execute(
                    """INSERT INTO chunks
                    (chunk_key, document_id, act_name, section_number, section_title, provision_type,
                     chapter, chapter_title, page_number, source_url, language, verification_status, text, active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                    (
                        chunk["chunk_key"], record["id"], chunk.get("act_name"),
                        chunk.get("section_number") or "unknown", chunk.get("section_title") or "",
                        chunk.get("provision_type") or "section", chunk.get("chapter") or "",
                        chunk.get("chapter_title") or "", chunk.get("page_number") or "",
                        chunk.get("source_url") or "", chunk.get("language") or "en",
                        chunk.get("verification_status") or "unverified_upload", chunk.get("text") or "",
                    ),
                )
            self._bump_content_revision(con)

    def deactivate_document(self, document_id: str) -> None:
        # A profile can hide a shared library item without changing the common
        # library for other users by storing an inactive local override.
        if getattr(self, "library_db", None) is not None:
            with self.connect() as con:
                local_exists = con.execute("SELECT 1 FROM documents WHERE id = ?", (document_id,)).fetchone()
            if not local_exists:
                shared_reader = getattr(self.library_db, "get_document", None)
                shared = shared_reader(document_id) if callable(shared_reader) else None
                if shared is not None:
                    tombstone = dict(shared)
                    tombstone["active"] = 0
                    tombstone["indexing_status"] = "removed"
                    self.upsert_document(tombstone)
        with self.connect() as con:
            con.execute("UPDATE documents SET active = 0, indexing_status = ? WHERE id = ?", ("removed", document_id))
            con.execute("UPDATE chunks SET active = 0 WHERE document_id = ?", (document_id,))
            self._bump_content_revision(con)

    def active_chunks(self) -> list[dict[str, Any]]:
        with self.connect() as con:
            cursor = con.execute(
                "SELECT c.*, d.original_filename FROM chunks c "
                "LEFT JOIN documents d ON d.id = c.document_id "
                "WHERE c.active = 1 AND length(trim(c.text)) > 0 ORDER BY c.document_id, c.id"
            )
            local_chunks = [
                _row_to_dict(row, CHUNK_ROW_COLUMNS) for row in cursor.fetchall()
            ]
            local_cursor = con.execute("SELECT id, file_hash FROM documents")
            local_docs = [
                _row_to_dict(row, ("id", "file_hash"))
                for row in local_cursor.fetchall()
            ]
        if not self.library_db:
            return local_chunks
        overridden_ids = {str(row.get("id")) for row in local_docs}
        local_hashes = {
            str(row.get("file_hash")) for row in local_docs if row.get("file_hash")
        }
        shared_rows = self.library_db.list_documents(active_only=False)
        shared_docs = [
            _row_to_dict(row, DOCUMENT_ROW_COLUMNS) for row in (shared_rows or [])
        ]
        shared_hash_by_id = {str(row["id"]): str(row.get("file_hash") or "") for row in shared_docs}
        shared_chunk_rows = self.library_db.active_chunks()
        shared_chunks_all = [
            _row_to_dict(row, CHUNK_ROW_COLUMNS) for row in (shared_chunk_rows or [])
        ]
        shared_chunks = [
            row for row in shared_chunks_all
            if str(row.get("document_id")) not in overridden_ids
            and shared_hash_by_id.get(str(row.get("document_id")), "") not in local_hashes
        ]
        return shared_chunks + local_chunks

    def document_chunks(self, document_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        """Read active chunks for one visible document without scanning the library."""
        library_db = getattr(self, "library_db", None)
        with self.connect() as con:
            local_doc = con.execute(
                "SELECT active FROM documents WHERE id = ?", (str(document_id),)
            ).fetchone()
            if local_doc:
                if not local_doc["active"]:
                    return []
                limit_sql = " LIMIT ?" if limit is not None else ""
                params = (str(document_id), int(limit)) if limit is not None else (str(document_id),)
                cursor = con.execute(
                    "SELECT c.*, d.original_filename FROM chunks c "
                    "LEFT JOIN documents d ON d.id = c.document_id "
                    "WHERE c.document_id = ? AND c.active = 1 "
                    "AND length(trim(c.text)) > 0 ORDER BY c.id" + limit_sql,
                    params,
                )
                columns = tuple(column[0] for column in (cursor.description or ()))
                rows = cursor.fetchall()
                return [_row_to_dict(row, columns) for row in rows]
        if library_db is None:
            return []
        library_reader = getattr(library_db, "document_chunks", None)
        if callable(library_reader):
            try:
                shared_rows = library_reader(document_id, limit)
                if shared_rows is not None:
                    return [_row_to_dict(row) for row in shared_rows]
            except (AttributeError, TypeError):
                # A cached Database instance from a previous app revision may
                # not have document_chunks yet. Fall through to the same
                # document-scoped SQL query without scanning all library text.
                pass
        # Streamlit may retain a Database object created by an older app
        # revision. Use its connection only when the legacy object exposes it;
        # otherwise the preview/quiz should degrade gracefully instead of
        # crashing the whole page with AttributeError.
        connector = getattr(library_db, "connect", None)
        if not callable(connector):
            return []
        limit_sql = " LIMIT ?" if limit is not None else ""
        params = (str(document_id), int(limit)) if limit is not None else (str(document_id),)
        with connector() as con:
            cursor = con.execute(
                "SELECT c.*, d.original_filename FROM chunks c "
                "LEFT JOIN documents d ON d.id = c.document_id "
                "WHERE c.document_id = ? AND c.active = 1 "
                "AND length(trim(c.text)) > 0 ORDER BY c.id" + limit_sql,
                params,
            )
            columns = tuple(column[0] for column in (cursor.description or ()))
            rows = cursor.fetchall()
        return [_row_to_dict(row, columns) for row in rows]

    def search_chunks(
        self,
        act_name: str = "",
        section_number: str = "",
        section_title: str = "",
        keyword: str = "",
        document_id: str = "",
        category: str = "",
    ) -> list[dict[str, Any]]:
        clauses = ["active = 1"]
        params: list[Any] = []
        if document_id:
            clauses.append("document_id = ?")
            params.append(document_id)
        if act_name:
            clauses.append("lower(act_name) LIKE ?")
            params.append(f"%{act_name.lower()}%")
        if section_number:
            clauses.append("lower(ifnull(section_number,'')) LIKE ?")
            params.append(f"%{section_number.lower()}%")
        if section_title:
            clauses.append("lower(ifnull(section_title,'')) LIKE ?")
            params.append(f"%{section_title.lower()}%")
        if keyword:
            clauses.append(
                "(lower(text) LIKE ? OR lower(ifnull(act_name,'')) LIKE ? "
                "OR lower(ifnull(section_title,'')) LIKE ? OR lower(ifnull(section_number,'')) LIKE ?)"
            )
            like = f"%{keyword.lower()}%"
            params.extend([like, like, like, like])
        if category == "Acts" and keyword:
            clauses.append("lower(ifnull(act_name,'')) LIKE ?")
            params.append(f"%{keyword.lower()}%")
        elif category == "Sections" and keyword:
            clauses.append(
                "(lower(ifnull(section_number,'')) LIKE ? OR lower(ifnull(section_title,'')) LIKE ?)"
            )
            like = f"%{keyword.lower()}%"
            params.extend([like, like])
        sql = f"SELECT * FROM chunks WHERE {' AND '.join(clauses)} ORDER BY act_name, id LIMIT 200"
        with self.connect() as con:
            local = [dict(r) for r in con.execute(sql, params).fetchall()]
            local_docs = con.execute("SELECT id, file_hash FROM documents").fetchall()
        if not self.library_db:
            return local
        overridden_ids = {str(row["id"]) for row in local_docs}
        local_hashes = {str(row["file_hash"]) for row in local_docs if row["file_hash"]}
        shared_docs = self.library_db.list_documents(active_only=False)
        shared_hash_by_id = {str(row["id"]): str(row.get("file_hash") or "") for row in shared_docs}
        shared = [
            row for row in self.library_db.search_chunks(act_name, section_number, section_title, keyword, document_id, category)
            if str(row.get("document_id")) not in overridden_ids
            and shared_hash_by_id.get(str(row.get("document_id")), "") not in local_hashes
        ]
        return (shared + local)[:200]

    def available_acts(self) -> list[str]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT DISTINCT act_name FROM chunks WHERE active = 1 AND act_name IS NOT NULL AND act_name != '' ORDER BY act_name"
            ).fetchall()
            local = [r["act_name"] for r in rows]
        if not self.library_db:
            return local
        return sorted(set(local) | set(self.library_db.available_acts()))

    def counts(self) -> dict[str, int]:
        with self.connect() as con:
            local_docs = con.execute("SELECT COUNT(*) AS c FROM documents WHERE active = 1").fetchone()["c"]
            local_chunks = con.execute(
                "SELECT COUNT(*) AS c FROM chunks WHERE active = 1 AND length(trim(text)) > 0"
            ).fetchone()["c"]
            local_rows = con.execute("SELECT id, file_hash, active FROM documents").fetchall()
        if not self.library_db:
            return {"documents": local_docs, "chunks": local_chunks}
        local_ids = {str(row["id"]) for row in local_rows}
        local_hashes = {str(row["file_hash"]) for row in local_rows if row["file_hash"] and row["active"]}
        shared_docs = [
            row for row in self.library_db.list_documents()
            if str(row.get("id")) not in local_ids
            and (not row.get("file_hash") or str(row.get("file_hash")) not in local_hashes)
        ]
        shared_doc_ids = [str(row["id"]) for row in shared_docs]
        shared_chunk_count = 0
        if shared_doc_ids:
            placeholders = ",".join("?" for _ in shared_doc_ids)
            with self.library_db.connect() as con:
                shared_chunk_count = int(con.execute(
                    f"SELECT COUNT(*) FROM chunks WHERE active = 1 "
                    f"AND length(trim(text)) > 0 AND document_id IN ({placeholders})",
                    shared_doc_ids,
                ).fetchone()[0])
        return {"documents": local_docs + len(shared_docs), "chunks": local_chunks + shared_chunk_count}

    def log_search(self, query: str, category: str) -> None:
        with self.connect() as con:
            con.execute(
                "INSERT INTO search_history(query, category, created_at) VALUES (?, ?, ?)",
                (query, category, utc_now()),
            )

    def recent_searches(self, limit: int = 5) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT query, category, created_at FROM search_history ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def ensure_session(self, session_id: str, language: str, title: str) -> None:
        with self.connect() as con:
            con.execute(
                """INSERT OR IGNORE INTO chat_sessions(id, created_at, language, title)
                   VALUES (?, ?, ?, ?)""",
                (session_id, utc_now(), language, title[:120]),
            )

    def add_message(self, session_id: str, role: str, content: str, sources: list[dict[str, Any]] | None) -> None:
        with self.connect() as con:
            con.execute(
                """INSERT INTO chat_messages(session_id, role, content, sources_json, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    session_id,
                    role,
                    content,
                    json.dumps(sources or [], ensure_ascii=False),
                    utc_now(),
                ),
            )

    def recent_chats(self, limit: int = 5) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute(
                """SELECT m.content AS question, m.created_at, m.session_id
                   FROM chat_messages m
                   WHERE m.role = 'user'
                   ORDER BY m.id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def list_chat_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute(
                """SELECT s.id, s.created_at, s.language, s.title,
                          MAX(m.created_at) AS updated_at, COUNT(m.id) AS message_count
                   FROM chat_sessions s LEFT JOIN chat_messages m ON m.session_id = s.id
                   GROUP BY s.id ORDER BY COALESCE(MAX(m.id), 0) DESC LIMIT ?""",
                (max(1, min(int(limit), 100)),),
            ).fetchall()
            return [dict(r) for r in rows]

    def chat_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT role, content, sources_json, created_at FROM chat_messages WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                try:
                    item["sources"] = json.loads(item.pop("sources_json") or "[]")
                except (TypeError, json.JSONDecodeError):
                    item["sources"] = []
                result.append(item)
            return result

    def delete_chat_session(self, session_id: str) -> None:
        with self.connect() as con:
            con.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
            con.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))

    def quiz_questions(self) -> list[dict[str, Any]]:
        with self.connect() as con:
            return [dict(r) for r in con.execute("SELECT * FROM quiz_questions ORDER BY id").fetchall()]

    def save_quiz_question(self, question: dict[str, Any]) -> int:
        required = ("question", "choice_a", "choice_b", "choice_c", "choice_d", "answer")
        values = {key: str(question.get(key) or "").strip() for key in required}
        if any(not value for value in values.values()):
            raise ValueError("Question, all four choices, and the correct answer are required.")
        values["answer"] = values["answer"].upper()
        if values["answer"] not in {"A", "B", "C", "D"}:
            raise ValueError("Correct answer must be A, B, C, or D.")
        qid = question.get("id")
        with self.connect() as con:
            if qid is None:
                qid = con.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM quiz_questions").fetchone()[0]
            con.execute(
                """INSERT INTO quiz_questions
                   (id, question, choice_a, choice_b, choice_c, choice_d, answer, explanation, source, educational_label)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET question=excluded.question, choice_a=excluded.choice_a,
                   choice_b=excluded.choice_b, choice_c=excluded.choice_c, choice_d=excluded.choice_d,
                   answer=excluded.answer, explanation=excluded.explanation, source=excluded.source,
                   educational_label=excluded.educational_label""",
                (qid, values["question"], values["choice_a"], values["choice_b"], values["choice_c"],
                 values["choice_d"], values["answer"], str(question.get("explanation") or "").strip(),
                 str(question.get("source") or "").strip(), 1 if question.get("educational_label", True) else 0),
            )
            return int(qid)

    def delete_quiz_question(self, question_id: int) -> None:
        with self.connect() as con:
            con.execute("DELETE FROM quiz_questions WHERE id = ?", (int(question_id),))

    def save_quiz_attempt(self, score: int, total: int, answers: dict[str, Any]) -> int:
        with self.connect() as con:
            cur = con.execute(
                "INSERT INTO quiz_attempts(score, total, answers_json, created_at) VALUES (?, ?, ?, ?)",
                (score, total, json.dumps(answers, ensure_ascii=False), utc_now()),
            )
            return int(cur.lastrowid)

    def recent_quiz_attempts(self, limit: int = 5) -> list[dict[str, Any]]:
        with self.connect() as con:
            return [
                dict(r)
                for r in con.execute(
                    "SELECT id, score, total, created_at FROM quiz_attempts ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            ]
