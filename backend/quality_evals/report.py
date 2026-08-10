"""Stable result schema for local and CI contract-quality runs."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

METRIC_NAMES = (
    "unknown_field_acceptance_count",
    "invalid_type_acceptance_count",
    "required_field_false_negative_count",
    "required_field_false_positive_count",
    "conflict_transition_failure_count",
    "successful_invalid_downloads",
    "cross_format_semantic_mismatch_count",
)
HARD_GATE_METRICS = (
    "unknown_field_acceptance_count",
    "invalid_type_acceptance_count",
    "required_field_false_negative_count",
    "required_field_false_positive_count",
    "conflict_transition_failure_count",
    "successful_invalid_downloads",
    "cross_format_semantic_mismatch_count",
)


@dataclass(frozen=True)
class CoverageExpectation:
    doc_id: str
    case_kind: str
    scenario: str
    renderer: str | None = None
    applicable: bool = True
    reason: str | None = None

    @property
    def key(self) -> str:
        return "::".join(
            (self.doc_id, self.case_kind, self.scenario, self.renderer or "-")
        )


@dataclass(frozen=True)
class CoverageRecord:
    key: str
    status: str
    reason: str | None = None


@dataclass(frozen=True)
class QualityCaseResult:
    doc_id: str
    case_id: str
    passed: bool
    field_key: str | None = None
    expected: str | None = None
    actual: str | None = None
    metric: str | None = None
    metric_triggered: bool = False
    coverage_key: str | None = None


@dataclass
class QualityReport:
    schema_version: int = 1
    expected_doc_ids: set[str] | None = None
    expected_coverage: tuple[CoverageExpectation, ...] = ()
    coverage_records: list[CoverageRecord] = field(default_factory=list)
    results: list[QualityCaseResult] = field(default_factory=list)
    metrics: dict[str, int] = field(
        default_factory=lambda: {name: 0 for name in METRIC_NAMES}
    )
    metric_denominators: dict[str, int] = field(
        default_factory=lambda: {name: 0 for name in METRIC_NAMES}
    )

    @classmethod
    def empty(
        cls,
        *,
        expected_doc_ids: set[str] | None = None,
        expected_coverage: tuple[CoverageExpectation, ...] = (),
    ) -> QualityReport:
        return cls(
            expected_doc_ids=expected_doc_ids,
            expected_coverage=expected_coverage,
        )

    def add(self, result: QualityCaseResult) -> None:
        self.results.append(result)
        if result.coverage_key:
            self.coverage_records.append(
                CoverageRecord(key=result.coverage_key, status="executed")
            )
        if result.metric:
            self.metric_denominators[result.metric] += 1
            if result.metric_triggered:
                self.metrics[result.metric] += 1

    def mark_not_applicable(self, expectation: CoverageExpectation) -> None:
        self.coverage_records.append(
            CoverageRecord(
                key=expectation.key,
                status="not_applicable",
                reason=expectation.reason,
            )
        )

    @property
    def total_cases(self) -> int:
        return len(self.results)

    @property
    def passed_cases(self) -> int:
        return sum(result.passed for result in self.results)

    @property
    def failed_cases(self) -> int:
        return self.total_cases - self.passed_cases

    @property
    def exit_code(self) -> int:
        if self.failed_cases or self.invariant_errors:
            return 1
        return int(any(self.metrics[name] for name in HARD_GATE_METRICS))

    @property
    def invariant_errors(self) -> list[str]:
        errors: list[str] = []
        if type(self.schema_version) is not int or self.schema_version != 1:
            errors.append("unsupported_report_schema")
        if set(self.metrics) != set(METRIC_NAMES) or set(
            self.metric_denominators
        ) != set(METRIC_NAMES):
            errors.append("metric_shape_mismatch")
        elif any(
            type(value) is not int or value <= 0
            for value in self.metric_denominators.values()
        ):
            errors.append("zero_metric_denominator")
        if self.expected_doc_ids is not None:
            actual_doc_ids = {result.doc_id for result in self.results}
            if actual_doc_ids != self.expected_doc_ids:
                errors.append("document_coverage_incomplete")
        expected_keys = [item.key for item in self.expected_coverage]
        expected_counts = Counter(expected_keys)
        actual_counts = Counter(item.key for item in self.coverage_records)
        if any(count > 1 for count in expected_counts.values()):
            errors.append("coverage_plan_duplicate_keys")
        if set(expected_keys) - set(actual_counts):
            errors.append("coverage_missing")
        if set(actual_counts) - set(expected_keys):
            errors.append("coverage_unexpected")
        if any(count > 1 for count in actual_counts.values()):
            errors.append("coverage_duplicate")
        expectations = {item.key: item for item in self.expected_coverage}
        for record in self.coverage_records:
            expectation = expectations.get(record.key)
            if expectation is None:
                continue
            expected_status = (
                "executed" if expectation.applicable else "not_applicable"
            )
            if record.status != expected_status:
                errors.append("coverage_applicability_mismatch")
                break
        return errors

    def failure_summary(self) -> str:
        failures = [result for result in self.results if not result.passed]
        lines = [
            f"{item.doc_id}:{item.case_id}:{item.field_key or '-'} "
            f"expected={item.expected!r} actual={item.actual!r}"
            for item in failures
        ]
        coverage = self.coverage_summary()
        for key in coverage["missing_coverage_keys"]:
            lines.append(f"coverage_missing:{key}")
        for key in coverage["unexpected_coverage_keys"]:
            lines.append(f"coverage_unexpected:{key}")
        for key in coverage["unexpected_duplicate_coverage_keys"]:
            lines.append(f"coverage_duplicate:{key}")
        for key in coverage["duplicate_expected_coverage_keys"]:
            lines.append(f"coverage_plan_duplicate:{key}")
        return "\n".join(lines)

    def document_summaries(self) -> dict[str, dict[str, int]]:
        summaries: dict[str, dict[str, int]] = {}
        for result in self.results:
            summary = summaries.setdefault(
                result.doc_id,
                {"total_cases": 0, "passed_cases": 0, "failed_cases": 0},
            )
            summary["total_cases"] += 1
            if result.passed:
                summary["passed_cases"] += 1
            else:
                summary["failed_cases"] += 1
        return dict(sorted(summaries.items()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "invariant_errors": self.invariant_errors,
            "total_cases": self.total_cases,
            "passed_cases": self.passed_cases,
            "failed_cases": self.failed_cases,
            "metrics": dict(self.metrics),
            "metric_denominators": dict(self.metric_denominators),
            "coverage": self.coverage_summary(),
            "documents": self.document_summaries(),
            "results": [asdict(result) for result in self.results],
        }

    def coverage_summary(self) -> dict[str, Any]:
        expected = {item.key: item for item in self.expected_coverage}
        actual_counts = Counter(item.key for item in self.coverage_records)
        actual_keys = set(actual_counts)
        expected_keys = set(expected)
        return {
            "expected_count": len(self.expected_coverage),
            "actual_count": len(self.coverage_records),
            "expected_unique_count": len(expected_keys),
            "actual_unique_count": len(actual_keys),
            "applicable_expected_count": sum(
                item.applicable for item in self.expected_coverage
            ),
            "not_applicable_expected_count": sum(
                not item.applicable for item in self.expected_coverage
            ),
            "missing_coverage_keys": sorted(expected_keys - actual_keys),
            "unexpected_coverage_keys": sorted(actual_keys - expected_keys),
            "unexpected_duplicate_coverage_keys": sorted(
                key for key, count in actual_counts.items() if count > 1
            ),
            "duplicate_expected_coverage_keys": sorted(
                key
                for key, count in Counter(
                    item.key for item in self.expected_coverage
                ).items()
                if count > 1
            ),
            "not_applicable": [
                {"key": item.key, "reason": item.reason}
                for item in self.expected_coverage
                if not item.applicable
            ],
            "records": [asdict(record) for record in self.coverage_records],
        }
