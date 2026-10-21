"""Administrator authentication using PBKDF2-HMAC (no plaintext passwords)."""
from __future__ import annotations

import hashlib
import hmac
import secrets

import config
from database import Database


def hash_password(password: str, salt: bytes | None = None, iterations: int | None = None) -> str:
    if iterations is None:
        iterations = config.PBKDF2_ITERATIONS
    if salt is None:
        salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iter_s, salt_hex, hash_hex = stored.split("$", 3)
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    try:
        iterations = int(iter_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(digest, expected)


def bootstrap_admin(db: Database) -> str:
    """Create/update admin from environment. Returns status: configured|missing|unchanged."""
    username = (config.ADMIN_USERNAME or "admin").strip()
    password = config.ADMIN_PASSWORD
    if not password:
        if db.admin_count() == 0:
            return "missing"
        return "unchanged"
    existing = db.get_admin_hash(username)
    if existing and verify_password(password, existing):
        return "unchanged"
    db.upsert_admin(username, hash_password(password))
    return "configured"


def authenticate(db: Database, username: str, password: str) -> bool:
    if not username or not password:
        return False
    stored = db.get_admin_hash(username.strip())
    if not stored:
        return False
    return verify_password(password, stored)


def random_token() -> str:
    return secrets.token_hex(16)


def safe_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
