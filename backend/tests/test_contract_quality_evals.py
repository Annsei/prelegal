"""Self-tests and the hard gate for the deterministic quality corpus."""

from __future__ import annotations

import copy
import json
import os
import sys

import pytest

import quality_evals.__main__ as quality_cli
from quality_evals.corpus import (
    CorpusValidationError,
    load_corpus,
    validate_corpus,
)
from quality_evals.report import HARD_GATE_METRICS, QualityReport
from quality_evals.runner import run_contract_quality_evaluation


def test_quality_corpus_discovers_every_catalog_manifest():
    corpus = load_corpus()

    validated = validate_corpus(corpus)

    assert len(validated.documents) == 11
    assert validated.catalog_doc_ids == validated.manifest_doc_ids
    assert validated.catalog_doc_ids == validated.corpus_doc_ids


def test_quality_harness_forces_litellm_offline_cost_data():
    assert os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] == "True"


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


def test_hard_gate_report_exits_nonzero_for_any_gated_metric():
    for metric in HARD_GATE_METRICS:
        report = QualityReport.empty()
        report.metrics[metric] = 1
        assert report.exit_code == 1


def test_quality_command_returns_nonzero_when_a_hard_gate_triggers(monkeypatch):
    report = QualityReport.empty()
    report.metrics[HARD_GATE_METRICS[0]] = 1
    monkeypatch.setattr(quality_cli, "run_contract_quality_evaluation", lambda: report)
    monkeypatch.setattr(sys, "argv", ["quality-evals"])

    assert quality_cli.main() == 1


@pytest.mark.contract_quality_gate
def test_contract_quality_hard_gate_is_zero_and_report_is_serializable():
    report = run_contract_quality_evaluation()

    assert report.failed_cases == 0, report.failure_summary()
    assert report.passed_cases == report.total_cases
    assert all(report.metrics[name] == 0 for name in HARD_GATE_METRICS)
    encoded = json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True)
    decoded = json.loads(encoded)
    assert decoded["schema_version"] == 1
    assert len(decoded["documents"]) == 11
    assert all(value > 0 for value in decoded["metric_denominators"].values())


class _raises_corpus_error:
    def __init__(self, kind: str):
        self.kind = kind

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        assert exc_type is CorpusValidationError
        assert exc.kind == self.kind
        return True
