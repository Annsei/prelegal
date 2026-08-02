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
from typing import Any, Literal, cast

from pydantic import BaseModel, Field, field_validator

from app.manifests import manifest_field_keys

FIELD_STATE_SCHEMA_VERSION = "draft-state.v1"

FieldStatus = Literal["confirmed", "pending_confirmation", "conflict", "missing"]
PatchSource = Literal["llm", "user", "form", "system"]
PatchOp = Literal["propose", "confirm", "reject"]
MessageIndexTrust = Literal["none", "client_asserted", "server_verified"]


class ValidationErrorItem(BaseModel):
    kind: str
    field_key: str | None = None
    message: str


class FieldProvenance(BaseModel):
    patch_id: str
    source: PatchSource
    actor_user_id: int | None = None
    operation: str = "unknown"
    value: str | None = None
    client_source: str | None = None
    message_index: int | None = None
    message_index_trust: MessageIndexTrust = "none"
    at: str | None = None


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
    manifest_version: int | str | None = None
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
    source: str = Field(min_length=1, max_length=40)
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
    raw_present = "draft_state" in state
    raw = state.get("draft_state")
    manifest_version = _manifest_version(manifest)
    if raw_present:
        if not isinstance(raw, dict):
            raise _draft_state_rejected(
                "invalid_draft_state",
                "Stored draft_state must be a JSON object.",
            )
        raw_schema = raw.get("schema_version")
        if raw_schema != FIELD_STATE_SCHEMA_VERSION:
            kind = (
                "unsupported_draft_state_schema"
                if isinstance(raw_schema, str)
                else "invalid_draft_state"
            )
            raise _draft_state_rejected(
                kind,
                "Stored draft_state uses an unsupported schema version.",
            )
        try:
            snapshot = DraftStateSnapshot.model_validate(raw)
        except ValueError as exc:
            raise _draft_state_rejected(
                "invalid_draft_state",
                "Stored draft_state is not a valid DraftStateSnapshot.",
            ) from exc
        if snapshot.doc_id != doc_id:
            raise _draft_state_rejected(
                "draft_state_doc_mismatch",
                "Stored draft_state belongs to a different document type.",
            )
        if snapshot.manifest_version != manifest_version:
            raise _draft_state_rejected(
                "manifest_version_mismatch",
                "Stored draft_state was created for a different manifest version.",
            )
        return _ensure_manifest_fields(snapshot, manifest)

    if _legacy_manifest_values(
        doc_id=doc_id,
        state=state,
        manifest=manifest,
    ):
        raise DraftPatchRejected(
            409,
            [
                ValidationErrorItem(
                    kind="migration_required",
                    message=(
                        "This draft has legacy manifest fields without a "
                        "DraftStateSnapshot. An explicit migration must "
                        "classify those values before field patches can "
                        "modify them."
                    ),
                ),
            ],
        )

    snapshot = DraftStateSnapshot(
        doc_id=doc_id,
        manifest_version=manifest_version,
    )
    legacy_fields = state.get("fields")
    if not isinstance(legacy_fields, dict):
        legacy_fields = {}
    for key in manifest_field_keys(manifest):
        snapshot.fields[key] = FieldState(key=key)
    return snapshot


def migrate_document_state_if_needed(
    *,
    doc_id: str,
    state: dict[str, Any],
    manifest: dict[str, Any],
) -> tuple[dict[str, Any], DraftStateSnapshot, bool]:
    """Return a state/snapshot pair, migrating legacy CSA field state.

    Legacy `state.fields` values have unknown provenance. The migration keeps
    the original flat fields in place for data recovery, but classifies managed
    manifest values as `pending_confirmation` with explicit `legacy_unverified`
    provenance. It never fabricates confirmation metadata.
    """
    next_state = copy.deepcopy(state)
    raw = next_state.get("draft_state")
    manifest_version = _manifest_version(manifest)

    if (
        isinstance(raw, dict)
        and raw.get("schema_version") == FIELD_STATE_SCHEMA_VERSION
    ):
        try:
            snapshot = DraftStateSnapshot.model_validate(raw)
        except ValueError as exc:
            raise _draft_state_rejected(
                "invalid_draft_state",
                "Stored draft_state is not a valid DraftStateSnapshot.",
            ) from exc
        if snapshot.doc_id != doc_id:
            raise _draft_state_rejected(
                "draft_state_doc_mismatch",
                "Stored draft_state belongs to a different document type.",
            )
        if snapshot.manifest_version is None:
            migrated = _ensure_manifest_fields(snapshot, manifest)
            migrated.manifest_version = manifest_version
            next_state["draft_state"] = migrated.model_dump(mode="json")
            if doc_id == "mutual-nda":
                next_state.pop("mnda", None)
            return next_state, migrated, True
        snapshot = snapshot_from_document_state(
            doc_id=doc_id,
            state=next_state,
            manifest=manifest,
        )
        if doc_id == "mutual-nda" and "mnda" in next_state:
            next_state.pop("mnda", None)
            return next_state, snapshot, True
        return next_state, snapshot, False

    if "draft_state" in next_state:
        snapshot = snapshot_from_document_state(
            doc_id=doc_id,
            state=next_state,
            manifest=manifest,
        )
        return next_state, snapshot, False

    managed_values = _legacy_manifest_values(
        doc_id=doc_id,
        state=next_state,
        manifest=manifest,
    )

    if managed_values:
        snapshot = DraftStateSnapshot(
            doc_id=doc_id,
            manifest_version=manifest_version,
        )
        for key in manifest_field_keys(manifest):
            value = managed_values.get(key)
            if value is None:
                snapshot.fields[key] = FieldState(key=key)
                continue
            snapshot.fields[key] = FieldState(
                key=key,
                status="pending_confirmation",
                value=value,
                provenance=[
                    FieldProvenance(
                        patch_id="legacy-migration",
                        source="system",
                        operation="legacy_unverified",
                        value=value,
                    ),
                ],
            )
        legacy_fields = next_state.get("fields")
        next_fields = dict(legacy_fields) if isinstance(legacy_fields, dict) else {}
        next_fields.update(managed_values)
        next_state["fields"] = next_fields
        next_state["draft_state"] = snapshot.model_dump(mode="json")
        if doc_id == "mutual-nda":
            next_state.pop("mnda", None)
        return next_state, snapshot, True

    snapshot = snapshot_from_document_state(
        doc_id=doc_id,
        state=next_state,
        manifest=manifest,
    )
    return next_state, snapshot, False


def legacy_mnda_to_manifest_fields(value: Any) -> dict[str, str]:
    """Normalize the retired typed MNDA state into manifest field strings.

    Legacy MNDA drafts stored a bespoke `state.mnda` object. Those values
    have unknown provenance, so migration classifies them as
    `pending_confirmation` elsewhere; this pure helper only maps the shape to
    the new canonical manifest keys without adding any actor or time metadata.
    """
    if not isinstance(value, dict):
        return {}

    mapped: dict[str, str] = {}
    _put_string(mapped, "保密用途", value.get("purpose"))
    _put_string(mapped, "生效日期", value.get("effectiveDate"))
    _put_string(mapped, "适用法律", value.get("governingLaw"))
    _put_string(mapped, "争议解决", value.get("jurisdiction"))
    _put_string(mapped, "对标准条款的修订", value.get("modifications"))

    mnda_term = _legacy_mnda_term(value)
    if mnda_term:
        mapped["协议期限"] = mnda_term
    confidentiality_term = _legacy_confidentiality_term(value)
    if confidentiality_term:
        mapped["保密期限"] = confidentiality_term

    party_map = {
        "party1": "甲方",
        "party2": "乙方",
    }
    field_map = {
        "company": "公司名称",
        "signerName": "签字人姓名",
        "signerTitle": "签字人职务",
        "noticeAddress": "通知地址",
    }
    for party_key, party_label in party_map.items():
        party = value.get(party_key)
        if not isinstance(party, dict):
            continue
        for field_key, field_label in field_map.items():
            _put_string(mapped, f"{party_label}{field_label}", party.get(field_key))

    return mapped


def _legacy_manifest_values(
    *,
    doc_id: str,
    state: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, str]:
    managed_keys = set(manifest_field_keys(manifest))
    values: dict[str, str] = {}
    legacy_fields = state.get("fields")
    if isinstance(legacy_fields, dict):
        for key in managed_keys:
            value = legacy_fields.get(key)
            if isinstance(value, str) and value.strip():
                values[key] = value.strip()
    if doc_id == "mutual-nda":
        for key, value in legacy_mnda_to_manifest_fields(state.get("mnda")).items():
            if key in managed_keys and key not in values:
                values[key] = value
    return values


def _put_string(target: dict[str, str], key: str, value: Any) -> None:
    if isinstance(value, str) and value.strip():
        target[key] = value.strip()


def _legacy_mnda_term(value: dict[str, Any]) -> str:
    mode = value.get("mndaTermMode")
    if mode == "continues":
        return "持续有效，直至依约终止"
    if mode == "expires":
        years = _legacy_non_negative_int(value.get("mndaTermYears"))
        if years is not None:
            return f"自生效日期起 {years} 年"
    return ""


def _legacy_confidentiality_term(value: dict[str, Any]) -> str:
    mode = value.get("confidentialityMode")
    if mode == "perpetual":
        return "永久"
    if mode == "years":
        years = _legacy_non_negative_int(value.get("confidentialityYears"))
        if years is not None:
            return f"自生效日期起 {years} 年"
    return ""


def _legacy_non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def apply_field_patch(
    *,
    snapshot: DraftStateSnapshot,
    patch: FieldPatchRequest,
    manifest: dict[str, Any],
    actor_user_id: int,
    actor_source: PatchSource | None = None,
    message_index_verified: bool = False,
    now: str | None = None,
) -> FieldPatchResponse:
    """Validate and apply one atomic field patch to a draft snapshot."""
    resolved_source = actor_source or _coerce_patch_source(patch.source)
    if resolved_source is None:
        raise DraftPatchRejected(
            422,
            [
                ValidationErrorItem(
                    kind="invalid_source",
                    message="Patch source is not recognized.",
                ),
            ],
        )
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

    errors = _validate_patch(patch, manifest, snapshot, resolved_source)
    if errors:
        raise DraftPatchRejected(422, errors)

    active_operations = [
        operation
        for operation in patch.operations
        if not _is_noop_proposal(
            operation,
            snapshot.fields.get(operation.key, FieldState(key=operation.key)),
        )
    ]
    if not active_operations:
        return FieldPatchResponse(snapshot=snapshot)

    next_snapshot = copy.deepcopy(snapshot)
    next_revision = snapshot.revision + 1
    at = now or _now_iso()
    provenance_user_id = (
        actor_user_id if resolved_source in {"user", "form"} else None
    )
    message_index_trust: MessageIndexTrust
    if patch.message_index is None:
        message_index_trust = "none"
    elif message_index_verified:
        message_index_trust = "server_verified"
    else:
        message_index_trust = "client_asserted"

    for operation in active_operations:
        field = next_snapshot.fields.setdefault(
            operation.key,
            FieldState(key=operation.key),
        )
        provenance = FieldProvenance(
            patch_id=patch.patch_id,
            source=resolved_source,
            actor_user_id=provenance_user_id,
            operation=operation.op,
            value=_provenance_value(operation, field),
            client_source=patch.source,
            message_index=patch.message_index,
            message_index_trust=message_index_trust,
            at=at,
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
    manifest: dict[str, Any] | None = None,
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
    manifest_keys = (
        set(manifest_field_keys(manifest))
        if manifest is not None
        else set(snapshot.fields)
    )
    extras = {
        key: value
        for key, value in (existing if isinstance(existing, dict) else {}).items()
        if key not in manifest_keys
    }
    legacy_unverified_values = {
        key: value
        for key, value in (existing if isinstance(existing, dict) else {}).items()
        if key in manifest_keys
        and _is_legacy_unverified_pending(snapshot.fields.get(key), value)
    }
    next_state["fields"] = {
        **extras,
        **legacy_unverified_values,
        **stable_values,
    }
    return next_state


def _ensure_manifest_fields(
    snapshot: DraftStateSnapshot,
    manifest: dict[str, Any],
) -> DraftStateSnapshot:
    changed = copy.deepcopy(snapshot)
    changed.manifest_version = _manifest_version(manifest)
    known = set(manifest_field_keys(manifest))
    for key in known:
        changed.fields.setdefault(key, FieldState(key=key))
    return changed


def _validate_patch(
    patch: FieldPatchRequest,
    manifest: dict[str, Any],
    snapshot: DraftStateSnapshot,
    actor_source: PatchSource,
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

        if actor_source == "llm" and operation.op == "confirm":
            errors.append(
                ValidationErrorItem(
                    kind="llm_confirm_forbidden",
                    field_key=operation.key,
                    message="LLM patches may propose values but cannot confirm them.",
                ),
            )
        if actor_source == "llm" and operation.op == "reject":
            errors.append(
                ValidationErrorItem(
                    kind="llm_reject_forbidden",
                    field_key=operation.key,
                    message="LLM patches cannot reject field candidates.",
                ),
            )

        normalized_value = _normalize_value(operation.value)
        if (
            actor_source == "llm"
            and operation.op == "propose"
            and normalized_value == ""
        ):
            errors.append(
                ValidationErrorItem(
                    kind="llm_clear_forbidden",
                    field_key=operation.key,
                    message="LLM patches cannot clear fields.",
                ),
            )

        if (
            operation.op in {"propose", "confirm"}
            and operation.value is not None
            and normalized_value
        ):
            errors.extend(_validate_value(operation.key, operation.value, field_def))
        elif operation.op == "propose" and operation.value is None:
            errors.append(
                ValidationErrorItem(
                    kind="invalid_patch",
                    field_key=operation.key,
                    message="Propose operations must include a value.",
                ),
            )
        if not any(err.field_key == operation.key for err in errors):
            transition_error = _validate_transition(
                operation,
                snapshot.fields.get(operation.key, FieldState(key=operation.key)),
                actor_source,
            )
            if transition_error is not None:
                errors.append(transition_error)

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
    if field.status == "confirmed" and field.value:
        if field.value == value:
            field.provenance.append(provenance)
            return
        field.status = "conflict"
        field.conflict = FieldConflict(
            proposed_value=value,
            base_value=field.value,
            provenance=provenance,
        )
        field.provenance.append(provenance)
        return

    if field.status == "conflict":
        base_value = field.conflict.base_value if field.conflict else field.value
        field.conflict = FieldConflict(
            proposed_value=value,
            base_value=base_value,
            provenance=provenance,
        )
        field.provenance.append(provenance)
        return

    if field.status == "pending_confirmation" and field.value:
        if field.value == value:
            field.provenance.append(provenance)
            return
        field.value = value
        field.confirmed_at = None
        field.confirmed_by_user_id = None
        field.conflict = None
        field.provenance.append(provenance)
        return

    if field.value:
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
    field.confirmed_at = None
    field.confirmed_by_user_id = None
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
    if field.status == "conflict" and field.conflict is not None:
        if field.conflict.base_value is not None:
            field.value = field.conflict.base_value
        if field.confirmed_at:
            field.status = "confirmed"
        else:
            field.status = "pending_confirmation" if field.value else "missing"
    elif field.status == "pending_confirmation":
        field.status = "missing"
        field.value = None
        field.confirmed_at = None
        field.confirmed_by_user_id = None
    elif field.confirmed_at:
        field.status = "confirmed"
    else:
        field.status = "missing"
    field.conflict = None
    field.provenance.append(provenance)


def _is_noop_proposal(
    operation: FieldPatchOperation,
    field: FieldState,
) -> bool:
    if operation.op != "propose":
        return False
    value = _normalize_value(operation.value)
    if field.status == "pending_confirmation":
        return field.value == value
    if field.status == "conflict" and field.conflict is not None:
        return field.conflict.proposed_value == value
    return False


def _is_legacy_unverified_pending(
    field: FieldState | None,
    current_value: Any,
) -> bool:
    if field is None or field.status != "pending_confirmation":
        return False
    if not isinstance(current_value, str) or current_value.strip() != field.value:
        return False
    return any(
        provenance.operation == "legacy_unverified"
        for provenance in field.provenance
    )


def _manifest_fields_by_key(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        field["key"]: field
        for field in manifest.get("fields", [])
        if isinstance(field, dict) and isinstance(field.get("key"), str)
    }


def _normalize_value(value: Any | None) -> str:
    return value.strip() if isinstance(value, str) else ""


def _provenance_value(
    operation: FieldPatchOperation,
    field: FieldState,
) -> str | None:
    if operation.op in {"propose", "confirm"} and operation.value is not None:
        return _normalize_value(operation.value)
    if operation.op == "confirm":
        if field.conflict is not None:
            return field.conflict.proposed_value
        return field.value
    if operation.op == "reject":
        if field.conflict is not None:
            return field.conflict.proposed_value
        return field.value
    return None


def _coerce_patch_source(source: str) -> PatchSource | None:
    if source in {"llm", "user", "form", "system"}:
        return cast(PatchSource, source)
    return None


def _manifest_version(manifest: dict[str, Any]) -> int | str | None:
    version = manifest.get("version")
    return version if isinstance(version, (int, str)) else None


def _draft_state_rejected(kind: str, message: str) -> DraftPatchRejected:
    return DraftPatchRejected(
        409,
        [
            ValidationErrorItem(
                kind=kind,
                message=message,
            ),
        ],
    )


def _validate_transition(
    operation: FieldPatchOperation,
    field: FieldState,
    actor_source: PatchSource,
) -> ValidationErrorItem | None:
    value = _normalize_value(operation.value)
    if operation.op == "propose":
        if value == "":
            return ValidationErrorItem(
                kind="invalid_transition",
                field_key=operation.key,
                message="Propose operations require a non-empty candidate value.",
            )
        return None

    if operation.op in {"confirm", "reject"} and actor_source not in {
        "form",
        "user",
    }:
        return ValidationErrorItem(
            kind="invalid_transition",
            field_key=operation.key,
            message="Only an authenticated user action can confirm or reject.",
        )

    if operation.op == "confirm":
        if operation.value is not None:
            if value == "" and field.status == "missing":
                return ValidationErrorItem(
                    kind="invalid_transition",
                    field_key=operation.key,
                    message="Cannot clear a missing field.",
                )
            return None
        if field.status == "pending_confirmation" and field.value:
            return None
        if field.status == "conflict" and field.conflict is not None:
            return None
        return ValidationErrorItem(
            kind="invalid_transition",
            field_key=operation.key,
            message="No active candidate exists to confirm.",
        )

    if operation.op == "reject":
        if field.status == "pending_confirmation" and field.value:
            return None
        if field.status == "conflict" and field.conflict is not None:
            return None
        return ValidationErrorItem(
            kind="invalid_transition",
            field_key=operation.key,
            message="No active candidate exists to reject.",
        )

    return None


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
    if field is None or field.value is None:
        return None
    if field.status == "confirmed":
        return field.value
    if field.status == "conflict" and field.confirmed_at is not None:
        return field.value
    return None


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
