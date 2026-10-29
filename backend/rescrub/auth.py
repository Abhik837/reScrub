"""Accounts and sign-in sessions.

- Passwords: Argon2id (argon2-cffi), re-hashed automatically when parameters change.
- Sessions: a random 256-bit token in an HttpOnly, Secure, SameSite=Lax cookie. Only its
  SHA-256 is stored, so a database leak does not reveal usable cookies.
- Every state-changing request must come from an allowed Origin (CSRF defense on top of
  SameSite=Lax).
"""

import hashlib
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import HTTPException, Request
from psycopg.errors import UniqueViolation

EMAIL_RE = re.compile(r"^[^\s@]{1,64}@[^\s@]{1,190}\.[^\s@]{2,63}$")
MIN_PASSWORD = 12
MAX_PASSWORD = 256  # Argon2 hashes any length; this only bounds request size

_hasher = PasswordHasher()  # Argon2id, library defaults (RFC 9106 "low memory" profile)
# Verified when the email is unknown, so response time doesn't reveal which accounts exist.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def normalize_email(email: str) -> str:
    return email.strip().lower()


def valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email)) and len(email) <= 254


class EmailTaken(ValueError):
    pass


def password_problem(password: str, email: str = "") -> str | None:
    if len(password) < MIN_PASSWORD:
        return f"Use at least {MIN_PASSWORD} characters."
    if len(password) > MAX_PASSWORD:
        return f"Use at most {MAX_PASSWORD} characters."
    name = email.split("@")[0]
    # Fewer than 8 characters besides the email name ("jordan2024!!") is mostly guessable.
    if len(set(password)) < 4 or (len(name) >= 4 and name in password.lower() and len(password) - len(name) < 8):
        return "Choose a password that is harder to guess (not your email or a repeated character)."
    return None


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def _token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


# --- users ------------------------------------------------------------------

def create_user(pool, email: str, password: str, role: str = "member") -> str:
    email = normalize_email(email)
    if not valid_email(email):
        raise ValueError("That is not a valid email address.")
    if problem := password_problem(password, email):
        raise ValueError(problem)
    uid = str(uuid.uuid4())
    try:
        with pool.connection() as c:
            c.execute("INSERT INTO users (id, email, password_hash, role) VALUES (%s, %s, %s, %s)",
                      (uid, email, hash_password(password), role))
    except UniqueViolation:
        raise EmailTaken("An account with this email already exists.") from None
    return uid


def set_password(pool, email: str, password: str) -> bool:
    """Change a password and sign the user out everywhere."""
    if problem := password_problem(password, normalize_email(email)):
        raise ValueError(problem)
    with pool.connection() as c, c.transaction():
        row = c.execute(
            "UPDATE users SET password_hash = %s, password_changed_at = now() WHERE email = %s RETURNING id",
            (hash_password(password), normalize_email(email)),
        ).fetchone()
        if row:
            c.execute("DELETE FROM auth_sessions WHERE user_id = %s", (row["id"],))
    return row is not None


def set_disabled(pool, email: str, disabled: bool) -> bool:
    with pool.connection() as c, c.transaction():
        row = c.execute("UPDATE users SET disabled = %s WHERE email = %s RETURNING id",
                        (disabled, normalize_email(email))).fetchone()
        if row and disabled:
            c.execute("DELETE FROM auth_sessions WHERE user_id = %s", (row["id"],))
    return row is not None


def list_users(pool) -> list[dict]:
    with pool.connection() as c:
        return c.execute("SELECT email, role, disabled, created_at, last_login_at FROM users ORDER BY email").fetchall()


def _burn_time() -> None:
    """Spend about as long as a real password check."""
    try:
        _hasher.verify(_DUMMY_HASH, "not-the-password")
    except VerificationError:
        pass


def authenticate(pool, email: str, password: str) -> dict | None:
    """The user row if the email/password pair is right and the account is enabled."""
    email = normalize_email(email)
    if not valid_email(email) or len(password) > MAX_PASSWORD:
        _burn_time()
        return None
    with pool.connection() as c:
        user = c.execute("SELECT id, email, role, disabled, password_hash FROM users WHERE email = %s",
                         (email,)).fetchone()
    try:
        _hasher.verify(user["password_hash"] if user else _DUMMY_HASH, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return None
    if user is None or user["disabled"]:
        return None
    if _hasher.check_needs_rehash(user["password_hash"]):
        with pool.connection() as c:
            c.execute("UPDATE users SET password_hash = %s WHERE id = %s", (hash_password(password), user["id"]))
    return user


# --- sessions ---------------------------------------------------------------

def start_session(pool, user_id, ttl: timedelta) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + ttl
    with pool.connection() as c, c.transaction():
        c.execute("INSERT INTO auth_sessions (token_hash, user_id, expires_at) VALUES (%s, %s, %s)",
                  (_token_hash(token), user_id, expires))
        c.execute("UPDATE users SET last_login_at = now() WHERE id = %s", (user_id,))
        # Housekeeping: drop this user's expired sessions.
        c.execute("DELETE FROM auth_sessions WHERE user_id = %s AND expires_at < now()", (user_id,))
    return token, expires


def user_for_token(pool, token: str) -> dict | None:
    if not token or len(token) > 100:
        return None
    with pool.connection() as c:
        row = c.execute(
            """SELECT u.id, u.email, u.role, s.last_seen_at FROM auth_sessions s JOIN users u ON u.id = s.user_id
               WHERE s.token_hash = %s AND s.expires_at > now() AND NOT u.disabled""",
            (_token_hash(token),),
        ).fetchone()
        if row and datetime.now(timezone.utc) - row["last_seen_at"] > timedelta(minutes=5):
            c.execute("UPDATE auth_sessions SET last_seen_at = now() WHERE token_hash = %s", (_token_hash(token),))
    return row


def end_session(pool, token: str) -> None:
    if token:
        with pool.connection() as c:
            c.execute("DELETE FROM auth_sessions WHERE token_hash = %s", (_token_hash(token),))


# --- request helpers --------------------------------------------------------

def check_origin(request: Request, allowed: list[str]) -> None:
    """CSRF: a state-changing request must name one of our origins.

    Browsers always send Origin on cross-origin and on same-origin POST/PATCH/DELETE from
    fetch/XHR, so a missing or foreign Origin is refused.
    """
    origin = request.headers.get("origin")
    if origin is None or origin not in allowed:
        raise HTTPException(403, "This request must come from the reScrub website.")
