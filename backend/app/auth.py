"""Auth utilities: password hashing + bearer-token dependency.

Tokens are random UUIDs stored in the `sessions` table and sent by the
frontend as `Authorization: Bearer <token>` on protected endpoints.
Tokens persist across restarts alongside the rest of the DB but expire
PRELEGAL_SESSION_TTL_DAYS after creation (default 30; 0 disables) — a
leaked token shouldn't stay valid forever.
"""

from __future__ import annotations

import os
import sqlite3
import uuid

import bcrypt
from fastapi import Depends, HTTPException, Request, status

from app.db import get_conn

DEFAULT_SESSION_TTL_DAYS = 30


def session_ttl_days() -> int:
    raw = os.environ.get("PRELEGAL_SESSION_TTL_DAYS", "")
    try:
        return int(raw) if raw else DEFAULT_SESSION_TTL_DAYS
    except ValueError:
        return DEFAULT_SESSION_TTL_DAYS


def hash_password(plain: str) -> str:
    """Hash a password with bcrypt. Returns the encoded hash as a string."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # Stored hash isn't a valid bcrypt string — treat as a non-match
        # rather than a 500. Shouldn't happen with our own writes.
        return False


def create_session(user_id: int) -> str:
    """Issue a new session token bound to user_id. Returns the token."""
    token = uuid.uuid4().hex
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id) VALUES (?, ?)",
            (token, user_id),
        )
    return token


def delete_session(token: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def purge_expired_sessions() -> None:
    """Delete sessions past their TTL. Called at startup so long-dead
    tokens don't pile up in the table; `current_user` filters them out
    per-request either way."""
    ttl = session_ttl_days()
    if ttl <= 0:
        return
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM sessions "
            "WHERE created_at <= datetime('now', '-' || ? || ' days')",
            (ttl,),
        )


def extract_token(request: Request) -> str:
    """Pull the bearer token from the Authorization header or 401."""
    auth_header = request.headers.get("authorization") or ""
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or malformed Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


def current_user(request: Request) -> sqlite3.Row:
    """FastAPI dependency: resolve `user_id` from the bearer token.

    Raises 401 if the header is missing/malformed or the token isn't in
    the sessions table. Endpoints that need to know who the caller is
    take this as a dependency:

        @router.get("/")
        def list_things(user: sqlite3.Row = Depends(current_user)):
            ...
    """
    token = extract_token(request)
    ttl = session_ttl_days()
    with get_conn() as conn:
        # Expiry is computed from the session's created_at rather than a
        # dedicated expires_at column — no schema migration needed on the
        # host-mounted volumes that already exist.
        row = conn.execute(
            """
            SELECT u.id, u.email, u.name, u.created_at
              FROM sessions s JOIN users u ON u.id = s.user_id
             WHERE s.token = ?
               AND (? <= 0 OR s.created_at > datetime('now', '-' || ? || ' days'))
            """,
            (token, ttl, ttl),
        ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired session",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return row


# Public dependency export — `Depends(current_user)` is the spelling
# routes use; this is just a small alias to keep signatures readable.
CurrentUser = Depends(current_user)
