"""Auth routes — placeholder for v1.

There is no real authentication yet: `POST /api/auth/login` accepts any email
and returns the matching user (creating one if needed). This is intentional
per PL-4 — the goal is to land users on the platform, not to gate access.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException, status

from app.db import get_conn
from app.models import LoginRequest, RegisterRequest, UserOut

router = APIRouter(prefix="/auth")


def _row_to_user(row: sqlite3.Row) -> UserOut:
    return UserOut(
        id=row["id"],
        email=row["email"],
        name=row["name"],
        created_at=row["created_at"],
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest) -> UserOut:
    with get_conn() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO users (email, name) VALUES (?, ?)",
                (payload.email, payload.name),
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
    return _row_to_user(row)


@router.post("/login", response_model=UserOut)
def login(payload: LoginRequest) -> UserOut:
    """Fake login: find the user by email, or create one on the fly.

    Two concurrent logins for the same new email could both see "no row"
    and race to insert; the second hits the UNIQUE constraint. Handle that
    by re-fetching, so neither caller sees a 500.
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, email, name, created_at FROM users WHERE email = ?",
            (payload.email,),
        ).fetchone()
        if row is None:
            try:
                conn.execute(
                    "INSERT INTO users (email, name) VALUES (?, ?)",
                    (payload.email, ""),
                )
            except sqlite3.IntegrityError:
                pass  # Lost the race — the user now exists, fall through.
            row = conn.execute(
                "SELECT id, email, name, created_at FROM users WHERE email = ?",
                (payload.email,),
            ).fetchone()
    return _row_to_user(row)
