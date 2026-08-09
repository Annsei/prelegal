"""Deterministic kernel, download-gate, and export-semantic evaluation."""

from __future__ import annotations

import copy
import importlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from io import BytesIO
from typing import Any

from docx import Document
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
from app.export import DISCLAIMER, build_export_document, render_docx, render_pdf
from app.manifests import load_manifest
from quality_evals.corpus import CorpusDocument, load_corpus, validate_corpus
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
    report = QualityReport.empty()

    for document in validated.documents:
        manifest = _manifest(document.doc_id)
        _evaluate_kernel(report, document, manifest)
        _evaluate_semantic_rendering(report, document, manifest)

    with _evaluation_client() as (client, get_conn):
        headers = _register(client)
        for document in validated.documents:
            _evaluate_routes(
                report,
                client,
                get_conn,
                headers,
                document,
                _manifest(document.doc_id),
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
        for index, condition in enumerate(conditions):
            driver_key = condition["field"]
            case_prefix = f"required-when:{dependent['key']}:{index}"

            unconfirmed = _fresh_snapshot(document.doc_id, manifest)
            active_unconfirmed = dependent["key"] in required_field_keys(
                manifest, unconfirmed
            )
            _record(
                report,
                document.doc_id,
                f"{case_prefix}:driver-unconfirmed",
                not active_unconfirmed,
                field_key=dependent["key"],
                expected="inactive until driver is confirmed",
                actual=f"active={active_unconfirmed}",
                metric=_FALSE_POSITIVE_METRIC,
            )

            matched = _confirm_values(
                _fresh_snapshot(document.doc_id, manifest),
                manifest,
                {driver_key: _matching_value(condition)},
            )
            matched_unresolved = unresolved_required_field_keys(manifest, matched)
            _record(
                report,
                document.doc_id,
                f"{case_prefix}:matched-missing",
                dependent["key"] in matched_unresolved,
                field_key=dependent["key"],
                expected="dependent unresolved",
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
                f"{case_prefix}:matched-confirmed",
                dependent["key"] not in resolved_keys,
                field_key=dependent["key"],
                expected="dependent resolved",
                actual=repr(resolved_keys),
                metric=_FALSE_POSITIVE_METRIC,
            )

            nonmatching = _fresh_snapshot(document.doc_id, manifest)
            nonmatch_value = _nonmatching_value(condition)
            if nonmatch_value is not None:
                nonmatching = _confirm_values(
                    nonmatching,
                    manifest,
                    {driver_key: nonmatch_value},
                )
            nonmatching_keys = required_field_keys(manifest, nonmatching)
            _record(
                report,
                document.doc_id,
                f"{case_prefix}:driver-nonmatching",
                dependent["key"] not in nonmatching_keys,
                field_key=dependent["key"],
                expected="dependent not required",
                actual=repr(nonmatching_keys),
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
    value_a = _valid_value(field_def)
    value_b = f"{value_a}-候选变更"
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


def _evaluate_routes(
    report: QualityReport,
    client: TestClient,
    get_conn,
    headers: dict[str, str],
    document: CorpusDocument,
    manifest: dict[str, Any],
) -> None:
    complete = _create_document(client, headers, document.doc_id, "complete")
    _api_confirm_fields(
        client, headers, complete["id"], manifest, manifest["fields"], 0
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
    confirmed = _api_confirm_fields(
        client, headers, conflict["id"], manifest, manifest["fields"], 0
    )
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
                "value": f"{_valid_value(_field_def(manifest, anchor))}-冲突候选",
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

    whitespace = _create_document(client, headers, document.doc_id, "whitespace")
    whitespace_snapshot = _api_confirm_fields(
        client, headers, whitespace["id"], manifest, manifest["fields"], 0
    )
    whitespace_snapshot["fields"][anchor]["value"] = "   "
    with get_conn() as conn:
        conn.execute(
            "UPDATE documents SET state_json = ? WHERE id = ?",
            (
                json.dumps({"draft_state": whitespace_snapshot}, ensure_ascii=False),
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
        for index, condition in enumerate(conditions):
            conditional = _create_document(
                client,
                headers,
                document.doc_id,
                f"conditional-{dependent['key']}-{index}",
            )
            overrides = {condition["field"]: _matching_value(condition)}
            fields = [
                field
                for field in manifest["fields"]
                if field["key"] != dependent["key"]
            ]
            _api_confirm_fields(
                client,
                headers,
                conditional["id"],
                manifest,
                fields,
                0,
                overrides=overrides,
            )
            _assert_blocked_formats(
                report,
                client,
                headers,
                document.doc_id,
                conditional["id"],
                f"required-when-{dependent['key']}-{index}",
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


def _evaluate_semantic_rendering(
    report: QualityReport,
    document: CorpusDocument,
    manifest: dict[str, Any],
) -> None:
    snapshot = _confirm_fields(
        _fresh_snapshot(document.doc_id, manifest), manifest["fields"]
    )
    anchor = document.anchor_field
    stable_value = snapshot.fields[anchor].value or ""
    candidate = f"{stable_value}-不得泄漏的候选"
    snapshot = _apply(
        snapshot,
        manifest,
        patch_id=f"{document.doc_id}-render-conflict",
        source="llm",
        operations=[FieldPatchOperation(op="propose", key=anchor, value=candidate)],
    )
    title = f"{document.doc_id} 确定性评测"
    model = build_export_document(
        doc_id=document.doc_id,
        title=title,
        manifest=manifest,
        snapshot=snapshot,
    )
    issues: list[str] = []
    semantic_anchor = next(field for field in model.fields if field.key == anchor)
    if semantic_anchor.value != stable_value:
        issues.append("canonical model lost stable conflict base")
    expected_conditions = {
        field["key"]: field["key"] in required_field_keys(manifest, snapshot)
        for field in manifest["fields"]
        if field.get("required_when") is not None
    }
    actual_conditions = {
        result.field_key: result.active for result in model.condition_results
    }
    if actual_conditions != expected_conditions:
        issues.append("required_when condition results differ")
    if [block.order for block in model.blocks] != list(range(len(model.blocks))):
        issues.append("canonical block order is not contiguous")
    if not any(block.section == "standard_terms" for block in model.blocks):
        issues.append("standard terms absent from canonical blocks")
    if model.disclaimer != DISCLAIMER:
        issues.append("canonical disclaimer differs")

    try:
        docx_payload = render_docx(model)
        pdf_payload = render_pdf(model)
    except Exception as exc:  # pragma: no cover - failure is reported with context
        issues.append(f"renderer raised {type(exc).__name__}: {exc}")
        docx_payload = b""
        pdf_payload = b""

    if not docx_payload.startswith(b"PK"):
        issues.append("DOCX signature missing")
    if not pdf_payload.startswith(b"%PDF"):
        issues.append("PDF signature missing")

    docx_text = _normalize_output_text(_docx_text(docx_payload)) if docx_payload else ""
    pdf_text = _normalize_output_text(_pdf_text(pdf_payload)) if pdf_payload else ""
    for field in model.fields:
        if field.value is None:
            continue
        normalized = _normalize_output_text(field.value)
        if normalized not in docx_text:
            issues.append(f"DOCX missing field {field.key}")
        if normalized not in pdf_text:
            issues.append(f"PDF missing field {field.key}")
    normalized_disclaimer = _normalize_output_text(DISCLAIMER)
    if normalized_disclaimer not in docx_text:
        issues.append("DOCX disclaimer missing")
    if normalized_disclaimer not in pdf_text:
        issues.append("PDF disclaimer missing")
    if _normalize_output_text(candidate) in docx_text:
        issues.append("DOCX leaked conflict proposal")
    if _normalize_output_text(candidate) in pdf_text:
        issues.append("PDF leaked conflict proposal")

    pending_candidate = f"{stable_value}-不得泄漏的待确认值"
    pending_snapshot = _apply(
        _fresh_snapshot(document.doc_id, manifest),
        manifest,
        patch_id=f"{document.doc_id}-render-pending",
        source="llm",
        operations=[
            FieldPatchOperation(
                op="propose",
                key=anchor,
                value=pending_candidate,
            )
        ],
    )
    pending_model = build_export_document(
        doc_id=document.doc_id,
        title=title,
        manifest=manifest,
        snapshot=pending_snapshot,
    )
    pending_anchor = next(
        field for field in pending_model.fields if field.key == anchor
    )
    if pending_anchor.value is not None:
        issues.append("canonical model treated pending value as stable")
    try:
        pending_docx_text = _normalize_output_text(
            _docx_text(render_docx(pending_model))
        )
        pending_pdf_text = _normalize_output_text(
            _pdf_text(render_pdf(pending_model))
        )
    except Exception as exc:  # pragma: no cover - failure is reported with context
        issues.append(f"pending renderer raised {type(exc).__name__}: {exc}")
        pending_docx_text = ""
        pending_pdf_text = ""
    normalized_pending = _normalize_output_text(pending_candidate)
    if normalized_pending in pending_docx_text:
        issues.append("DOCX leaked pending proposal")
    if normalized_pending in pending_pdf_text:
        issues.append("PDF leaked pending proposal")

    _record(
        report,
        document.doc_id,
        "cross-format-semantics",
        not issues,
        field_key=anchor,
        expected="one canonical model with no renderer mismatch",
        actual="; ".join(issues) if issues else "matched",
        metric=_SEMANTIC_METRIC,
    )


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
    choices = field.get("enum") or field.get("options")
    if isinstance(choices, list) and choices:
        return str(choices[0])
    example = field.get("example")
    if isinstance(example, str) and example.strip():
        return example.strip()
    if field.get("type") == "date":
        return "2026-01-15"
    return f"{field['key']}确定性测试值"


def _matching_value(condition: dict[str, Any]) -> str:
    op = condition.get("op") or "equals"
    if op in {"equals", "not_equals"}:
        if op == "equals":
            return str(condition.get("value", ""))
        return "确定性非匹配基值"
    if op == "in":
        values = condition.get("values") or []
        return str(values[0])
    return "已存在"


def _nonmatching_value(condition: dict[str, Any]) -> str | None:
    op = condition.get("op") or "equals"
    if op == "equals":
        return "确定性不命中值"
    if op == "not_equals":
        return str(condition.get("value", ""))
    if op == "in":
        return "确定性不命中值"
    if op == "exists":
        return None
    return "确定性不命中值"


def _field_def(manifest: dict[str, Any], key: str) -> dict[str, Any]:
    return next(field for field in manifest["fields"] if field["key"] == key)


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
            from app import db, main, ratelimit

            importlib.reload(db)
            importlib.reload(main)
            for limiter in ratelimit.ALL_LIMITERS:
                limiter.reset()
            with TestClient(main.app) as client:
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
    parts = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                parts.extend(paragraph.text for paragraph in cell.paragraphs)
    return "\n".join(parts)


def _pdf_text(payload: bytes) -> str:
    reader = PdfReader(BytesIO(payload))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _normalize_output_text(value: str) -> str:
    return re.sub(r"\s+", "", value).replace("\u200b", "")
