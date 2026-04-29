"""Auth utilities: password hashing + bearer-token dependency.

Tokens are random UUIDs stored in the `sessions` table and sent by the
frontend as `Authorization: Bearer <token>` on protected endpoints. The
DB resets on every server restart per PL-7, so token persistence beyond
process lifetime isn't a goal — but per-session isolation across users
is, which is what this layer enforces.
"""

from __future__ import annotations

import sqlite3
import uuid

import bcrypt
from fastapi import Depends, HTTPException, Request, status

from app.db import get_conn


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
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT u.id, u.email, u.name, u.created_at
              FROM sessions s JOIN users u ON u.id = s.user_id
             WHERE s.token = ?
            """,
            (token,),
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
