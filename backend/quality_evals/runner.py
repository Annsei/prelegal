"""Deterministic kernel, download-gate, and export-semantic evaluation."""

from __future__ import annotations

import copy
import importlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import date
from io import BytesIO
from typing import Any

from docx import Document
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.draft_state import (
    DraftPatchRejected,
    DraftStateSnapshot,
    FieldPatchOperation,
    FieldPatchRequest,
    apply_field_patch,
    required_field_keys,
    snapshot_from_document_state,
    unresolved_required_field_keys,
)
from app.export import ExportDocument, build_export_document
from app.manifests import load_manifest
from quality_evals.corpus import (
    CorpusDocument,
    CorpusValidationError,
    load_corpus,
    validate_corpus,
)
from quality_evals.report import QualityCaseResult, QualityReport

_FIXED_AT = "2026-01-15T00:00:00+00:00"
_INVALID_TYPE_METRIC = "invalid_type_acceptance_count"
_UNKNOWN_FIELD_METRIC = "unknown_field_acceptance_count"
_FALSE_NEGATIVE_METRIC = "required_field_false_negative_count"
_FALSE_POSITIVE_METRIC = "required_field_false_positive_count"
_CONFLICT_METRIC = "conflict_transition_failure_count"
_INVALID_DOWNLOAD_METRIC = "successful_invalid_downloads"
_SEMANTIC_METRIC = "cross_format_semantic_mismatch_count"


def run_contract_quality_evaluation() -> QualityReport:
    validated = validate_corpus(load_corpus())
    report = QualityReport.empty(expected_doc_ids=validated.corpus_doc_ids)

    for document in validated.documents:
        manifest = _manifest(document.doc_id)
        _evaluate_kernel(report, document, manifest)

    with _evaluation_client() as (client, get_conn):
        headers = _register(client)
        for document in validated.documents:
            try:
                _evaluate_routes(
                    report,
                    client,
                    get_conn,
                    headers,
                    document,
                    _manifest(document.doc_id),
                )
            except Exception as exc:  # one bad setup must fail, not abort, the gate
                _record(
                    report,
                    document.doc_id,
                    "route-evaluation:setup",
                    False,
                    expected="route evaluation completed",
                    actual=f"{type(exc).__name__}: {exc}",
                )

    return report


def _evaluate_kernel(
    report: QualityReport,
    document: CorpusDocument,
    manifest: dict[str, Any],
) -> None:
    doc_id = document.doc_id
    anchor = document.anchor_field

    complete = _confirm_fields(_fresh_snapshot(doc_id, manifest), manifest["fields"])
    unresolved = unresolved_required_field_keys(manifest, complete)
    _record(
        report,
        doc_id,
        "complete-state",
        not unresolved,
        expected="[]",
        actual=repr(unresolved),
        metric=_FALSE_POSITIVE_METRIC,
    )

    missing = _confirm_fields(
        _fresh_snapshot(doc_id, manifest),
        [field for field in manifest["fields"] if field["key"] != anchor],
    )
    missing_keys = unresolved_required_field_keys(manifest, missing)
    _record(
        report,
        doc_id,
        "missing-required",
        anchor in missing_keys,
        field_key=anchor,
        expected=f"{anchor!r} unresolved",
        actual=repr(missing_keys),
        metric=_FALSE_NEGATIVE_METRIC,
    )

    for field in manifest["fields"]:
        if field.get("required") is not True:
            continue
        key = field["key"]
        whitespace = copy.deepcopy(complete)
        whitespace.fields[key].value = "   "
        whitespace_keys = unresolved_required_field_keys(manifest, whitespace)
        _record(
            report,
            doc_id,
            f"required-field:{key}:whitespace",
            key in whitespace_keys,
            field_key=key,
            expected="whitespace-only confirmed value remains unresolved",
            actual=repr(whitespace_keys),
            metric=_FALSE_NEGATIVE_METRIC,
        )

    _evaluate_conditions(report, document, manifest)
    _evaluate_constraints(report, document, manifest)
    _evaluate_unknown_field(report, document, manifest)
    _evaluate_conflicts(report, document, manifest)
    _evaluate_idempotency(report, document, manifest)
    _evaluate_semantic_projection(report, document, manifest)


def _evaluate_conditions(
    report: QualityReport,
    document: CorpusDocument,
    manifest: dict[str, Any],
) -> None:
    fields = {field["key"]: field for field in manifest["fields"]}
    for dependent in manifest["fields"]:
        raw_condition = dependent.get("required_when")
        if raw_condition is None:
            continue
        conditions = (
            raw_condition if isinstance(raw_condition, list) else [raw_condition]
        )
        case_prefix = f"required-when:{dependent['key']}"
        matching_values = _condition_witness_values(manifest, conditions)

        unconfirmed = _fresh_snapshot(document.doc_id, manifest)
        active_unconfirmed = dependent["key"] in required_field_keys(
            manifest, unconfirmed
        )
        _record(
            report,
            document.doc_id,
            f"{case_prefix}:drivers-unconfirmed",
            not active_unconfirmed,
            field_key=dependent["key"],
            expected="inactive until every driver is confirmed",
            actual=f"active={active_unconfirmed}",
            metric=_FALSE_POSITIVE_METRIC,
        )

        matched = _confirm_values(
            _fresh_snapshot(document.doc_id, manifest),
            manifest,
            matching_values,
        )
        matched_unresolved = unresolved_required_field_keys(manifest, matched)
        _record(
            report,
            document.doc_id,
            f"{case_prefix}:all-matched-missing",
            dependent["key"] in matched_unresolved,
            field_key=dependent["key"],
            expected="dependent unresolved when all conditions match",
            actual=repr(matched_unresolved),
            metric=_FALSE_NEGATIVE_METRIC,
        )

        resolved = _confirm_values(
            matched,
            manifest,
            {dependent["key"]: _valid_value(fields[dependent["key"]])},
        )
        resolved_keys = unresolved_required_field_keys(manifest, resolved)
        _record(
            report,
            document.doc_id,
            f"{case_prefix}:all-matched-confirmed",
            dependent["key"] not in resolved_keys,
            field_key=dependent["key"],
            expected="dependent resolved",
            actual=repr(resolved_keys),
            metric=_FALSE_POSITIVE_METRIC,
        )

        for index, condition in enumerate(conditions):
            driver_key = condition["field"]
            unconfirmed_values = {
                key: value
                for key, value in matching_values.items()
                if key != driver_key
            }
            one_unconfirmed = _confirm_values(
                _fresh_snapshot(document.doc_id, manifest),
                manifest,
                unconfirmed_values,
            )
            unconfirmed_keys = required_field_keys(manifest, one_unconfirmed)
            _record(
                report,
                document.doc_id,
                f"{case_prefix}:{index}:driver-unconfirmed",
                dependent["key"] not in unconfirmed_keys,
                field_key=dependent["key"],
                expected="dependent not required",
                actual=repr(unconfirmed_keys),
                metric=_FALSE_POSITIVE_METRIC,
            )

            if (condition.get("op") or "equals") == "exists":
                continue
            negative_values = _condition_witness_values(
                manifest,
                conditions,
                failing_index=index,
            )
            one_mismatch = _confirm_values(
                _fresh_snapshot(document.doc_id, manifest),
                manifest,
                negative_values,
            )
            mismatch_keys = required_field_keys(manifest, one_mismatch)
            _record(
                report,
                document.doc_id,
                f"{case_prefix}:{index}:driver-mismatched",
                dependent["key"] not in mismatch_keys,
                field_key=dependent["key"],
                expected="dependent not required",
                actual=repr(mismatch_keys),
                metric=_FALSE_POSITIVE_METRIC,
            )


def _evaluate_constraints(
    report: QualityReport,
    document: CorpusDocument,
    manifest: dict[str, Any],
) -> None:
    for field in manifest["fields"]:
        snapshot = _fresh_snapshot(document.doc_id, manifest)
        bad_type = FieldPatchRequest(
            patch_id=f"{document.doc_id}-invalid-type-{field['key']}",
            base_revision=0,
            source="form",
            operations=[
                FieldPatchOperation(op="confirm", key=field["key"], value=123)
            ],
        )
        rejected, errors = _rejected_patch(snapshot, bad_type, manifest)
        _record(
            report,
            document.doc_id,
            f"field-constraints:{field['key']}:invalid-type",
            rejected
            and any(error.kind == "invalid_type" for error in errors)
            and snapshot.revision == 0,
            field_key=field["key"],
            expected="invalid_type with unchanged revision",
            actual=repr([error.kind for error in errors]),
            metric=_INVALID_TYPE_METRIC,
            metric_triggered=not rejected,
        )

        if field.get("type") != "date":
            continue
        valid = _confirm_values(
            _fresh_snapshot(document.doc_id, manifest),
            manifest,
            {field["key"]: "2026-01-15"},
        )
        _record(
            report,
            document.doc_id,
            f"field-constraints:{field['key']}:valid-date",
            valid.fields[field["key"]].status == "confirmed",
            field_key=field["key"],
            expected="confirmed",
            actual=valid.fields[field["key"]].status,
        )
        invalid = FieldPatchRequest(
            patch_id=f"{document.doc_id}-{field['key']}-invalid-date",
            base_revision=0,
            source="form",
            operations=[
                FieldPatchOperation(
                    op="confirm",
                    key=field["key"],
                    value="2026-02-30",
                )
            ],
        )
        rejected, errors = _rejected_patch(
            _fresh_snapshot(document.doc_id, manifest), invalid, manifest
        )
        _record(
            report,
            document.doc_id,
            f"field-constraints:{field['key']}:invalid-date",
            rejected and any(error.kind == "invalid_date" for error in errors),
            field_key=field["key"],
            expected="invalid_date",
            actual=repr([error.kind for error in errors]),
            metric=_INVALID_TYPE_METRIC,
            metric_triggered=not rejected,
        )



def _evaluate_unknown_field(
    report: QualityReport,
    document: CorpusDocument,
    manifest: dict[str, Any],
) -> None:
    snapshot = _fresh_snapshot(document.doc_id, manifest)
    before = snapshot.model_dump(mode="json")
    patch = FieldPatchRequest(
        patch_id=f"{document.doc_id}-unknown",
        base_revision=0,
        source="llm",
        operations=[
            FieldPatchOperation(op="propose", key="未声明字段", value="非法值")
        ],
    )
    rejected, errors = _rejected_patch(snapshot, patch, manifest, source="llm")
    unchanged = snapshot.model_dump(mode="json") == before
    _record(
        report,
        document.doc_id,
        "unknown-field",
        rejected
        and any(error.kind == "unknown_field" for error in errors)
        and unchanged,
        field_key="未声明字段",
        expected="unknown_field and no state mutation",
        actual=repr([error.kind for error in errors]),
        metric=_UNKNOWN_FIELD_METRIC,
        metric_triggered=not rejected,
    )


def _evaluate_conflicts(
    report: QualityReport,
    document: CorpusDocument,
    manifest: dict[str, Any],
) -> None:
    anchor = document.anchor_field
    field_def = _field_def(manifest, anchor)
    value_a, value_b = _distinct_valid_values(field_def)
    confirmed = _confirm_values(
        _fresh_snapshot(document.doc_id, manifest), manifest, {anchor: value_a}
    )
    conflicted = _apply(
        confirmed,
        manifest,
        patch_id=f"{document.doc_id}-conflict",
        source="llm",
        operations=[FieldPatchOperation(op="propose", key=anchor, value=value_b)],
    )
    state = conflicted.fields[anchor]
    conflict_valid = (
        state.status == "conflict"
        and state.value == value_a
        and state.conflict is not None
        and state.conflict.base_value == value_a
        and state.conflict.proposed_value == value_b
        and conflicted.revision == 2
    )
    _record(
        report,
        document.doc_id,
        "conflict-transitions:created",
        conflict_valid,
        field_key=anchor,
        expected=f"conflict(base={value_a!r}, candidate={value_b!r})",
        actual=repr(state.model_dump(mode="json")),
        metric=_CONFLICT_METRIC,
    )

    rejected = _apply(
        copy.deepcopy(conflicted),
        manifest,
        patch_id=f"{document.doc_id}-keep-base",
        source="form",
        operations=[FieldPatchOperation(op="reject", key=anchor)],
    )
    kept = rejected.fields[anchor]
    _record(
        report,
        document.doc_id,
        "conflict-transitions:keep-base",
        kept.status == "confirmed"
        and kept.value == value_a
        and kept.provenance[-1].operation == "reject"
        and rejected.revision == 3,
        field_key=anchor,
        expected=f"confirmed {value_a!r} at revision 3",
        actual=repr(kept.model_dump(mode="json")),
        metric=_CONFLICT_METRIC,
    )

    accepted = _apply(
        copy.deepcopy(conflicted),
        manifest,
        patch_id=f"{document.doc_id}-accept-candidate",
        source="form",
        operations=[FieldPatchOperation(op="confirm", key=anchor)],
    )
    chosen = accepted.fields[anchor]
    _record(
        report,
        document.doc_id,
        "conflict-transitions:accept-candidate",
        chosen.status == "confirmed"
        and chosen.value == value_b
        and chosen.provenance[-1].operation == "confirm"
        and accepted.revision == 3,
        field_key=anchor,
        expected=f"confirmed {value_b!r} at revision 3",
        actual=repr(chosen.model_dump(mode="json")),
        metric=_CONFLICT_METRIC,
    )


def _evaluate_idempotency(
    report: QualityReport,
    document: CorpusDocument,
    manifest: dict[str, Any],
) -> None:
    anchor = document.anchor_field
    patch = FieldPatchRequest(
        patch_id=f"{document.doc_id}-idempotent",
        base_revision=0,
        source="llm",
        operations=[
            FieldPatchOperation(
                op="propose",
                key=anchor,
                value=_valid_value(_field_def(manifest, anchor)),
            )
        ],
    )
    first = apply_field_patch(
        snapshot=_fresh_snapshot(document.doc_id, manifest),
        patch=patch,
        manifest=manifest,
        actor_user_id=1,
        actor_source="llm",
        now=_FIXED_AT,
    )
    replay = apply_field_patch(
        snapshot=first.snapshot,
        patch=patch,
        manifest=manifest,
        actor_user_id=1,
        actor_source="llm",
        now=_FIXED_AT,
    )
    _record(
        report,
        document.doc_id,
        "idempotency-concurrency:replay",
        replay.duplicate
        and replay.snapshot.revision == first.snapshot.revision
        and len(replay.snapshot.applied_patches) == 1,
        field_key=anchor,
        expected="duplicate without revision or event",
        actual=(
            f"duplicate={replay.duplicate}, revision={replay.snapshot.revision}, "
            f"patches={len(replay.snapshot.applied_patches)}"
        ),
    )

    stale = FieldPatchRequest(
        patch_id=f"{document.doc_id}-stale",
        base_revision=0,
        source="llm",
        operations=[
            FieldPatchOperation(op="propose", key=anchor, value="过期候选")
        ],
    )
    before = first.snapshot.model_dump(mode="json")
    rejected, errors = _rejected_patch(
        first.snapshot, stale, manifest, source="llm"
    )
    _record(
        report,
        document.doc_id,
        "idempotency-concurrency:stale-revision",
        rejected
        and any(error.kind == "revision_conflict" for error in errors)
        and first.snapshot.model_dump(mode="json") == before,
        field_key=anchor,
        expected="revision_conflict without mutation",
        actual=repr([error.kind for error in errors]),
    )


def _evaluate_semantic_projection(
    report: QualityReport,
    document: CorpusDocument,
    manifest: dict[str, Any],
) -> None:
    field = _conflict_field(manifest)
    key = field["key"]
    base_value, candidate = _distinct_valid_values(field)

    confirmed = _confirm_values(
        _fresh_snapshot(document.doc_id, manifest),
        manifest,
        {key: base_value},
    )
    conflict = _apply(
        confirmed,
        manifest,
        patch_id=f"{document.doc_id}-semantic-conflict",
        source="llm",
        operations=[FieldPatchOperation(op="propose", key=key, value=candidate)],
    )
    conflict_model = build_export_document(
        doc_id=document.doc_id,
        title=f"{document.doc_id}-conflict-projection",
        manifest=manifest,
        snapshot=conflict,
    )
    normalized_conflict_html = _normalize_output_text(conflict_model.html)
    _record(
        report,
        document.doc_id,
        "cross-format-semantics:conflict-projection",
        _normalize_output_text(base_value) in normalized_conflict_html
        and _normalize_output_text(candidate) not in normalized_conflict_html,
        field_key=key,
        expected="stable base present and conflict candidate absent",
        actual=f"base={base_value!r}, candidate={candidate!r}",
        metric=_SEMANTIC_METRIC,
    )

    pending = _apply(
        _fresh_snapshot(document.doc_id, manifest),
        manifest,
        patch_id=f"{document.doc_id}-semantic-pending",
        source="llm",
        operations=[FieldPatchOperation(op="propose", key=key, value=candidate)],
    )
    pending_model = build_export_document(
        doc_id=document.doc_id,
        title=f"{document.doc_id}-pending-projection",
        manifest=manifest,
        snapshot=pending,
    )
    _record(
        report,
        document.doc_id,
        "cross-format-semantics:pending-projection",
        _normalize_output_text(candidate)
        not in _normalize_output_text(pending_model.html),
        field_key=key,
        expected="pending candidate absent",
        actual=f"candidate={candidate!r}",
        metric=_SEMANTIC_METRIC,
    )


def _evaluate_routes(
    report: QualityReport,
    client: TestClient,
    get_conn,
    headers: dict[str, str],
    document: CorpusDocument,
    manifest: dict[str, Any],
) -> None:
    complete = _create_document(client, headers, document.doc_id, "complete")
    complete_snapshot = _api_confirm_fields(
        client, headers, complete["id"], manifest, manifest["fields"], 0
    )
    complete_snapshot, forbidden_values = _add_nonblocking_candidates(
        client,
        headers,
        complete["id"],
        manifest,
        complete_snapshot,
    )
    readiness = client.get(
        f"/api/documents/{complete['id']}/download-readiness",
        headers=headers,
    )
    readiness_body = readiness.json() if readiness.status_code == 200 else {}
    _record(
        report,
        document.doc_id,
        "complete-state:download-readiness",
        readiness.status_code == 200
        and readiness_body.get("can_download") is True
        and readiness_body.get("unresolved_required_fields") == [],
        expected="HTTP 200 with can_download=true and no unresolved fields",
        actual=f"HTTP {readiness.status_code}, body={readiness_body!r}",
        metric=_FALSE_POSITIVE_METRIC,
    )
    model = build_export_document(
        doc_id=document.doc_id,
        title=complete["title"],
        manifest=manifest,
        snapshot=DraftStateSnapshot.model_validate(complete_snapshot),
    )
    for renderer in ("docx", "pdf"):
        response = client.get(
            f"/api/documents/{complete['id']}/download?format={renderer}",
            headers=headers,
        )
        issues = _semantic_response_issues(
            renderer,
            response,
            model,
            forbidden_values=forbidden_values,
        )
        _record(
            report,
            document.doc_id,
            f"cross-format-semantics:{renderer}",
            not issues,
            field_key=document.anchor_field,
            expected="actual download matches the authoritative export model",
            actual="; ".join(issues) if issues else "matched",
            metric=_SEMANTIC_METRIC,
        )
    _evaluate_invalid_downloads(
        report, client, get_conn, headers, document, manifest
    )
    _evaluate_public_put(report, client, headers, document, manifest)


def _evaluate_invalid_downloads(
    report: QualityReport,
    client: TestClient,
    get_conn,
    headers: dict[str, str],
    document: CorpusDocument,
    manifest: dict[str, Any],
) -> None:
    anchor = document.anchor_field

    missing = _create_document(client, headers, document.doc_id, "missing")
    _assert_blocked_formats(
        report, client, headers, document.doc_id, missing["id"], "missing", anchor
    )

    pending = _create_document(client, headers, document.doc_id, "pending")
    pending_response = _api_patch(
        client,
        headers,
        pending["id"],
        patch_id=f"{document.doc_id}-pending",
        base_revision=0,
        source="llm",
        operations=[
            {
                "op": "propose",
                "key": anchor,
                "value": _valid_value(_field_def(manifest, anchor)),
            }
        ],
    )
    if pending_response.status_code == 200:
        _assert_blocked_formats(
            report,
            client,
            headers,
            document.doc_id,
            pending["id"],
            "pending",
            anchor,
        )
    else:
        _record(
            report,
            document.doc_id,
            "invalid-downloads:pending-setup",
            False,
            field_key=anchor,
            expected="patch 200",
            actual=f"HTTP {pending_response.status_code}",
        )

    conflict = _create_document(client, headers, document.doc_id, "conflict")
    try:
        confirmed = _api_confirm_fields(
            client, headers, conflict["id"], manifest, manifest["fields"], 0
        )
    except RuntimeError as exc:
        _record(
            report,
            document.doc_id,
            "invalid-downloads:conflict-setup",
            False,
            field_key=anchor,
            expected="confirmation patch 200",
            actual=str(exc),
        )
        confirmed = None
    if confirmed is not None:
        base_value, conflict_value = _distinct_valid_values(
            _field_def(manifest, anchor)
        )
        current_value = confirmed["fields"][anchor].get("value")
        conflict_value = conflict_value if current_value == base_value else base_value
        conflict_response = _api_patch(
            client,
            headers,
            conflict["id"],
            patch_id=f"{document.doc_id}-download-conflict",
            base_revision=confirmed["revision"],
            source="llm",
            operations=[
                {
                    "op": "propose",
                    "key": anchor,
                    "value": conflict_value,
                }
            ],
        )
        if conflict_response.status_code == 200:
            _assert_blocked_formats(
                report,
                client,
                headers,
                document.doc_id,
                conflict["id"],
                "required-conflict",
                anchor,
            )
        else:
            _record(
                report,
                document.doc_id,
                "invalid-downloads:conflict-setup",
                False,
                field_key=anchor,
                expected="patch 200",
                actual=f"HTTP {conflict_response.status_code}",
            )

    whitespace = _create_document(client, headers, document.doc_id, "whitespace")
    try:
        whitespace_snapshot = _api_confirm_fields(
            client, headers, whitespace["id"], manifest, manifest["fields"], 0
        )
    except RuntimeError as exc:
        _record(
            report,
            document.doc_id,
            "invalid-downloads:whitespace-setup",
            False,
            field_key=anchor,
            expected="confirmation patch 200",
            actual=str(exc),
        )
    else:
        whitespace_snapshot["fields"][anchor]["value"] = "   "
        with get_conn() as conn:
            conn.execute(
                "UPDATE documents SET state_json = ? WHERE id = ?",
                (
                    json.dumps(
                        {"draft_state": whitespace_snapshot},
                        ensure_ascii=False,
                    ),
                    whitespace["id"],
                ),
            )
        _assert_blocked_formats(
            report,
            client,
            headers,
            document.doc_id,
            whitespace["id"],
            "whitespace",
            anchor,
        )

    for dependent in manifest["fields"]:
        raw_condition = dependent.get("required_when")
        if raw_condition is None:
            continue
        conditions = (
            raw_condition if isinstance(raw_condition, list) else [raw_condition]
        )
        conditional = _create_document(
            client,
            headers,
            document.doc_id,
            f"conditional-{dependent['key']}",
        )
        overrides = _condition_witness_values(manifest, conditions)
        fields = [
            field
            for field in manifest["fields"]
            if field["key"] != dependent["key"]
        ]
        try:
            _api_confirm_fields(
                client,
                headers,
                conditional["id"],
                manifest,
                fields,
                0,
                overrides=overrides,
            )
        except RuntimeError as exc:
            _record(
                report,
                document.doc_id,
                f"invalid-downloads:required-when-{dependent['key']}-setup",
                False,
                field_key=dependent["key"],
                expected="confirmation patch 200",
                actual=str(exc),
            )
        else:
            _assert_blocked_formats(
                report,
                client,
                headers,
                document.doc_id,
                conditional["id"],
                f"required-when-{dependent['key']}",
                dependent["key"],
            )


def _evaluate_public_put(
    report: QualityReport,
    client: TestClient,
    headers: dict[str, str],
    document: CorpusDocument,
    manifest: dict[str, Any],
) -> None:
    created = _create_document(client, headers, document.doc_id, "put-protection")
    snapshot = _api_confirm_fields(
        client,
        headers,
        created["id"],
        manifest,
        [_field_def(manifest, document.anchor_field)],
        0,
    )
    incoming = {
        "chat": [{"role": "user", "content": "non-field autosave"}],
        "fields": {document.anchor_field: "回滚值"},
        "draft_state": {
            **snapshot,
            "revision": 0,
            "fields": {},
            "applied_patches": {},
        },
    }
    response = client.put(
        f"/api/documents/{created['id']}",
        headers=headers,
        json={"state": incoming},
    )
    state = response.json().get("state", {}) if response.status_code == 200 else {}
    stored = state.get("draft_state", {})
    field = stored.get("fields", {}).get(document.anchor_field, {})
    _record(
        report,
        document.doc_id,
        "public-put-protection",
        response.status_code == 200
        and stored.get("revision") == snapshot["revision"]
        and field.get("value") == snapshot["fields"][document.anchor_field]["value"]
        and state.get("chat") == incoming["chat"],
        field_key=document.anchor_field,
        expected="latest kernel snapshot plus incoming chat",
        actual=(
            f"HTTP {response.status_code}, revision={stored.get('revision')}, "
            f"value={field.get('value')!r}"
        ),
    )


def _add_nonblocking_candidates(
    client: TestClient,
    headers: dict[str, str],
    document_id: int,
    manifest: dict[str, Any],
    snapshot: dict[str, Any],
) -> tuple[dict[str, Any], tuple[str, ...]]:
    eligible: list[tuple[dict[str, Any], tuple[str, str]]] = []
    for field in manifest["fields"]:
        if field.get("required") or field.get("required_when") is not None:
            continue
        try:
            values = _distinct_valid_values(field)
        except CorpusValidationError:
            continue
        eligible.append((field, values))

    forbidden: list[str] = []
    if eligible:
        field, values = eligible[0]
        current = snapshot["fields"][field["key"]].get("value")
        candidate = values[1] if current == values[0] else values[0]
        response = _api_patch(
            client,
            headers,
            document_id,
            patch_id=f"semantic-conflict-{document_id}",
            base_revision=snapshot["revision"],
            source="llm",
            operations=[
                {"op": "propose", "key": field["key"], "value": candidate}
            ],
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Semantic conflict setup failed: HTTP {response.status_code}"
            )
        snapshot = response.json()["snapshot"]
        forbidden.append(candidate)

    if len(eligible) > 1:
        field, values = eligible[1]
        clear_response = _api_patch(
            client,
            headers,
            document_id,
            patch_id=f"semantic-clear-{document_id}",
            base_revision=snapshot["revision"],
            source="form",
            operations=[{"op": "confirm", "key": field["key"], "value": ""}],
        )
        if clear_response.status_code != 200:
            raise RuntimeError(
                f"Semantic pending clear failed: HTTP {clear_response.status_code}"
            )
        snapshot = clear_response.json()["snapshot"]
        candidate = values[0]
        pending_response = _api_patch(
            client,
            headers,
            document_id,
            patch_id=f"semantic-pending-{document_id}",
            base_revision=snapshot["revision"],
            source="llm",
            operations=[
                {"op": "propose", "key": field["key"], "value": candidate}
            ],
        )
        if pending_response.status_code != 200:
            raise RuntimeError(
                f"Semantic pending setup failed: HTTP {pending_response.status_code}"
            )
        snapshot = pending_response.json()["snapshot"]
        forbidden.append(candidate)

    return snapshot, tuple(forbidden)


def _semantic_response_issues(
    renderer: str,
    response: Any,
    model: ExportDocument,
    *,
    forbidden_values: tuple[str, ...],
) -> list[str]:
    issues: list[str] = []
    status_code = getattr(response, "status_code", None)
    if status_code != 200:
        return [f"download returned HTTP {status_code}"]

    payload = getattr(response, "content", b"")
    headers = getattr(response, "headers", {})
    content_type = str(headers.get("content-type", "")).lower()
    disposition = str(headers.get("content-disposition", ""))
    expected_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if renderer == "docx"
        else "application/pdf"
    )
    if not content_type.startswith(expected_type):
        issues.append(f"wrong content type {content_type!r}")
    if (
        "attachment" not in disposition.lower()
        or "filename*=UTF-8''" not in disposition
        or f".{renderer}" not in disposition.lower()
    ):
        issues.append("invalid Content-Disposition")

    signature = b"PK" if renderer == "docx" else b"%PDF"
    if not isinstance(payload, bytes) or not payload.startswith(signature):
        issues.append(f"{renderer.upper()} signature missing")
        return issues

    try:
        text = _docx_text(payload) if renderer == "docx" else _pdf_text(payload)
    except Exception as exc:
        issues.append(f"{renderer.upper()} parse failed: {type(exc).__name__}")
        return issues

    normalized_text = _normalize_output_text(text)
    if _normalize_output_text(model.title) not in normalized_text:
        issues.append("rendered title missing")
    for field in model.fields:
        if field.value and _normalize_output_text(field.value) not in normalized_text:
            issues.append(f"rendered field missing: {field.key}")
    if _normalize_output_text(model.disclaimer) not in normalized_text:
        issues.append("rendered disclaimer missing")

    standard_blocks = [
        block for block in model.blocks if block.section == "standard_terms"
    ]
    if not standard_blocks:
        issues.append("standard terms absent from semantic projection")
    elif not any(
        _normalize_output_text(block.text) in normalized_text
        for block in standard_blocks
        if _normalize_output_text(block.text)
    ):
        issues.append("standard terms content missing")
    cursor = 0
    for block in model.blocks:
        expected = _normalize_output_text(block.text)
        if not expected:
            continue
        position = normalized_text.find(expected, cursor)
        if position < 0:
            issues.append(
                f"rendered block missing or out of order: {block.section}:{block.order}"
            )
            continue
        cursor = position + len(expected)
    for value in forbidden_values:
        if _normalize_output_text(value) in normalized_text:
            issues.append(f"unconfirmed candidate leaked: {value}")
    return issues


def _assert_blocked_formats(
    report: QualityReport,
    client: TestClient,
    headers: dict[str, str],
    doc_id: str,
    document_id: int,
    state_name: str,
    expected_key: str,
) -> None:
    for renderer in ("docx", "pdf"):
        response = client.get(
            f"/api/documents/{document_id}/download?format={renderer}",
            headers=headers,
        )
        detail = (
            response.json().get("detail", {})
            if response.status_code == 409
            else {}
        )
        unresolved = detail.get("unresolved_required_fields", [])
        _record(
            report,
            doc_id,
            f"invalid-downloads:{state_name}:{renderer}",
            response.status_code == 409 and expected_key in unresolved,
            field_key=expected_key,
            expected=f"HTTP 409 containing {expected_key!r}",
            actual=f"HTTP {response.status_code}, unresolved={unresolved!r}",
            metric=_INVALID_DOWNLOAD_METRIC,
            metric_triggered=200 <= response.status_code < 300,
        )


def _fresh_snapshot(doc_id: str, manifest: dict[str, Any]) -> DraftStateSnapshot:
    return snapshot_from_document_state(doc_id=doc_id, state={}, manifest=manifest)


def _confirm_fields(
    snapshot: DraftStateSnapshot,
    fields: list[dict[str, Any]],
) -> DraftStateSnapshot:
    if not fields:
        return snapshot
    return _apply(
        snapshot,
        {"fields": fields},
        patch_id=f"{snapshot.doc_id}-confirm-{snapshot.revision}",
        source="form",
        operations=[
            FieldPatchOperation(
                op="confirm", key=field["key"], value=_valid_value(field)
            )
            for field in fields
        ],
    )


def _confirm_values(
    snapshot: DraftStateSnapshot,
    manifest: dict[str, Any],
    values: dict[str, str],
) -> DraftStateSnapshot:
    if not values:
        return snapshot
    return _apply(
        snapshot,
        manifest,
        patch_id=f"{snapshot.doc_id}-values-{snapshot.revision}-"
        + "-".join(values),
        source="form",
        operations=[
            FieldPatchOperation(op="confirm", key=key, value=value)
            for key, value in values.items()
        ],
    )


def _apply(
    snapshot: DraftStateSnapshot,
    manifest: dict[str, Any],
    *,
    patch_id: str,
    source: str,
    operations: list[FieldPatchOperation],
) -> DraftStateSnapshot:
    patch = FieldPatchRequest(
        patch_id=patch_id,
        base_revision=snapshot.revision,
        source=source,
        operations=operations,
    )
    return apply_field_patch(
        snapshot=snapshot,
        patch=patch,
        manifest=manifest,
        actor_user_id=1,
        actor_source="llm" if source == "llm" else "form",
        now=_FIXED_AT,
    ).snapshot


def _rejected_patch(
    snapshot: DraftStateSnapshot,
    patch: FieldPatchRequest,
    manifest: dict[str, Any],
    *,
    source: str = "form",
) -> tuple[bool, list[Any]]:
    try:
        apply_field_patch(
            snapshot=snapshot,
            patch=patch,
            manifest=manifest,
            actor_user_id=1,
            actor_source="llm" if source == "llm" else "form",
            now=_FIXED_AT,
        )
    except DraftPatchRejected as exc:
        return True, exc.errors
    return False, []


def _valid_value(field: dict[str, Any]) -> str:
    candidates = _valid_value_candidates(field, [])
    if not candidates:
        raise CorpusValidationError(
            "field_witness_unavailable",
            f"No valid deterministic value exists for {field.get('key')!r}.",
        )
    return candidates[0]


def _distinct_valid_values(field: dict[str, Any]) -> tuple[str, str]:
    candidates = _valid_value_candidates(field, [])
    if len(candidates) < 2:
        raise CorpusValidationError(
            "field_witness_unavailable",
            f"Two distinct valid values are required for {field.get('key')!r}.",
        )
    return candidates[0], candidates[1]


def _condition_witness_values(
    manifest: dict[str, Any],
    conditions: list[dict[str, Any]],
    *,
    failing_index: int | None = None,
) -> dict[str, str]:
    fields = {
        field["key"]: field
        for field in manifest.get("fields", [])
        if isinstance(field, dict) and isinstance(field.get("key"), str)
    }
    grouped: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for index, condition in enumerate(conditions):
        key = condition.get("field")
        if not isinstance(key, str) or key not in fields:
            raise CorpusValidationError(
                "unknown_condition_field",
                f"Condition references unknown field {key!r}.",
            )
        grouped.setdefault(key, []).append((index, condition))

    assignments: dict[str, str] = {}
    for key, entries in grouped.items():
        field = fields[key]
        candidates = _valid_value_candidates(
            field,
            [condition for _index, condition in entries],
        )
        selected = next(
            (
                candidate
                for candidate in candidates
                if all(
                    _condition_matches_value(condition, candidate)
                    != (index == failing_index)
                    for index, condition in entries
                )
            ),
            None,
        )
        if selected is None:
            mode = "negative" if failing_index is not None else "positive"
            raise CorpusValidationError(
                "condition_witness_unavailable",
                "No "
                f"{mode} condition witness exists for "
                f"{manifest.get('doc_id')}:{key}.",
            )
        assignments[key] = selected
    return assignments


def _valid_value_candidates(
    field: dict[str, Any],
    conditions: list[dict[str, Any]],
) -> list[str]:
    choices = field.get("enum") or field.get("options")
    constrained = isinstance(choices, list) and bool(choices)
    operands: list[str] = []
    for condition in conditions:
        value = condition.get("value")
        if isinstance(value, str):
            operands.append(value)
        values = condition.get("values")
        if isinstance(values, list):
            operands.extend(value for value in values if isinstance(value, str))

    raw_candidates: list[str] = []
    if constrained:
        raw_candidates.extend(value for value in choices if isinstance(value, str))
    raw_candidates.extend(operands)
    example = field.get("example")
    if isinstance(example, str):
        raw_candidates.append(example)
    if field.get("type") == "date":
        raw_candidates.extend(("2026-01-15", "2026-01-16", "2026-01-17"))
    else:
        key = field.get("key") or "字段"
        raw_candidates.extend((f"{key}确定性测试值", f"{key}确定性候选值"))

    candidates: list[str] = []
    for raw in raw_candidates:
        value = raw.strip()
        if not value or value in candidates:
            continue
        if constrained and value not in choices:
            continue
        if field.get("type") == "date":
            try:
                date.fromisoformat(value)
            except ValueError:
                continue
        candidates.append(value)
    return candidates


def _condition_matches_value(condition: dict[str, Any], value: str) -> bool:
    op = condition.get("op") or "equals"
    if op == "equals":
        return value == condition.get("value")
    if op == "not_equals":
        return value != condition.get("value")
    if op == "in":
        values = condition.get("values")
        return isinstance(values, list) and value in values
    if op == "exists":
        return bool(value)
    return False


def _field_def(manifest: dict[str, Any], key: str) -> dict[str, Any]:
    for field in manifest.get("fields", []):
        if isinstance(field, dict) and field.get("key") == key:
            return field
    raise CorpusValidationError(
        "unknown_corpus_field",
        f"Manifest {manifest.get('doc_id')!r} has no field {key!r}.",
    )


def _conflict_field(manifest: dict[str, Any]) -> dict[str, Any]:
    for field in manifest.get("fields", []):
        if not isinstance(field, dict):
            continue
        if len(_valid_value_candidates(field, [])) >= 2:
            return field
    raise CorpusValidationError(
        "field_witness_unavailable",
        f"Manifest {manifest.get('doc_id')!r} has no conflict-testable field.",
    )


def _manifest(doc_id: str) -> dict[str, Any]:
    manifest = load_manifest(doc_id)
    if manifest is None:
        raise RuntimeError(f"Manifest unavailable for {doc_id}")
    return manifest


def _record(
    report: QualityReport,
    doc_id: str,
    case_id: str,
    passed: bool,
    *,
    field_key: str | None = None,
    expected: str | None = None,
    actual: str | None = None,
    metric: str | None = None,
    metric_triggered: bool | None = None,
) -> None:
    report.add(
        QualityCaseResult(
            doc_id=doc_id,
            case_id=case_id,
            passed=passed,
            field_key=field_key,
            expected=expected,
            actual=actual,
            metric=metric,
            metric_triggered=(
                not passed if metric_triggered is None else metric_triggered
            ),
        )
    )


@contextmanager
def _evaluation_client():
    previous_db = os.environ.get("PRELEGAL_DB_PATH")
    previous_rate_limit = os.environ.get("PRELEGAL_RATELIMIT_DISABLED")
    try:
        with tempfile.TemporaryDirectory(prefix="prelegal-quality-") as temp_dir:
            os.environ["PRELEGAL_DB_PATH"] = os.path.join(
                temp_dir, "quality.sqlite"
            )
            os.environ["PRELEGAL_RATELIMIT_DISABLED"] = "1"
            from app import db, ratelimit
            from app.routes import auth, documents

            importlib.reload(db)
            db.init_database()
            for limiter in ratelimit.ALL_LIMITERS:
                limiter.reset()
            app = FastAPI(title="Prelegal deterministic quality evaluator")
            app.include_router(auth.router, prefix="/api")
            app.include_router(documents.router, prefix="/api")
            with TestClient(app) as client:
                yield client, db.get_conn
    finally:
        if previous_db is None:
            os.environ.pop("PRELEGAL_DB_PATH", None)
        else:
            os.environ["PRELEGAL_DB_PATH"] = previous_db
        if previous_rate_limit is None:
            os.environ.pop("PRELEGAL_RATELIMIT_DISABLED", None)
        else:
            os.environ["PRELEGAL_RATELIMIT_DISABLED"] = previous_rate_limit


def _register(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/register",
        json={"email": "quality-evals@example.com", "password": "quality-pass-1"},
    )
    if response.status_code != 201:
        raise RuntimeError(f"Quality evaluator registration failed: {response.text}")
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _create_document(
    client: TestClient,
    headers: dict[str, str],
    doc_id: str,
    suffix: str,
) -> dict[str, Any]:
    response = client.post(
        "/api/documents",
        headers=headers,
        json={"doc_id": doc_id, "title": f"{doc_id}-{suffix}", "state": {}},
    )
    if response.status_code != 201:
        raise RuntimeError(f"Document setup failed for {doc_id}: {response.text}")
    return response.json()


def _api_patch(
    client: TestClient,
    headers: dict[str, str],
    document_id: int,
    *,
    patch_id: str,
    base_revision: int,
    source: str,
    operations: list[dict[str, Any]],
):
    return client.post(
        f"/api/documents/{document_id}/field-patches",
        headers=headers,
        json={
            "patch_id": patch_id,
            "base_revision": base_revision,
            "source": source,
            "operations": operations,
        },
    )


def _api_confirm_fields(
    client: TestClient,
    headers: dict[str, str],
    document_id: int,
    manifest: dict[str, Any],
    fields: list[dict[str, Any]],
    base_revision: int,
    *,
    overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    response = _api_patch(
        client,
        headers,
        document_id,
        patch_id=f"confirm-{document_id}-{base_revision}",
        base_revision=base_revision,
        source="form",
        operations=[
            {
                "op": "confirm",
                "key": field["key"],
                "value": (overrides or {}).get(field["key"], _valid_value(field)),
            }
            for field in fields
        ],
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Field confirmation failed for {manifest['doc_id']}: {response.text}"
        )
    return response.json()["snapshot"]


def _docx_text(payload: bytes) -> str:
    document = Document(BytesIO(payload))
    parts: list[str] = []
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            parts.append(Paragraph(child, document).text)
        elif isinstance(child, CT_Tbl):
            table = Table(child, document)
            for row in table.rows:
                for cell in row.cells:
                    parts.extend(paragraph.text for paragraph in cell.paragraphs)
    return "\n".join(parts)


def _pdf_text(payload: bytes) -> str:
    reader = PdfReader(BytesIO(payload))
    if not reader.pages:
        raise ValueError("PDF has no pages")
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _normalize_output_text(value: str) -> str:
    # PDF text extraction may emit CSS list counters as standalone lines and
    # place them mid-sentence. They are presentation markers, not contract
    # semantics, so remove only whole-line counters before whitespace folding.
    without_list_counters = re.sub(
        r"(?m)^\s*(?:\d+|[A-Za-z])\.\s*$",
        "",
        value,
    )
    return re.sub(r"\s+", "", without_list_counters).replace("\u200b", "")
