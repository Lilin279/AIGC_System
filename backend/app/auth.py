from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from app.database import connect
from app.models import User


PASSWORD_ITERATIONS = 210_000
SESSION_DAYS = 7


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${_encode(salt)}${_encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = _decode(salt_text)
        expected = _decode(digest_text)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def issue_session(user_id: str) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    token_hash = _token_hash(token)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).isoformat()
    with connect() as connection:
        connection.execute(
            "INSERT INTO sessions(token_hash, user_id, expires_at) VALUES (?, ?, ?)",
            (token_hash, user_id, expires_at),
        )
    return token, expires_at


def revoke_session(token: str) -> None:
    with connect() as connection:
        connection.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


def user_from_token(token: str) -> User | None:
    now = datetime.now(timezone.utc).isoformat()
    with connect() as connection:
        connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        row = connection.execute(
            """
            SELECT users.id, users.name, users.role, users.organization, users.username,
                   users.email, users.phone, users.avatar_url, users.account_status,
                   users.must_change_password, users.student_no, users.department,
                   users.title, users.rejection_reason
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token_hash = ? AND sessions.expires_at > ?
              AND users.is_active = 1 AND users.account_status != 'disabled'
            """,
            (_token_hash(token), now),
        ).fetchone()
    return User(**dict(row)) if row else None


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii"))
