"""Auth routes — real password auth + session tokens (PL-7).

Register and login both return a fresh session token; the frontend
stores it and sends it as `Authorization: Bearer <token>` on protected
endpoints (notably /api/documents/*). Logout invalidates the token.

The DB resets on every server restart so token persistence ends with
the process — that's by design per PL-7.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.auth import (
    create_session,
    current_user,
    delete_session,
    extract_token,
    hash_password,
    verify_password,
)
from app.db import get_conn
from app.models import LoginRequest, RegisterRequest, SessionOut, UserOut

router = APIRouter(prefix="/auth")


def _row_to_user(row: sqlite3.Row) -> UserOut:
    return UserOut(
        id=row["id"],
        email=row["email"],
        name=row["name"],
        created_at=row["created_at"],
    )


@router.post(
    "/register", response_model=SessionOut, status_code=status.HTTP_201_CREATED,
)
def register(payload: RegisterRequest) -> SessionOut:
    pw_hash = hash_password(payload.password)
    with get_conn() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO users (email, name, password_hash) VALUES (?, ?, ?)",
                (payload.email, payload.name, pw_hash),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="email already registered",
            )
        row = conn.execute(
            "SELECT id, email, name, created_at FROM users WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()

    user = _row_to_user(row)
    token = create_session(user.id)
    return SessionOut(user=user, token=token)


@router.post("/login", response_model=SessionOut)
def login(payload: LoginRequest) -> SessionOut:
    """Validate email + password, issue a new session token.

    Returns 401 for both unknown email and wrong password to avoid
    leaking which is the case to brute-force probers.
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, email, name, password_hash, created_at "
            "FROM users WHERE email = ?",
            (payload.email,),
        ).fetchone()

    if row is None or not verify_password(payload.password, row["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid email or password",
        )

    user = _row_to_user(row)
    token = create_session(user.id)
    return SessionOut(user=user, token=token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    _user: sqlite3.Row = Depends(current_user),
) -> None:
    """Invalidate the bearer token used to make the call.

    The dependency's job is to 401 if the caller isn't authenticated;
    we reuse the same `extract_token` helper here so the parsing logic
    has exactly one definition.
    """
    delete_session(extract_token(request))


@router.get("/me", response_model=UserOut)
def me(user: sqlite3.Row = Depends(current_user)) -> UserOut:
    """Return the current user — used by the frontend to validate a
    stored token survives the page reload before showing the editor."""
    return _row_to_user(user)
