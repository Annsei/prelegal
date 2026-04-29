"""Documents CRUD — drafts the user has saved.

All endpoints require a valid bearer token. A user can only see and
modify their own documents; anything else returns 404 to avoid leaking
existence of other users' rows.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import current_user
from app.db import get_conn
from app.models import (
    DocumentCreateRequest,
    DocumentOut,
    DocumentSummary,
    DocumentUpdateRequest,
)

router = APIRouter(prefix="/documents")


def _safe_load_state(raw: str) -> dict[str, Any]:
    """Decode a row's state_json. Bad JSON falls back to empty so a
    partially-corrupted row doesn't take down the list endpoint."""
    try:
        loaded = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _row_to_summary(row: sqlite3.Row) -> DocumentSummary:
    return DocumentSummary(
        id=row["id"],
        doc_id=row["doc_id"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_full(row: sqlite3.Row) -> DocumentOut:
    return DocumentOut(
        id=row["id"],
        doc_id=row["doc_id"],
        title=row["title"],
        state=_safe_load_state(row["state_json"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


_DOC_COLS = "id, doc_id, title, state_json, created_at, updated_at"


def _fetch_owned_in(
    conn: sqlite3.Connection, doc_pk: int, user_id: int,
) -> sqlite3.Row | None:
    """Fetch a row only if it belongs to user_id, on the given connection.

    Update/delete handlers reuse the same connection across the auth
    check and the write so a concurrent delete can't open a window
    between them where the post-write re-fetch finds nothing.
    """
    return conn.execute(
        f"SELECT {_DOC_COLS} FROM documents WHERE id = ? AND user_id = ?",
        (doc_pk, user_id),
    ).fetchone()


@router.get("", response_model=list[DocumentSummary])
def list_documents(
    user: sqlite3.Row = Depends(current_user),
) -> list[DocumentSummary]:
    """Return the caller's documents, most recently updated first."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, doc_id, title, created_at, updated_at "
            "FROM documents WHERE user_id = ? "
            "ORDER BY updated_at DESC, id DESC",
            (user["id"],),
        ).fetchall()
    return [_row_to_summary(r) for r in rows]


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
def create_document(
    payload: DocumentCreateRequest,
    user: sqlite3.Row = Depends(current_user),
) -> DocumentOut:
    state_json = json.dumps(payload.state, ensure_ascii=False)
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO documents (user_id, doc_id, title, state_json) "
            "VALUES (?, ?, ?, ?)",
            (user["id"], payload.doc_id, payload.title, state_json),
        )
        row = conn.execute(
            "SELECT id, doc_id, title, state_json, created_at, updated_at "
            "FROM documents WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
    return _row_to_full(row)


@router.get("/{doc_pk}", response_model=DocumentOut)
def get_document(
    doc_pk: int,
    user: sqlite3.Row = Depends(current_user),
) -> DocumentOut:
    with get_conn() as conn:
        row = _fetch_owned_in(conn, doc_pk, user["id"])
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _row_to_full(row)


@router.put("/{doc_pk}", response_model=DocumentOut)
def update_document(
    doc_pk: int,
    payload: DocumentUpdateRequest,
    user: sqlite3.Row = Depends(current_user),
) -> DocumentOut:
    # Auth check + write + re-fetch share one connection so a concurrent
    # delete can't slip a TOCTOU between them. The re-fetch keeps the
    # `user_id = ?` guard for defense in depth.
    with get_conn() as conn:
        row = _fetch_owned_in(conn, doc_pk, user["id"])
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

        new_title = row["title"] if payload.title is None else payload.title
        new_state_json = (
            row["state_json"]
            if payload.state is None
            else json.dumps(payload.state, ensure_ascii=False)
        )

        conn.execute(
            "UPDATE documents "
            "   SET title = ?, state_json = ?, updated_at = datetime('now') "
            " WHERE id = ? AND user_id = ?",
            (new_title, new_state_json, doc_pk, user["id"]),
        )
        updated = _fetch_owned_in(conn, doc_pk, user["id"])
    if updated is None:
        # Should not happen — the row was just updated under a held FK lock —
        # but if it did, surface a clean 404 instead of a 500.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _row_to_full(updated)


@router.delete("/{doc_pk}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    doc_pk: int,
    user: sqlite3.Row = Depends(current_user),
) -> None:
    with get_conn() as conn:
        row = _fetch_owned_in(conn, doc_pk, user["id"])
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        conn.execute(
            "DELETE FROM documents WHERE id = ? AND user_id = ?",
            (doc_pk, user["id"]),
        )
