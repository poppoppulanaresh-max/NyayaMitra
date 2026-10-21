from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config as _config

_config.PBKDF2_ITERATIONS = 2000
_config.USE_EMBEDDINGS = False

from database import Database
from document_processor import DocumentProcessor
from rag_engine import NyayMitraRAG


def fake_encode(texts, is_query=False):
    dim = 32
    rows = []
    for text in texts:
        vec = np.zeros(dim, dtype=np.float32)
        blob = (text or "").lower().encode("utf-8")[:400]
        for i, byte in enumerate(blob):
            vec[i % dim] += 1.0 + byte / 255.0
        for token in (text or "").lower().split():
            vec[hash(token) % dim] += 2.5
        norm = np.linalg.norm(vec) or 1.0
        rows.append(vec / norm)
    return np.stack(rows)


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "test.db")


@pytest.fixture
def processor(db: Database, tmp_path: Path) -> DocumentProcessor:
    return DocumentProcessor(db, uploads_dir=tmp_path / "uploads")


@pytest.fixture
def rag(db: Database) -> NyayMitraRAG:
    return NyayMitraRAG(db, encode_fn=fake_encode)
