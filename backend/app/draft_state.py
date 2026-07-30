"""Draft field-state kernel.

This module is intentionally independent of chat, preview, and export code.
LLM and form inputs submit `FieldPatch` objects; the server validates them and
produces a versioned `DraftStateSnapshot` that later renderers can consume.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.manifests import manifest_field_keys

FIELD_STATE_SCHEMA_VERSION = "draft-state.v1"

FieldStatus = Literal["confirmed", "pending_confirmation", "conflict", "missing"]
PatchSource = Literal["llm", "user", "form", "system"]
PatchOp = Literal["propose", "confirm", "reject"]


class ValidationErrorItem(BaseModel):
    kind: str
    field_key: str | None = None
    message: str


class FieldProvenance(BaseModel):
    patch_id: str
    source: PatchSource
    actor_user_id: int
    message_index: int | None = None
    at: str


class FieldConflict(BaseModel):
    proposed_value: str
    base_value: str | None = None
    provenance: FieldProvenance


class FieldState(BaseModel):
    key: str
    status: FieldStatus = "missing"
    value: str | None = None
    revision: int = 0
    provenance: list[FieldProvenance] = Field(default_factory=list)
    confirmed_at: str | None = None
    confirmed_by_user_id: int | None = None
    conflict: FieldConflict | None = None
    validation_errors: list[ValidationErrorItem] = Field(default_factory=list)


class AppliedPatchRecord(BaseModel):
    revision: int
    fingerprint: str


class DraftStateSnapshot(BaseModel):
    schema_version: Literal["draft-state.v1"] = FIELD_STATE_SCHEMA_VERSION
    doc_id: str
    revision: int = 0
    fields: dict[str, FieldState] = Field(default_factory=dict)
    validation_errors: list[ValidationErrorItem] = Field(default_factory=list)
    applied_patches: dict[str, AppliedPatchRecord] = Field(default_factory=dict)

    @field_validator("applied_patches", mode="before")
    @classmethod
    def _upgrade_applied_patch_records(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        upgraded: dict[str, Any] = {}
        for key, record in value.items():
            if isinstance(record, int):
                upgraded[key] = {"revision": record, "fingerprint": ""}
            else:
                upgraded[key] = record
        return upgraded


class FieldPatchOperation(BaseModel):
    op: PatchOp = "propose"
    key: str = Field(min_length=1, max_length=200)
    value: Any | None = None


class FieldPatchRequest(BaseModel):
    patch_id: str = Field(min_length=1, max_length=120)
    base_revision: int = Field(ge=0)
    source: PatchSource
    message_index: int | None = Field(default=None, ge=0)
    operations: list[FieldPatchOperation] = Field(min_length=1, max_length=100)


class FieldPatchResponse(BaseModel):
    snapshot: DraftStateSnapshot
    duplicate: bool = False


class DraftPatchRejected(ValueError):
    def __init__(self, status_code: int, errors: list[ValidationErrorItem]):
        self.status_code = status_code
        self.errors = errors
        super().__init__("draft field patch rejected")


def snapshot_from_document_state(
    *,
    doc_id: str,
    state: dict[str, Any],
    manifest: dict[str, Any],
) -> DraftStateSnapshot:
    """Read or bootstrap a DraftStateSnapshot from a document state blob."""
    raw = state.get("draft_state")
    if isinstance(raw, dict):
        try:
            snapshot = DraftStateSnapshot.model_validate(raw)
            if snapshot.doc_id == doc_id:
                return _ensure_manifest_fields(snapshot, manifest)
        except ValueError:
            pass

    snapshot = DraftStateSnapshot(doc_id=doc_id)
    legacy_fields = state.get("fields")
    if not isinstance(legacy_fields, dict):
        legacy_fields = {}
    now = _now_iso()
    for key in manifest_field_keys(manifest):
        value = legacy_fields.get(key)
        text = value.strip() if isinstance(value, str) else ""
        if text:
            provenance = FieldProvenance(
                patch_id="legacy-import",
                source="system",
                actor_user_id=0,
                at=now,
            )
            snapshot.fields[key] = FieldState(
                key=key,
                status="confirmed",
                value=text,
                provenance=[provenance],
                confirmed_at=now,
                confirmed_by_user_id=0,
            )
        else:
            snapshot.fields[key] = FieldState(key=key)
    return snapshot


def apply_field_patch(
    *,
    snapshot: DraftStateSnapshot,
    patch: FieldPatchRequest,
    manifest: dict[str, Any],
    actor_user_id: int,
    now: str | None = None,
) -> FieldPatchResponse:
    """Validate and apply one atomic field patch to a draft snapshot."""
    fingerprint = _patch_fingerprint(patch)
    existing_patch = snapshot.applied_patches.get(patch.patch_id)
    if existing_patch is not None and existing_patch.fingerprint == fingerprint:
        return FieldPatchResponse(snapshot=snapshot, duplicate=True)
    if existing_patch is not None:
        raise DraftPatchRejected(
            409,
            [
                ValidationErrorItem(
                    kind="patch_id_conflict",
                    message=(
                        "patch_id has already been applied with different "
                        "operations."
                    ),
                ),
            ],
        )

    if patch.base_revision != snapshot.revision:
        raise DraftPatchRejected(
            409,
            [
                ValidationErrorItem(
                    kind="revision_conflict",
                    message=(
                        f"Patch base_revision {patch.base_revision} does not "
                        f"match current revision {snapshot.revision}."
                    ),
                ),
            ],
        )

    errors = _validate_patch(patch, manifest)
    if errors:
        raise DraftPatchRejected(422, errors)

    next_snapshot = copy.deepcopy(snapshot)
    next_revision = snapshot.revision + 1
    provenance = FieldProvenance(
        patch_id=patch.patch_id,
        source=patch.source,
        actor_user_id=actor_user_id,
        message_index=patch.message_index,
        at=now or _now_iso(),
    )

    for operation in patch.operations:
        field = next_snapshot.fields.setdefault(
            operation.key,
            FieldState(key=operation.key),
        )
        if operation.op == "propose":
            _apply_proposal(field, _normalize_value(operation.value), provenance)
        elif operation.op == "confirm":
            _apply_confirmation(field, operation.value, provenance)
        elif operation.op == "reject":
            _apply_rejection(field, provenance)
        field.revision = next_revision

    next_snapshot.revision = next_revision
    next_snapshot.applied_patches[patch.patch_id] = AppliedPatchRecord(
        revision=next_revision,
        fingerprint=fingerprint,
    )
    next_snapshot.validation_errors = []
    return FieldPatchResponse(snapshot=next_snapshot)


def required_field_keys(
    manifest: dict[str, Any],
    snapshot: DraftStateSnapshot,
) -> list[str]:
    """Required fields after evaluating the manifest's declarative rules.

    Supported conditional shape:
    `{ "field": "Some Key", "op": "equals|not_equals|in|exists", ... }`.
    Values are read only from confirmed field states.
    """
    keys: list[str] = []
    for field_def in manifest.get("fields", []):
        if not isinstance(field_def, dict) or not isinstance(
            field_def.get("key"), str,
        ):
            continue
        if field_def.get("required") is True or _required_when_matches(
            field_def.get("required_when"),
            snapshot,
        ):
            keys.append(field_def["key"])
    return keys


def unresolved_required_field_keys(
    manifest: dict[str, Any],
    snapshot: DraftStateSnapshot,
) -> list[str]:
    return [
        key
        for key in required_field_keys(manifest, snapshot)
        if snapshot.fields.get(key) is None
        or snapshot.fields[key].status != "confirmed"
        or not snapshot.fields[key].value
    ]


def embed_snapshot_in_state(
    state: dict[str, Any],
    snapshot: DraftStateSnapshot,
) -> dict[str, Any]:
    """Return a document state blob with the normalized draft snapshot added.

    The legacy `fields` map is kept in sync with confirmed values only, so
    pending LLM suggestions and conflicts cannot silently change preview/export
    data before a user confirms them.
    """
    next_state = copy.deepcopy(state)
    next_state["draft_state"] = snapshot.model_dump(mode="json")
    stable_values = {
        key: field.value
        for key, field in snapshot.fields.items()
        if (
            field.status == "confirmed"
            or (field.status == "conflict" and field.confirmed_at is not None)
        )
        and isinstance(field.value, str)
    }
    existing = next_state.get("fields")
    manifest_keys = set(snapshot.fields)
    extras = {
        key: value
        for key, value in (existing if isinstance(existing, dict) else {}).items()
        if key not in manifest_keys
    }
    next_state["fields"] = {
        **extras,
        **stable_values,
    }
    return next_state


def _ensure_manifest_fields(
    snapshot: DraftStateSnapshot,
    manifest: dict[str, Any],
) -> DraftStateSnapshot:
    changed = copy.deepcopy(snapshot)
    known = set(manifest_field_keys(manifest))
    for key in known:
        changed.fields.setdefault(key, FieldState(key=key))
    changed.fields = {
        key: field for key, field in changed.fields.items() if key in known
    }
    return changed


def _validate_patch(
    patch: FieldPatchRequest,
    manifest: dict[str, Any],
) -> list[ValidationErrorItem]:
    errors: list[ValidationErrorItem] = []
    fields = _manifest_fields_by_key(manifest)
    seen_keys: set[str] = set()

    for operation in patch.operations:
        if operation.key in seen_keys:
            errors.append(
                ValidationErrorItem(
                    kind="duplicate_field",
                    field_key=operation.key,
                    message="A patch may update each field at most once.",
                ),
            )
        seen_keys.add(operation.key)

        field_def = fields.get(operation.key)
        if field_def is None:
            errors.append(
                ValidationErrorItem(
                    kind="unknown_field",
                    field_key=operation.key,
                    message="Field is not declared in the document manifest.",
                ),
            )
            continue

        if patch.source == "llm" and operation.op == "confirm":
            errors.append(
                ValidationErrorItem(
                    kind="llm_confirm_forbidden",
                    field_key=operation.key,
                    message="LLM patches may propose values but cannot confirm them.",
                ),
            )

        if operation.op in {"propose", "confirm"} and operation.value is not None:
            errors.extend(_validate_value(operation.key, operation.value, field_def))
        elif operation.op == "propose" and operation.value is None:
            errors.append(
                ValidationErrorItem(
                    kind="invalid_patch",
                    field_key=operation.key,
                    message="Propose operations must include a value.",
                ),
            )

    return errors


def _validate_value(
    key: str,
    value: Any,
    field_def: dict[str, Any],
) -> list[ValidationErrorItem]:
    if not isinstance(value, str):
        return [
            ValidationErrorItem(
                kind="invalid_type",
                field_key=key,
                message="Field value must be a string.",
            ),
        ]

    field_type = field_def.get("type")
    if field_type == "date" and value.strip():
        try:
            date.fromisoformat(value.strip())
        except ValueError:
            return [
                ValidationErrorItem(
                    kind="invalid_date",
                    field_key=key,
                    message="Date fields must use ISO YYYY-MM-DD format.",
                ),
            ]

    choices = field_def.get("enum") or field_def.get("options")
    if isinstance(choices, list) and choices and value not in choices:
        return [
            ValidationErrorItem(
                kind="invalid_enum",
                field_key=key,
                message="Field value is not one of the allowed options.",
            ),
        ]

    return []


def _apply_proposal(
    field: FieldState,
    value: str,
    provenance: FieldProvenance,
) -> None:
    if value == "":
        field.status = "missing"
        field.value = None
        field.conflict = None
        field.provenance.append(provenance)
        return

    if field.status in {"confirmed", "pending_confirmation"} and field.value:
        if field.value != value:
            field.status = "conflict"
            field.conflict = FieldConflict(
                proposed_value=value,
                base_value=field.value,
                provenance=provenance,
            )
            field.provenance.append(provenance)
            return

    field.status = "pending_confirmation"
    field.value = value
    field.conflict = None
    field.provenance.append(provenance)


def _apply_confirmation(
    field: FieldState,
    raw_value: Any | None,
    provenance: FieldProvenance,
) -> None:
    if raw_value is not None:
        value = _normalize_value(raw_value)
    elif field.conflict is not None:
        value = field.conflict.proposed_value
    else:
        value = field.value or ""

    if value == "":
        field.status = "missing"
        field.value = None
        field.confirmed_at = None
        field.confirmed_by_user_id = None
        field.conflict = None
        field.provenance.append(provenance)
        return

    field.status = "confirmed"
    field.value = value
    field.confirmed_at = provenance.at
    field.confirmed_by_user_id = provenance.actor_user_id
    field.conflict = None
    field.provenance.append(provenance)


def _apply_rejection(
    field: FieldState,
    provenance: FieldProvenance,
) -> None:
    if field.confirmed_at:
        field.status = "confirmed"
    elif field.value:
        field.status = "pending_confirmation"
    else:
        field.status = "missing"
    field.conflict = None
    field.provenance.append(provenance)


def _manifest_fields_by_key(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        field["key"]: field
        for field in manifest.get("fields", [])
        if isinstance(field, dict) and isinstance(field.get("key"), str)
    }


def _normalize_value(value: Any | None) -> str:
    return value.strip() if isinstance(value, str) else ""


def _patch_fingerprint(patch: FieldPatchRequest) -> str:
    encoded = json.dumps(
        patch.model_dump(mode="json"),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _required_when_matches(
    raw_condition: Any,
    snapshot: DraftStateSnapshot,
) -> bool:
    if raw_condition is None:
        return False
    conditions = raw_condition if isinstance(raw_condition, list) else [raw_condition]
    return all(
        _single_condition_matches(condition, snapshot)
        for condition in conditions
    )


def _single_condition_matches(
    condition: Any,
    snapshot: DraftStateSnapshot,
) -> bool:
    if not isinstance(condition, dict):
        return False
    key = condition.get("field")
    if not isinstance(key, str):
        return False
    value = _confirmed_value(snapshot, key)
    op = condition.get("op") or "equals"
    if op == "equals":
        return value == condition.get("value")
    if op == "not_equals":
        return value is not None and value != condition.get("value")
    if op == "in":
        choices = condition.get("values")
        return isinstance(choices, list) and value in choices
    if op == "exists":
        return bool(value)
    return False


def _confirmed_value(snapshot: DraftStateSnapshot, key: str) -> str | None:
    field = snapshot.fields.get(key)
    if field is None or field.status != "confirmed" or not field.value:
        return None
    return field.value


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
