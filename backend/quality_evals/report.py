"""Stable result schema for local and CI contract-quality runs."""

from __future__ import annotations

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
    "successful_invalid_downloads",
    "cross_format_semantic_mismatch_count",
)


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


@dataclass
class QualityReport:
    schema_version: int = 1
    expected_doc_ids: set[str] | None = None
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
    ) -> QualityReport:
        return cls(expected_doc_ids=expected_doc_ids)

    def add(self, result: QualityCaseResult) -> None:
        self.results.append(result)
        if result.metric:
            self.metric_denominators[result.metric] += 1
            if result.metric_triggered:
                self.metrics[result.metric] += 1

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
        return errors

    def failure_summary(self) -> str:
        failures = [result for result in self.results if not result.passed]
        return "\n".join(
            f"{item.doc_id}:{item.case_id}:{item.field_key or '-'} "
            f"expected={item.expected!r} actual={item.actual!r}"
            for item in failures
        )

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
            "documents": self.document_summaries(),
            "results": [asdict(result) for result in self.results],
        }
