"""Quiz data, scoring, and persistence."""
from __future__ import annotations

import hashlib
import random
import re
from collections import OrderedDict
from typing import Any

from database import Database
from translations import t


class QuizService:
    def __init__(self, db: Database):
        self.db = db
        self._pool_cache: OrderedDict[tuple[Any, ...], list[dict[str, Any]]] = OrderedDict()

    def questions(self) -> list[dict[str, Any]]:
        return self.db.quiz_questions()

    def law_documents(self) -> list[dict[str, Any]]:
        return [
            doc for doc in self.db.list_documents(active_only=True)
            if str(doc.get("original_filename") or "").lower().endswith(".pdf")
            and doc.get("indexing_status") == "indexed"
        ]

    def law_question_pool(self, document_id: str, lang: str = "en") -> list[dict[str, Any]]:
        """Build source-locating quiz items from section openings in the selected PDF."""
        document = next((d for d in self.law_documents() if str(d["id"]) == str(document_id)), None)
        if not document:
            return []
        library_db = getattr(self.db, "library_db", None)
        local_revision_reader = getattr(self.db, "content_revision", None)
        shared_revision_reader = getattr(library_db, "content_revision", None)
        local_revision = local_revision_reader() if callable(local_revision_reader) else 0
        shared_revision = shared_revision_reader() if callable(shared_revision_reader) else 0
        cache_key = (str(document_id), lang, local_revision, shared_revision)
        if cache_key in self._pool_cache:
            self._pool_cache.move_to_end(cache_key)
            return self._pool_cache[cache_key]
        chunk_reader = getattr(self.db, "document_chunks", None)
        if callable(chunk_reader):
            try:
                chunks = chunk_reader(str(document_id))
            except AttributeError:
                # Cached database resources can outlive a source-code update.
                # The current Database method handles older shared DB objects;
                # this last resort preserves quiz availability if that method
                # itself comes from an older class definition.
                chunks = self._legacy_document_chunks(str(document_id))
        else:
            chunks = self._legacy_document_chunks(str(document_id))
        line_pattern = re.compile(r"(?m)^\s*(\d{1,3}[A-Z]?)\.\s+([^\n]{8,180})", re.IGNORECASE)
        entries: dict[str, tuple[str, str]] = {}
        for chunk in chunks:
            page = str(chunk.get("page_number") or "?")
            for number, raw_excerpt in line_pattern.findall(str(chunk.get("text") or "")):
                excerpt = re.sub(r"\s+", " ", raw_excerpt).strip(" .—-\t")
                alpha = sum(char.isalpha() for char in excerpt)
                alnum = sum(char.isalnum() for char in excerpt)
                if alpha < 12 or not alnum or alpha / alnum < 0.65:
                    continue
                if any(marker in excerpt.casefold() for marker in ("subs. by", "ins. by", "the gazette", "omitted")):
                    continue
                entries.setdefault(number.upper(), (excerpt[:155].rstrip(" ,;-") + ("…" if len(excerpt) > 155 else ""), page))

        section_numbers = list(entries)
        questions = []
        for index, (number, (excerpt, page)) in enumerate(entries.items(), start=1):
            seed = hashlib.sha256(f"{document_id}:{number}".encode("utf-8")).hexdigest()
            rng = random.Random(seed)
            distractors = rng.sample([other for other in section_numbers if other != number], min(3, len(section_numbers) - 1))
            options = [number, *distractors]
            rng.shuffle(options)
            labels = ["A", "B", "C", "D"][:len(options)]
            correct = labels[options.index(number)]
            choices = {f"choice_{letter.lower()}": f"Section {option}" for letter, option in zip(labels, options)}
            questions.append({
                "id": index,
                "question": t(lang, "quiz_excerpt_question").format(act=document["act_name"], excerpt=excerpt),
                **choices,
                "answer": correct,
                "explanation": t(lang, "quiz_excerpt_explanation").format(section=number),
                "source": f"{document.get('original_filename')} · page {page}",
                "educational_label": 1,
            })
        self._pool_cache[cache_key] = questions
        self._pool_cache.move_to_end(cache_key)
        while len(self._pool_cache) > 48:
            self._pool_cache.popitem(last=False)
        return questions

    def _legacy_document_chunks(self, document_id: str) -> list[dict[str, Any]]:
        """Read one Act directly when an older cached Database lacks the helper."""
        source_db = getattr(self.db, "library_db", None) or self.db
        with source_db.connect() as con:
            rows = con.execute(
                "SELECT c.*, d.original_filename FROM chunks c "
                "LEFT JOIN documents d ON d.id = c.document_id "
                "WHERE c.document_id = ? AND c.active = 1 "
                "AND length(trim(c.text)) > 0 ORDER BY c.id",
                (document_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def round_questions(self, document_id: str, round_index: int, lang: str = "en", size: int = 10) -> list[dict[str, Any]]:
        pool = self.law_question_pool(document_id, lang)
        start = max(0, int(round_index)) * max(1, int(size))
        return pool[start:start + size]

    def score_items(self, questions: list[dict[str, Any]], answers: dict[int, str]) -> tuple[int, int, list[dict[str, Any]]]:
        details = []
        for row in questions:
            qid = int(row["id"])
            selected = (answers.get(qid) or "")[:1].upper()
            is_correct = selected == str(row["answer"]).strip().upper()[:1]
            details.append({**row, "selected": selected, "is_correct": is_correct})
        return sum(row["is_correct"] for row in details), len(details), details

    def score(self, answers: dict[int, str]) -> tuple[int, int, list[dict[str, Any]]]:
        rows = self.questions()
        details = []
        correct_count = 0
        for row in rows:
            qid = int(row["id"])
            selected = (answers.get(qid) or "")[:1].upper()
            is_correct = selected == str(row["answer"]).strip().upper()[:1]
            if is_correct:
                correct_count += 1
            details.append({**row, "selected": selected, "is_correct": is_correct})
        return correct_count, len(rows), details

    def persist(self, score_value: int, total: int, answers: dict[int, str]) -> int:
        serializable = {str(k): v for k, v in answers.items()}
        return self.db.save_quiz_attempt(score_value, total, serializable)

    def recent(self, limit: int = 5) -> list[dict[str, Any]]:
        return self.db.recent_quiz_attempts(limit)
