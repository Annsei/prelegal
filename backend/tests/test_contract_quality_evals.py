"""Self-tests and the hard gate for the deterministic quality corpus."""

from __future__ import annotations

import copy
import json
import socket
import sys
from io import BytesIO
from types import SimpleNamespace

import pytest
from docx import Document

import quality_evals.__main__ as quality_cli
import quality_evals.runner as quality_runner
from app.draft_state import snapshot_from_document_state
from app.export import build_export_document, render_docx, render_pdf
from app.manifests import load_manifest
from quality_evals.corpus import (
    CorpusDocument,
    CorpusValidationError,
    load_corpus,
    validate_corpus,
)
from quality_evals.report import (
    HARD_GATE_METRICS,
    METRIC_NAMES,
    QualityCaseResult,
    QualityReport,
)
from quality_evals.runner import run_contract_quality_evaluation


def test_quality_corpus_discovers_every_catalog_manifest():
    corpus = load_corpus()

    validated = validate_corpus(corpus)

    assert len(validated.documents) == 11
    assert validated.catalog_doc_ids == validated.manifest_doc_ids
    assert validated.catalog_doc_ids == validated.corpus_doc_ids


def test_quality_corpus_rejects_catalog_manifest_or_corpus_drift():
    corpus = load_corpus()

    with _raises_corpus_error("catalog_manifest_mismatch"):
        validate_corpus(corpus, catalog_doc_ids={*corpus.doc_ids, "new-document"})

    missing_document = copy.deepcopy(corpus.raw)
    missing_document["documents"] = missing_document["documents"][:-1]
    with _raises_corpus_error("catalog_corpus_mismatch"):
        validate_corpus(missing_document)


def test_quality_corpus_rejects_duplicate_case_ids_and_unknown_fields():
    corpus = load_corpus()
    duplicate = copy.deepcopy(corpus.raw)
    duplicate["cases"].append(copy.deepcopy(duplicate["cases"][0]))
    with _raises_corpus_error("duplicate_case_id"):
        validate_corpus(duplicate)

    unknown_field = copy.deepcopy(corpus.raw)
    unknown_field["documents"][0]["anchor_field"] = "不存在字段"
    with _raises_corpus_error("unknown_corpus_field"):
        validate_corpus(unknown_field)


def test_quality_corpus_rejects_missing_case_suite():
    corpus = load_corpus()
    incomplete = copy.deepcopy(corpus.raw)
    incomplete["cases"] = incomplete["cases"][:-1]

    with _raises_corpus_error("case_coverage_mismatch"):
        validate_corpus(incomplete)


def test_quality_corpus_requires_both_renderers():
    corpus = load_corpus()
    missing_pdf = copy.deepcopy(corpus.raw)
    missing_pdf["renderers"] = ["docx"]

    with _raises_corpus_error("renderer_coverage_missing"):
        validate_corpus(missing_pdf)


@pytest.mark.parametrize(
    ("raw", "kind"),
    [
        ([], "invalid_corpus"),
        (None, "invalid_corpus"),
        ("not-an-object", "invalid_corpus"),
        ({"schema_version": True}, "unsupported_corpus_schema"),
        (
            {
                "schema_version": 1,
                "renderers": ["docx", "pdf"],
                "cases": [{"id": [], "kind": "complete_state"}],
                "documents": [],
            },
            "invalid_corpus",
        ),
        (
            {
                "schema_version": 1,
                "renderers": ["docx", "pdf"],
                "cases": [{"id": "complete", "kind": {}}],
                "documents": [],
            },
            "invalid_corpus",
        ),
        (
            {
                "schema_version": 1,
                "renderers": ["docx", "pdf"],
                "cases": [],
                "documents": [{"doc_id": [], "anchor_field": "字段"}],
            },
            "invalid_corpus",
        ),
        (
            {
                "schema_version": 1,
                "renderers": ["docx", "pdf"],
                "cases": [],
                "documents": [{"doc_id": "doc", "anchor_field": {}}],
            },
            "invalid_corpus",
        ),
        (
            {
                "schema_version": 1,
                "renderers": ["docx", 1],
                "cases": [],
                "documents": [],
            },
            "invalid_corpus",
        ),
    ],
)
def test_quality_corpus_rejects_malformed_shapes(raw, kind: str):
    with _raises_corpus_error(kind):
        validate_corpus(raw)


def test_quality_corpus_honors_explicit_empty_document_sets():
    with _raises_corpus_error("catalog_corpus_mismatch"):
        validate_corpus(
            load_corpus(),
            catalog_doc_ids=set(),
            manifest_doc_ids=set(),
        )


def test_condition_evaluator_exercises_required_when_arrays_as_conjunctions():
    manifest = {
        "doc_id": "synthetic-conjunction",
        "version": 1,
        "fields": [
            {
                "key": "模式",
                "type": "string",
                "enum": ["付费", "免费"],
                "required": False,
            },
            {
                "key": "地区",
                "type": "string",
                "options": ["境内", "境外"],
                "required": False,
            },
            {
                "key": "日期",
                "type": "date",
                "required": False,
            },
            {
                "key": "付款安排",
                "type": "text",
                "required": False,
                "required_when": [
                    {"field": "模式", "op": "equals", "value": "付费"},
                    {"field": "地区", "op": "in", "values": ["境内"]},
                    {
                        "field": "日期",
                        "op": "not_equals",
                        "value": "2026-01-16",
                    },
                ],
            },
        ],
    }
    report = QualityReport.empty(expected_doc_ids={manifest["doc_id"]})

    quality_runner._evaluate_conditions(
        report,
        CorpusDocument(doc_id=manifest["doc_id"], anchor_field="模式"),
        manifest,
    )

    assert report.failed_cases == 0, report.failure_summary()


def test_condition_evaluator_rejects_impossible_conjunction_witnesses():
    manifest = {
        "doc_id": "impossible-conjunction",
        "version": 1,
        "fields": [
            {
                "key": "模式",
                "type": "string",
                "enum": ["甲", "乙"],
                "required": False,
            },
            {
                "key": "结果",
                "type": "string",
                "required": False,
                "required_when": [
                    {"field": "模式", "op": "equals", "value": "甲"},
                    {"field": "模式", "op": "equals", "value": "乙"},
                ],
            },
        ],
    }

    with _raises_corpus_error("condition_witness_unavailable"):
        quality_runner._evaluate_conditions(
            QualityReport.empty(expected_doc_ids={manifest["doc_id"]}),
            CorpusDocument(doc_id=manifest["doc_id"], anchor_field="模式"),
            manifest,
        )


def test_hard_gate_report_exits_nonzero_for_any_gated_metric():
    for metric in HARD_GATE_METRICS:
        report = QualityReport.empty()
        report.metrics[metric] = 1
        assert report.exit_code == 1


def test_report_hard_gate_enforces_denominators_schema_coverage_and_metric_shape():
    report = QualityReport.empty(expected_doc_ids={"expected-doc"})
    assert report.exit_code == 1
    assert "zero_metric_denominator" in report.invariant_errors
    assert "document_coverage_incomplete" in report.invariant_errors

    for metric in METRIC_NAMES:
        report.add(
            QualityCaseResult(
                doc_id="expected-doc",
                case_id=f"case-{metric}",
                passed=True,
                metric=metric,
            )
        )
    assert report.exit_code == 0

    report.schema_version = 2
    assert report.exit_code == 1
    assert "unsupported_report_schema" in report.invariant_errors

    report.schema_version = 1
    report.metrics["unregistered_metric"] = 0
    assert report.exit_code == 1
    assert "metric_shape_mismatch" in report.invariant_errors


def test_quality_command_returns_nonzero_when_a_hard_gate_triggers(monkeypatch):
    report = QualityReport.empty()
    report.metrics[HARD_GATE_METRICS[0]] = 1
    monkeypatch.setattr(quality_cli, "run_contract_quality_evaluation", lambda: report)
    monkeypatch.setattr(sys, "argv", ["quality-evals"])

    assert quality_cli.main() == 1


def test_quality_json_command_returns_nonzero_for_serialization_failure(
    monkeypatch,
    capsys,
):
    report = QualityReport.empty()
    monkeypatch.setattr(report, "to_dict", lambda: {"bad": object()})
    monkeypatch.setattr(quality_cli, "run_contract_quality_evaluation", lambda: report)
    monkeypatch.setattr(sys, "argv", ["quality-evals", "--json"])

    assert quality_cli.main() == 1
    assert "report_serialization_failed" in capsys.readouterr().err


def test_quality_command_returns_stable_corpus_failure(monkeypatch, capsys):
    def fail_corpus():
        raise CorpusValidationError("synthetic_corpus_failure", "bad corpus")

    monkeypatch.setattr(quality_cli, "run_contract_quality_evaluation", fail_corpus)
    monkeypatch.setattr(sys, "argv", ["quality-evals", "--json"])

    assert quality_cli.main() == 1
    stderr = capsys.readouterr().err
    assert "corpus_validation_failed:synthetic_corpus_failure" in stderr


@pytest.mark.parametrize("status_code", [422, 500])
def test_invalid_download_conflict_setup_failure_is_a_hard_failure(
    monkeypatch,
    status_code: int,
):
    original_patch = quality_runner._api_patch

    def fail_conflict_patch(*args, **kwargs):
        if "download-conflict" in kwargs.get("patch_id", ""):
            return SimpleNamespace(
                status_code=status_code,
                text="injected conflict setup failure",
                json=lambda: {},
            )
        return original_patch(*args, **kwargs)

    monkeypatch.setattr(quality_runner, "_api_patch", fail_conflict_patch)
    document = CorpusDocument(doc_id="mutual-nda", anchor_field="保密用途")
    manifest = load_manifest(document.doc_id)
    assert manifest is not None
    report = QualityReport.empty(expected_doc_ids={document.doc_id})

    with quality_runner._evaluation_client() as (client, get_conn):
        headers = quality_runner._register(client)
        quality_runner._evaluate_invalid_downloads(
            report,
            client,
            get_conn,
            headers,
            document,
            manifest,
        )

    failures = [result for result in report.results if not result.passed]
    assert any(
        result.case_id == "invalid-downloads:conflict-setup"
        and f"HTTP {status_code}" in (result.actual or "")
        for result in failures
    )
    assert report.exit_code == 1
    assert "conflict-setup" in report.failure_summary()


def test_semantic_verifier_rejects_empty_wrong_and_corrupt_downloads():
    model, docx_payload, pdf_payload = _semantic_fixture()
    valid_headers = {
        "content-type": (
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        "content-disposition": "attachment; filename*=UTF-8''quality.docx",
    }

    assert quality_runner._semantic_response_issues(
        "docx",
        _download_response(docx_payload, valid_headers),
        model,
        forbidden_values=(),
    ) == []
    assert quality_runner._semantic_response_issues(
        "docx",
        _download_response(b"", valid_headers),
        model,
        forbidden_values=(),
    )
    assert quality_runner._semantic_response_issues(
        "docx",
        _download_response(pdf_payload, valid_headers),
        model,
        forbidden_values=(),
    )
    assert quality_runner._semantic_response_issues(
        "docx",
        _download_response(b"PKbroken", valid_headers),
        model,
        forbidden_values=(),
    )
    assert quality_runner._semantic_response_issues(
        "pdf",
        _download_response(
            b"%PDF-broken",
            {
                "content-type": "application/pdf",
                "content-disposition": "attachment; filename*=UTF-8''quality.pdf",
            },
        ),
        model,
        forbidden_values=(),
    )
    assert quality_runner._semantic_response_issues(
        "docx",
        _download_response(docx_payload, {}),
        model,
        forbidden_values=(),
    )


def test_semantic_verifier_requires_title_fields_terms_disclaimer_and_every_block():
    model, _docx_payload, _pdf_payload = _semantic_fixture()
    headers = {
        "content-type": (
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        "content-disposition": "attachment; filename*=UTF-8''quality.docx",
    }
    values = [field.value for field in model.fields if field.value]
    only_fields = _docx_with_lines([model.title, *values, model.disclaimer])
    only_fields_issues = quality_runner._semantic_response_issues(
        "docx",
        _download_response(only_fields, headers),
        model,
        forbidden_values=(),
    )
    assert any("standard terms" in issue for issue in only_fields_issues)

    omitted = next(block for block in model.blocks if block.section == "standard_terms")
    without_one_block = _docx_with_lines(
        [
            model.title,
            *values,
            *(block.text for block in model.blocks if block != omitted),
            model.disclaimer,
        ]
    )
    block_issues = quality_runner._semantic_response_issues(
        "docx",
        _download_response(without_one_block, headers),
        model,
        forbidden_values=(),
    )
    assert any("block" in issue for issue in block_issues)


def test_semantic_verifier_rejects_payload_from_the_wrong_snapshot():
    model, _docx_payload, _pdf_payload = _semantic_fixture(anchor_value="预期稳定值")
    wrong_model, wrong_payload, _pdf = _semantic_fixture(anchor_value="错误快照值")
    assert wrong_model != model
    issues = quality_runner._semantic_response_issues(
        "docx",
        _download_response(
            wrong_payload,
            {
                "content-type": (
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                "content-disposition": "attachment; filename*=UTF-8''quality.docx",
            },
        ),
        model,
        forbidden_values=(),
    )
    assert any("field" in issue for issue in issues)


@pytest.mark.contract_quality_gate
def test_contract_quality_hard_gate_is_zero_and_report_is_serializable(monkeypatch):
    def reject_network(*_args, **_kwargs):
        raise AssertionError("deterministic evaluator attempted network access")

    # Other backend tests legitimately import the chat stack. Remove those
    # cached modules for this test so the evaluator must prove it does not load
    # the LLM path itself; monkeypatch restores the original entries afterward.
    for module_name in tuple(sys.modules):
        if module_name == "app.llm" or module_name.startswith("litellm"):
            monkeypatch.delitem(sys.modules, module_name)
    monkeypatch.setattr(socket.socket, "connect", reject_network)
    report = run_contract_quality_evaluation()

    assert report.failed_cases == 0, report.failure_summary()
    assert report.passed_cases == report.total_cases
    assert all(report.metrics[name] == 0 for name in HARD_GATE_METRICS)
    encoded = json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True)
    decoded = json.loads(encoded)
    assert decoded["schema_version"] == 1
    assert len(decoded["documents"]) == 11
    assert all(value > 0 for value in decoded["metric_denominators"].values())
    assert "app.llm" not in sys.modules
    assert "litellm" not in sys.modules


class _raises_corpus_error:
    def __init__(self, kind: str):
        self.kind = kind

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        assert exc_type is CorpusValidationError
        assert exc.kind == self.kind
        return True


def _semantic_fixture(anchor_value: str = "确定性稳定值"):
    manifest = load_manifest("mutual-nda")
    assert manifest is not None
    snapshot = snapshot_from_document_state(
        doc_id="mutual-nda",
        state={},
        manifest=manifest,
    )
    values = {
        field["key"]: (
            anchor_value
            if field["key"] == "保密用途"
            else quality_runner._valid_value(field)
        )
        for field in manifest["fields"]
    }
    snapshot = quality_runner._confirm_values(snapshot, manifest, values)
    model = build_export_document(
        doc_id="mutual-nda",
        title="确定性语义验证协议",
        manifest=manifest,
        snapshot=snapshot,
    )
    return model, render_docx(model), render_pdf(model)


def _download_response(payload: bytes, headers: dict[str, str]):
    return SimpleNamespace(status_code=200, content=payload, headers=headers)


def _docx_with_lines(lines: list[str]) -> bytes:
    document = Document()
    for line in lines:
        document.add_paragraph(line)
    output = BytesIO()
    document.save(output)
    return output.getvalue()
