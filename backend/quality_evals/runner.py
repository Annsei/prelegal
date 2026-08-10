"""Deterministic kernel, download-gate, and export-semantic evaluation."""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from contextvars import ContextVar
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
from quality_evals.report import (
    CoverageExpectation,
    QualityCaseResult,
    QualityReport,
)

_FIXED_AT = "2026-01-15T00:00:00+00:00"
_INVALID_TYPE_METRIC = "invalid_type_acceptance_count"
_UNKNOWN_FIELD_METRIC = "unknown_field_acceptance_count"
_FALSE_NEGATIVE_METRIC = "required_field_false_negative_count"
_FALSE_POSITIVE_METRIC = "required_field_false_positive_count"
_CONFLICT_METRIC = "conflict_transition_failure_count"
_INVALID_DOWNLOAD_METRIC = "successful_invalid_downloads"
_SEMANTIC_METRIC = "cross_format_semantic_mismatch_count"

CASE_REGISTRY = {
    "complete_state": "_evaluate_complete_state_case",
    "missing_required": "_evaluate_missing_required_case",
    "required_when": "_evaluate_conditions_case",
    "field_constraints": "_evaluate_constraints_case",
    "unknown_field": "_evaluate_unknown_field_case",
    "conflict_transitions": "_evaluate_conflicts_case",
    "idempotency_concurrency": "_evaluate_idempotency_case",
    "public_put_protection": "_evaluate_public_put_case",
    "invalid_downloads": "_evaluate_invalid_downloads_case",
    "cross_format_semantics": "_evaluate_cross_format_case",
}
_ACTIVE_CASE_KIND: ContextVar[str | None] = ContextVar(
    "quality_eval_case_kind", default=None
)


def run_contract_quality_evaluation(validated=None) -> QualityReport:
    if validated is None:
        validated = validate_corpus(
            load_corpus(), registered_case_kinds=set(CASE_REGISTRY)
        )
    expected_coverage = _build_coverage_plan(validated)
    report = QualityReport.empty(
        expected_doc_ids=validated.corpus_doc_ids,
        expected_coverage=expected_coverage,
    )
    for expectation in expected_coverage:
        if not expectation.applicable:
            report.mark_not_applicable(expectation)

    with _evaluation_client() as (client, get_conn):
        headers = _register(client)
        for case in validated.corpus.cases:
            evaluator_name = CASE_REGISTRY[case.kind]
            evaluator = globals()[evaluator_name]
            token = _ACTIVE_CASE_KIND.set(case.kind)
            try:
                for document in validated.documents:
                    try:
                        evaluator(
                            report,
                            client,
                            get_conn,
                            headers,
                            document,
                            _manifest(document.doc_id),
                        )
                    except Exception as exc:
                        _record(
                            report,
                            document.doc_id,
                            f"{case.id}:setup",
                            False,
                            expected="case evaluation completed",
                            actual=f"{type(exc).__name__}: {exc}",
                        )
            finally:
                _ACTIVE_CASE_KIND.reset(token)

    return report


def _build_coverage_plan(validated) -> tuple[CoverageExpectation, ...]:
    expectations: list[CoverageExpectation] = []
    for case in validated.corpus.cases:
        for document in validated.documents:
            manifest = _manifest(document.doc_id)
            expectations.extend(
                _case_coverage_expectations(
                    case.kind,
                    document,
                    manifest,
                    validated.corpus.renderers,
                )
            )
    return tuple(expectations)


def _case_coverage_expectations(
    case_kind: str,
    document: CorpusDocument,
    manifest: dict[str, Any],
    renderers: tuple[str, ...],
) -> list[CoverageExpectation]:
    doc_id = document.doc_id
    case_ids: list[tuple[str, bool, str | None]] = []
    if case_kind == "complete_state":
        case_ids.extend(
            (case_id, True, None)
            for case_id in ("complete-state", "complete-state:download-readiness")
        )
    elif case_kind == "missing_required":
        case_ids.append(("missing-required", True, None))
        case_ids.extend(
            (f"required-field:{field['key']}:whitespace", True, None)
            for field in manifest["fields"]
            if field.get("required") is True
        )
    elif case_kind == "required_when":
        for dependent in manifest["fields"]:
            raw = dependent.get("required_when")
            if raw is None:
                continue
            conditions = raw if isinstance(raw, list) else [raw]
            positive, negatives = _condition_group_witnesses(manifest, conditions)
            prefix = f"required-when:{dependent['key']}"
            case_ids.extend(
                (case_id, True, None)
                for case_id in (
                    f"{prefix}:drivers-unconfirmed",
                    f"{prefix}:all-matched-missing",
                    f"{prefix}:all-matched-confirmed",
                )
            )
            for driver_key in sorted(positive):
                case_ids.append(
                    (f"{prefix}:driver-{driver_key}:unconfirmed", True, None)
                )
                if driver_key in negatives:
                    case_ids.append(
                        (f"{prefix}:driver-{driver_key}:mismatched", True, None)
                    )
    elif case_kind == "field_constraints":
        for field in manifest["fields"]:
            key = field["key"]
            case_ids.append((f"field-constraints:{key}:invalid-type", True, None))
            if field.get("type") == "date":
                case_ids.extend(
                    (case_id, True, None)
                    for case_id in (
                        f"field-constraints:{key}:valid-date",
                        f"field-constraints:{key}:invalid-date",
                    )
                )
    elif case_kind == "unknown_field":
        case_ids.append(("unknown-field", True, None))
    elif case_kind == "conflict_transitions":
        case_ids.extend(
            (f"conflict-transitions:{scenario}", True, None)
            for scenario in ("created", "keep-base", "accept-candidate")
        )
    elif case_kind == "idempotency_concurrency":
        case_ids.extend(
            (f"idempotency-concurrency:{scenario}", True, None)
            for scenario in ("replay", "stale-revision")
        )
    elif case_kind == "public_put_protection":
        case_ids.append(("public-put-protection", True, None))
    elif case_kind == "invalid_downloads":
        for scenario in ("missing", "pending", "required-conflict", "whitespace"):
            case_ids.extend(
                (f"invalid-downloads:{scenario}:{renderer}", True, None)
                for renderer in renderers
            )
        for dependent in manifest["fields"]:
            if dependent.get("required_when") is None:
                continue
            case_ids.extend(
                (
                    f"invalid-downloads:required-when-{dependent['key']}:{renderer}",
                    True,
                    None,
                )
                for renderer in renderers
            )
    elif case_kind == "cross_format_semantics":
        case_ids.extend(
            (f"cross-format-semantics:{scenario}", True, None)
            for scenario in ("conflict-projection", "pending-projection")
        )
        case_ids.extend(
            (f"cross-format-semantics:complete:{renderer}", True, None)
            for renderer in renderers
        )
        candidates = _candidate_specs(manifest)
        for state_name, candidate in zip(
            ("conflict", "pending"), candidates, strict=True
        ):
            applicable = candidate is not None
            if applicable:
                reason = None
            elif state_name == "conflict":
                reason = (
                    "no non-required conflict candidate; required conflict "
                    "is blocked by download readiness"
                )
            else:
                reason = "no safe non-required pending candidate field"
            case_ids.extend(
                (
                    f"cross-format-semantics:{state_name}:{renderer}",
                    applicable,
                    reason,
                )
                for renderer in renderers
            )
    else:
        raise CorpusValidationError(
            "unregistered_case_kind", f"No coverage planner for {case_kind!r}."
        )
    return [
        _coverage_expectation(doc_id, case_kind, case_id, applicable, reason)
        for case_id, applicable, reason in case_ids
    ]


def _coverage_expectation(
    doc_id: str,
    case_kind: str,
    case_id: str,
    applicable: bool,
    reason: str | None,
) -> CoverageExpectation:
    scenario, renderer = _split_renderer(case_id)
    return CoverageExpectation(
        doc_id=doc_id,
        case_kind=case_kind,
        scenario=scenario,
        renderer=renderer,
        applicable=applicable,
        reason=reason,
    )


def _split_renderer(case_id: str) -> tuple[str, str | None]:
    prefix, separator, suffix = case_id.rpartition(":")
    if separator and suffix in {"docx", "pdf"}:
        return prefix, suffix
    return case_id, None


def _evaluate_complete_state_case(
    report, client, _get_conn, headers, document, manifest
) -> None:
    complete = _confirm_fields(
        _fresh_snapshot(document.doc_id, manifest), manifest["fields"]
    )
    unresolved = unresolved_required_field_keys(manifest, complete)
    _record(
        report,
        document.doc_id,
        "complete-state",
        not unresolved,
        expected="[]",
        actual=repr(unresolved),
        metric=_FALSE_POSITIVE_METRIC,
    )
    created = _create_document(client, headers, document.doc_id, "complete-readiness")
    _api_confirm_fields(client, headers, created["id"], manifest, manifest["fields"], 0)
    readiness = client.get(
        f"/api/documents/{created['id']}/download-readiness", headers=headers
    )
    body = readiness.json() if readiness.status_code == 200 else {}
    _record(
        report,
        document.doc_id,
        "complete-state:download-readiness",
        readiness.status_code == 200
        and body.get("can_download") is True
        and body.get("unresolved_required_fields") == [],
        expected="HTTP 200 with can_download=true and no unresolved fields",
        actual=f"HTTP {readiness.status_code}, body={body!r}",
        metric=_FALSE_POSITIVE_METRIC,
    )


def _evaluate_missing_required_case(
    report, _client, _get_conn, _headers, document, manifest
) -> None:
    anchor = document.anchor_field
    missing = _confirm_fields(
        _fresh_snapshot(document.doc_id, manifest),
        [field for field in manifest["fields"] if field["key"] != anchor],
    )
    missing_keys = unresolved_required_field_keys(manifest, missing)
    _record(
        report,
        document.doc_id,
        "missing-required",
        anchor in missing_keys,
        field_key=anchor,
        expected=f"{anchor!r} unresolved",
        actual=repr(missing_keys),
        metric=_FALSE_NEGATIVE_METRIC,
    )
    complete = _confirm_fields(
        _fresh_snapshot(document.doc_id, manifest), manifest["fields"]
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
            document.doc_id,
            f"required-field:{key}:whitespace",
            key in whitespace_keys,
            field_key=key,
            expected="whitespace-only confirmed value remains unresolved",
            actual=repr(whitespace_keys),
            metric=_FALSE_NEGATIVE_METRIC,
        )


def _evaluate_conditions_case(
    report, _client, _get_conn, _headers, document, manifest
) -> None:
    _evaluate_conditions(report, document, manifest)


def _evaluate_constraints_case(
    report, _client, _get_conn, _headers, document, manifest
) -> None:
    _evaluate_constraints(report, document, manifest)


def _evaluate_unknown_field_case(
    report, _client, _get_conn, _headers, document, manifest
) -> None:
    _evaluate_unknown_field(report, document, manifest)


def _evaluate_conflicts_case(
    report, _client, _get_conn, _headers, document, manifest
) -> None:
    _evaluate_conflicts(report, document, manifest)


def _evaluate_idempotency_case(
    report, _client, _get_conn, _headers, document, manifest
) -> None:
    _evaluate_idempotency(report, document, manifest)


def _evaluate_public_put_case(
    report, client, _get_conn, headers, document, manifest
) -> None:
    _evaluate_public_put(report, client, headers, document, manifest)


def _evaluate_invalid_downloads_case(
    report, client, get_conn, headers, document, manifest
) -> None:
    _evaluate_invalid_downloads(report, client, get_conn, headers, document, manifest)


def _evaluate_cross_format_case(
    report, client, _get_conn, headers, document, manifest
) -> None:
    _evaluate_semantic_projection(report, document, manifest)
    _evaluate_successful_downloads(report, client, headers, document, manifest)


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
        positive, negatives = _condition_group_witnesses(manifest, conditions)
        _record_condition_assignment(
            report,
            document,
            manifest,
            f"{case_prefix}:drivers-unconfirmed",
            {},
            metric=_FALSE_POSITIVE_METRIC,
        )
        matched = _record_condition_assignment(
            report,
            document,
            manifest,
            f"{case_prefix}:all-matched-missing",
            positive,
            metric=_FALSE_NEGATIVE_METRIC,
            expected_unresolved=dependent["key"],
        )
        resolved = _confirm_values(
            matched,
            manifest,
            {dependent["key"]: _valid_value(fields[dependent["key"]])},
        )
        _record_condition_snapshot(
            report,
            document,
            manifest,
            f"{case_prefix}:all-matched-confirmed",
            resolved,
            metric=_FALSE_POSITIVE_METRIC,
            expected_resolved=dependent["key"],
        )

        for driver_key in sorted(positive):
            _record_condition_assignment(
                report,
                document,
                manifest,
                f"{case_prefix}:driver-{driver_key}:unconfirmed",
                {
                    key: value
                    for key, value in positive.items()
                    if key != driver_key
                },
                metric=_FALSE_POSITIVE_METRIC,
            )
            if driver_key in negatives:
                _record_condition_assignment(
                    report,
                    document,
                    manifest,
                    f"{case_prefix}:driver-{driver_key}:mismatched",
                    negatives[driver_key],
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


def _evaluate_successful_downloads(
    report: QualityReport,
    client: TestClient,
    headers: dict[str, str],
    document: CorpusDocument,
    manifest: dict[str, Any],
) -> None:
    complete = _create_document(client, headers, document.doc_id, "semantic-complete")
    complete_snapshot = _api_confirm_fields(
        client, headers, complete["id"], manifest, manifest["fields"], 0
    )
    _assert_semantic_formats(
        report,
        client,
        headers,
        document,
        manifest,
        complete,
        complete_snapshot,
        "complete",
    )

    conflict_spec, pending_spec = _candidate_specs(manifest)
    if conflict_spec is not None:
        _evaluate_candidate_downloads(
            report,
            client,
            headers,
            document,
            manifest,
            "conflict",
            conflict_spec,
        )
    if pending_spec is not None:
        _evaluate_candidate_downloads(
            report,
            client,
            headers,
            document,
            manifest,
            "pending",
            pending_spec,
        )


def _evaluate_candidate_downloads(
    report: QualityReport,
    client: TestClient,
    headers: dict[str, str],
    document: CorpusDocument,
    manifest: dict[str, Any],
    state_name: str,
    spec: tuple[dict[str, Any], str],
) -> None:
    field, candidate = spec
    created = _create_document(
        client, headers, document.doc_id, f"semantic-{state_name}"
    )
    snapshot = _api_confirm_fields(
        client, headers, created["id"], manifest, manifest["fields"], 0
    )
    if state_name == "pending":
        cleared = _api_patch(
            client,
            headers,
            created["id"],
            patch_id=f"semantic-pending-clear-{created['id']}",
            base_revision=snapshot["revision"],
            source="form",
            operations=[{"op": "confirm", "key": field["key"], "value": ""}],
        )
        if cleared.status_code != 200:
            raise RuntimeError(f"Pending clear failed: HTTP {cleared.status_code}")
        snapshot = cleared.json()["snapshot"]
    response = _api_patch(
        client,
        headers,
        created["id"],
        patch_id=f"semantic-{state_name}-{created['id']}",
        base_revision=snapshot["revision"],
        source="llm",
        operations=[{"op": "propose", "key": field["key"], "value": candidate}],
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"{state_name.title()} candidate setup failed: HTTP {response.status_code}"
        )
    _assert_semantic_formats(
        report,
        client,
        headers,
        document,
        manifest,
        created,
        response.json()["snapshot"],
        state_name,
        forbidden_values=(candidate,),
    )


def _assert_semantic_formats(
    report: QualityReport,
    client: TestClient,
    headers: dict[str, str],
    document: CorpusDocument,
    manifest: dict[str, Any],
    created: dict[str, Any],
    snapshot: dict[str, Any],
    state_name: str,
    *,
    forbidden_values: tuple[str, ...] = (),
) -> None:
    model = build_export_document(
        doc_id=document.doc_id,
        title=created["title"],
        manifest=manifest,
        snapshot=DraftStateSnapshot.model_validate(snapshot),
    )
    for renderer in ("docx", "pdf"):
        response = client.get(
            f"/api/documents/{created['id']}/download?format={renderer}",
            headers=headers,
        )
        issues = _semantic_response_issues(
            renderer, response, model, forbidden_values=forbidden_values
        )
        _record(
            report,
            document.doc_id,
            f"cross-format-semantics:{state_name}:{renderer}",
            not issues,
            expected="actual download matches model without candidate leakage",
            actual="; ".join(issues) if issues else "matched",
            metric=_SEMANTIC_METRIC,
        )


def _candidate_specs(
    manifest: dict[str, Any],
) -> tuple[tuple[dict[str, Any], str] | None, tuple[dict[str, Any], str] | None]:
    driver_keys = {
        condition["field"]
        for field in manifest.get("fields", [])
        for condition in _conditions(field.get("required_when"))
        if isinstance(condition.get("field"), str)
    }
    candidate_fields = [
        field
        for field in manifest.get("fields", [])
        if field.get("required") is not True
        and field.get("required_when") is None
        and field.get("key") not in driver_keys
        and field.get("type") in {"string", "text"}
        and not (field.get("enum") or field.get("options"))
    ]
    return (
        _candidate_spec(manifest, candidate_fields[0], "conflict")
        if candidate_fields
        else None,
        _candidate_spec(manifest, candidate_fields[0], "pending")
        if candidate_fields
        else None,
    )


def _candidate_spec(
    manifest: dict[str, Any], field: dict[str, Any], state_name: str
) -> tuple[dict[str, Any], str]:
    digest = hashlib.sha256(
        f"{manifest.get('doc_id')}::{field['key']}::{state_name}".encode()
    ).hexdigest()[:12]
    return field, f"PL24候选-{digest}"


def _conditions(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    values = raw if isinstance(raw, list) else [raw]
    return [value for value in values if isinstance(value, dict)]


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
        if expected not in normalized_text:
            issues.append(f"rendered block missing: {block.section}:{block.order}")
            continue
        # PDF extractors may emit short table headers before their visual row.
        # Keep presence checks for those labels, but order only substantive text.
        if len(expected) < 8:
            continue
        position = normalized_text.find(expected, cursor)
        if position < 0:
            issues.append(
                f"rendered block out of order: {block.section}:{block.order}"
            )
            continue
        cursor = position + len(expected)
    authoritative_text = _normalize_output_text(
        "\n".join(
            [
                model.title,
                model.disclaimer,
                *(field.value or "" for field in model.fields),
                *(block.text for block in model.blocks),
            ]
        )
    )
    for value in forbidden_values:
        normalized_value = _normalize_output_text(value)
        if normalized_value in authoritative_text:
            continue
        if normalized_value in normalized_text:
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
    positive, negatives = _condition_group_witnesses(manifest, conditions)
    if failing_index is None:
        return positive
    try:
        driver_key = conditions[failing_index]["field"]
    except (IndexError, KeyError, TypeError) as exc:
        raise CorpusValidationError(
            "condition_witness_unavailable", "Invalid failing condition index."
        ) from exc
    negative = negatives.get(driver_key)
    if negative is None:
        raise CorpusValidationError(
            "condition_witness_unavailable",
            "No negative group witness exists for "
            f"{manifest.get('doc_id')}:{driver_key}.",
        )
    return negative


def _condition_group_witnesses(
    manifest: dict[str, Any],
    conditions: list[dict[str, Any]],
) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    fields = {
        field["key"]: field
        for field in manifest.get("fields", [])
        if isinstance(field, dict) and isinstance(field.get("key"), str)
    }
    grouped: dict[str, list[dict[str, Any]]] = {}
    for condition in conditions:
        key = condition.get("field")
        if not isinstance(key, str) or key not in fields:
            raise CorpusValidationError(
                "unknown_condition_field",
                f"Condition references unknown field {key!r}.",
            )
        grouped.setdefault(key, []).append(condition)

    positive: dict[str, str] = {}
    group_negatives: dict[str, str] = {}
    for key, group_conditions in grouped.items():
        field = fields[key]
        candidates = _valid_value_candidates(field, group_conditions)
        positive_value = next(
            (
                candidate
                for candidate in candidates
                if all(
                    _condition_matches_value(condition, candidate)
                    for condition in group_conditions
                )
            ),
            None,
        )
        if positive_value is None:
            raise CorpusValidationError(
                "condition_witness_unavailable",
                "No positive condition witness exists for "
                f"{manifest.get('doc_id')}:{key}.",
            )
        positive[key] = positive_value
        negative_value = next(
            (
                candidate
                for candidate in candidates
                if not all(
                    _condition_matches_value(condition, candidate)
                    for condition in group_conditions
                )
            ),
            None,
        )
        if negative_value is not None:
            group_negatives[key] = negative_value

    negatives = {
        key: {**positive, key: value}
        for key, value in group_negatives.items()
    }
    return positive, negatives


def _record_condition_assignment(
    report: QualityReport,
    document: CorpusDocument,
    manifest: dict[str, Any],
    case_id: str,
    values: dict[str, str],
    *,
    metric: str,
    expected_unresolved: str | None = None,
) -> DraftStateSnapshot:
    snapshot = _confirm_values(
        _fresh_snapshot(document.doc_id, manifest), manifest, values
    )
    _record_condition_snapshot(
        report,
        document,
        manifest,
        case_id,
        snapshot,
        metric=metric,
        expected_unresolved=expected_unresolved,
    )
    return snapshot


def _record_condition_snapshot(
    report: QualityReport,
    document: CorpusDocument,
    manifest: dict[str, Any],
    case_id: str,
    snapshot: DraftStateSnapshot,
    *,
    metric: str,
    expected_unresolved: str | None = None,
    expected_resolved: str | None = None,
) -> None:
    values = {
        key: field.value.strip()
        for key, field in snapshot.fields.items()
        if isinstance(field.value, str)
        and field.value.strip()
        and (
            field.status == "confirmed"
            or (field.status == "conflict" and field.confirmed_at is not None)
        )
    }
    expected_active = _oracle_conditional_required_keys(manifest, values)
    conditional_keys = {
        field["key"]
        for field in manifest["fields"]
        if field.get("required_when") is not None
    }
    actual_active = set(required_field_keys(manifest, snapshot)) & conditional_keys
    unresolved = set(unresolved_required_field_keys(manifest, snapshot))
    passed = actual_active == expected_active
    if expected_unresolved is not None:
        passed = passed and expected_unresolved in unresolved
    if expected_resolved is not None:
        passed = passed and expected_resolved not in unresolved
    _record(
        report,
        document.doc_id,
        case_id,
        passed,
        field_key=expected_unresolved or expected_resolved,
        expected=(
            f"active={sorted(expected_active)!r}, "
            f"unresolved={expected_unresolved!r}, resolved={expected_resolved!r}"
        ),
        actual=f"active={sorted(actual_active)!r}, unresolved={sorted(unresolved)!r}",
        metric=metric,
    )


def _oracle_conditional_required_keys(
    manifest: dict[str, Any], values: dict[str, str]
) -> set[str]:
    active: set[str] = set()
    for field in manifest.get("fields", []):
        raw = field.get("required_when")
        if raw is None:
            continue
        conditions = raw if isinstance(raw, list) else [raw]
        if all(
            isinstance(condition, dict)
            and isinstance(values.get(condition.get("field")), str)
            and _condition_matches_value(
                condition, values[condition["field"]]
            )
            for condition in conditions
        ):
            active.add(field["key"])
    return active


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
    case_kind = _ACTIVE_CASE_KIND.get()
    coverage_key = None
    if case_kind is not None:
        scenario, renderer = _split_renderer(case_id)
        coverage_key = CoverageExpectation(
            doc_id=doc_id,
            case_kind=case_kind,
            scenario=scenario,
            renderer=renderer,
        ).key
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
            coverage_key=coverage_key,
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
