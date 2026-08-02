"""Documents CRUD — drafts the user has saved.

All endpoints require a valid bearer token. A user can only see and
modify their own documents; anything else returns 404 to avoid leaking
existence of other users' rows.
"""

from __future__ import annotations

import copy
import json
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import current_user
from app.db import get_conn
from app.draft_state import (
    DraftPatchRejected,
    FieldPatchRequest,
    FieldPatchResponse,
    ValidationErrorItem,
    apply_field_patch,
    embed_snapshot_in_state,
    migrate_document_state_if_needed,
    snapshot_from_document_state,
    unresolved_required_field_keys,
)
from app.manifests import load_manifest, manifest_field_keys
from app.models import (
    MAX_DOCUMENT_STATE_BYTES,
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


def _validation_error_detail(
    errors: list[ValidationErrorItem],
) -> dict[str, list[dict[str, Any]]]:
    return {"validation_errors": [err.model_dump(mode="json") for err in errors]}


def _raise_validation_errors(
    status_code: int,
    errors: list[ValidationErrorItem],
) -> None:
    raise HTTPException(
        status_code=status_code,
        detail=_validation_error_detail(errors),
    )


def _draft_state_injection_error() -> ValidationErrorItem:
    return ValidationErrorItem(
        kind="draft_state_injection_forbidden",
        message="Public document writes cannot create or replace draft_state.",
    )


def _state_json_or_reject(state: dict[str, Any]) -> str:
    state_json = json.dumps(state, ensure_ascii=False)
    encoded = len(state_json.encode("utf-8"))
    if encoded > MAX_DOCUMENT_STATE_BYTES:
        _raise_validation_errors(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            [
                ValidationErrorItem(
                    kind="state_too_large",
                    message=(
                        f"state too large ({encoded} bytes > "
                        f"{MAX_DOCUMENT_STATE_BYTES})"
                    ),
                ),
            ],
        )
    return state_json


def _persist_state(
    conn: sqlite3.Connection,
    *,
    doc_pk: int,
    user_id: int,
    state: dict[str, Any],
) -> None:
    conn.execute(
        "UPDATE documents "
        "   SET state_json = ?, updated_at = datetime('now') "
        " WHERE id = ? AND user_id = ?",
        (_state_json_or_reject(state), doc_pk, user_id),
    )


def _public_patch_source_errors(
    payload: FieldPatchRequest,
) -> list[ValidationErrorItem]:
    if payload.source in {"llm", "form"}:
        return []
    return [
        ValidationErrorItem(
            kind="forbidden_source",
            message=(
                "Public field-patch requests may only use llm proposals or "
                "authenticated form actions."
            ),
        ),
    ]


def _merge_public_state_update(
    *,
    doc_id: str,
    current_state: dict[str, Any],
    incoming_state: dict[str, Any],
) -> dict[str, Any]:
    manifest = load_manifest(doc_id)
    if "draft_state" not in current_state:
        if "draft_state" in incoming_state:
            raise DraftPatchRejected(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                [_draft_state_injection_error()],
            )
        return copy.deepcopy(incoming_state)

    if manifest is None:
        if "draft_state" in incoming_state:
            raise DraftPatchRejected(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                [_draft_state_injection_error()],
            )
        return copy.deepcopy(incoming_state)

    snapshot = snapshot_from_document_state(
        doc_id=doc_id,
        state=current_state,
        manifest=manifest,
    )
    merged = copy.deepcopy(incoming_state)
    merged.pop("draft_state", None)
    if doc_id == "mutual-nda":
        # MNDA's retired typed state is no longer authoritative after the
        # manifest kernel exists. Old clients may still PUT it during
        # autosave, but public writes must not resurrect that dead envelope.
        merged.pop("mnda", None)

    managed_keys = set(manifest_field_keys(manifest))
    current_fields = current_state.get("fields")
    incoming_fields = merged.get("fields")
    fields_for_embed: dict[str, Any] = {}
    if isinstance(current_fields, dict):
        fields_for_embed.update(current_fields)
    if isinstance(incoming_fields, dict):
        fields_for_embed.update(
            {
                key: value
                for key, value in incoming_fields.items()
                if key not in managed_keys
            },
        )
    merged["fields"] = fields_for_embed
    return embed_snapshot_in_state(merged, snapshot, manifest)


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
    if "draft_state" in payload.state:
        _raise_validation_errors(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            [_draft_state_injection_error()],
        )
    state_json = _state_json_or_reject(payload.state)
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
        conn.execute("BEGIN IMMEDIATE")
        row = _fetch_owned_in(conn, doc_pk, user["id"])
        if row is not None:
            manifest = load_manifest(row["doc_id"])
            if manifest is not None:
                try:
                    state, _snapshot, changed = migrate_document_state_if_needed(
                        doc_id=row["doc_id"],
                        state=_safe_load_state(row["state_json"]),
                        manifest=manifest,
                    )
                except DraftPatchRejected:
                    changed = False
                if changed:
                    _persist_state(
                        conn,
                        doc_pk=doc_pk,
                        user_id=int(user["id"]),
                        state=state,
                    )
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
        conn.execute("BEGIN IMMEDIATE")
        row = _fetch_owned_in(conn, doc_pk, user["id"])
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

        new_title = row["title"] if payload.title is None else payload.title
        if payload.state is None:
            new_state_json = row["state_json"]
        else:
            try:
                new_state = _merge_public_state_update(
                    doc_id=row["doc_id"],
                    current_state=_safe_load_state(row["state_json"]),
                    incoming_state=payload.state,
                )
                new_state_json = _state_json_or_reject(new_state)
            except DraftPatchRejected as exc:
                _raise_validation_errors(exc.status_code, exc.errors)

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


@router.get("/{doc_pk}/download-readiness")
def get_download_readiness(
    doc_pk: int,
    user: sqlite3.Row = Depends(current_user),
) -> dict[str, Any]:
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _fetch_owned_in(conn, doc_pk, user["id"])
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

        manifest = load_manifest(row["doc_id"])
        if manifest is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=_validation_error_detail(
                    [
                        ValidationErrorItem(
                            kind="unsupported_document_schema",
                            message=(
                                "Download readiness is only available for "
                                "manifest-backed documents."
                            ),
                        ),
                    ],
                ),
            )

        try:
            state_blob, snapshot, changed = migrate_document_state_if_needed(
                doc_id=row["doc_id"],
                state=_safe_load_state(row["state_json"]),
                manifest=manifest,
            )
        except DraftPatchRejected as exc:
            _raise_validation_errors(exc.status_code, exc.errors)
        if changed:
            _persist_state(
                conn,
                doc_pk=doc_pk,
                user_id=int(user["id"]),
                state=state_blob,
            )

    unresolved = unresolved_required_field_keys(manifest, snapshot)
    if unresolved:
        detail = _validation_error_detail(
            [
                ValidationErrorItem(
                    kind="download_blocked",
                    message=(
                        "Required fields must be confirmed before download."
                    ),
                ),
            ],
        )
        detail["unresolved_required_fields"] = unresolved
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
    return {"can_download": True, "unresolved_required_fields": []}


@router.post("/{doc_pk}/field-patches", response_model=FieldPatchResponse)
def apply_document_field_patch(
    doc_pk: int,
    payload: FieldPatchRequest,
    user: sqlite3.Row = Depends(current_user),
) -> FieldPatchResponse:
    """Apply one atomic FieldPatch to a manifest-backed draft.

    This is the first server-owned write path for normalized document fields:
    LLM/form inputs submit proposals, and only explicit user confirmation can
    turn them into confirmed values used by legacy preview/export state.
    """
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _fetch_owned_in(conn, doc_pk, user["id"])
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

        manifest = load_manifest(row["doc_id"])
        if manifest is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=_validation_error_detail(
                    [
                        ValidationErrorItem(
                            kind="unsupported_document_schema",
                            message=(
                                "Field patches require a manifest-backed "
                                "document schema."
                            ),
                        ),
                    ],
                ),
            )

        state_blob = _safe_load_state(row["state_json"])
        source_errors = _public_patch_source_errors(payload)
        if source_errors:
            _raise_validation_errors(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                source_errors,
            )
        try:
            state_blob, snapshot, migrated = migrate_document_state_if_needed(
                doc_id=row["doc_id"],
                state=state_blob,
                manifest=manifest,
            )
        except DraftPatchRejected as exc:
            _raise_validation_errors(exc.status_code, exc.errors)

        try:
            result = apply_field_patch(
                snapshot=snapshot,
                patch=payload,
                manifest=manifest,
                actor_user_id=int(user["id"]),
                actor_source="llm" if payload.source == "llm" else "form",
            )
        except DraftPatchRejected as exc:
            _raise_validation_errors(exc.status_code, exc.errors)

        if result.duplicate:
            if migrated:
                _persist_state(
                    conn,
                    doc_pk=doc_pk,
                    user_id=int(user["id"]),
                    state=state_blob,
                )
            return result

        snapshot_changed = (
            result.snapshot.model_dump(mode="json")
            != snapshot.model_dump(mode="json")
        )
        if not snapshot_changed:
            if migrated:
                _persist_state(
                    conn,
                    doc_pk=doc_pk,
                    user_id=int(user["id"]),
                    state=state_blob,
                )
            return result

        next_state = embed_snapshot_in_state(state_blob, result.snapshot, manifest)
        _persist_state(
            conn,
            doc_pk=doc_pk,
            user_id=int(user["id"]),
            state=next_state,
        )
        return result


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
