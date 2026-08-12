"""Stable, secret-free report model for live LLM evaluation runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class AssertionResult:
    name: str
    passed: bool
    detail: str | None = None


@dataclass(frozen=True)
class LiveCaseResult:
    case_id: str
    category: str
    doc_id: str
    status: str
    latency_ms: int
    http_status: int | None
    calls: int
    retries: int
    product_followup_calls: int = 0
    local_followup_fallback_used: bool = False
    assertions: tuple[AssertionResult, ...] = ()
    token_usage: dict[str, int] = field(default_factory=dict)
    estimated_cost_usd: float | None = None
    reported_cost_usd: float | None = None
    error_class: str | None = None


@dataclass
class LiveEvalReport:
    corpus_version: str
    run_id: str
    started_at: str
    git_sha: str
    dirty_worktree: bool
    model: str
    provider: str
    live: bool
    mode: str
    max_calls: int
    max_retries: int
    api_key_present: bool
    selected_case_ids: tuple[str, ...]
    judge_enabled: bool = False
    judge_rubric_version: str | None = None
    judge_results: list[dict[str, Any]] = field(default_factory=list)
    schema_version: int = 1
    finished_at: str | None = None
    actual_calls: int = 0
    retry_count: int = 0
    product_followup_calls: int = 0
    local_followup_fallback_count: int = 0
    token_usage: dict[str, int] = field(default_factory=dict)
    estimated_cost_usd: float | None = None
    reported_cost_usd: float | None = None
    incomplete: bool = False
    results: list[LiveCaseResult] = field(default_factory=list)

    @classmethod
    def start(
        cls,
        *,
        corpus_version: str,
        git_sha: str,
        dirty_worktree: bool,
        mode: str,
        max_calls: int,
        max_retries: int,
        api_key_present: bool,
        selected_case_ids: tuple[str, ...],
    ) -> LiveEvalReport:
        return cls(
            corpus_version=corpus_version,
            run_id=uuid4().hex,
            started_at=_timestamp(),
            git_sha=git_sha,
            dirty_worktree=dirty_worktree,
            model="openrouter/openai/gpt-oss-120b",
            provider="cerebras",
            live=True,
            mode=mode,
            max_calls=max_calls,
            max_retries=max_retries,
            api_key_present=api_key_present,
            selected_case_ids=selected_case_ids,
        )

    def finish(self) -> None:
        self.finished_at = _timestamp()

    @property
    def case_totals(self) -> dict[str, int]:
        totals = {
            "total": len(self.results),
            "pass": 0,
            "fail": 0,
            "error": 0,
            "skipped": 0,
        }
        for result in self.results:
            if result.status in totals:
                totals[result.status] += 1
        return totals

    def category_totals(self) -> dict[str, dict[str, int]]:
        return _group_totals(self.results, "category")

    def document_totals(self) -> dict[str, dict[str, int]]:
        return _group_totals(self.results, "doc_id")

    @property
    def invariant_errors(self) -> list[str]:
        errors: list[str] = []
        totals = self.case_totals
        allowed_statuses = {"pass", "fail", "error", "skipped"}
        result_ids = [result.case_id for result in self.results]
        if any(result.status not in allowed_statuses for result in self.results):
            errors.append("invalid_result_status")
        if len(self.results) != len(self.selected_case_ids):
            errors.append("selected_case_count_mismatch")
        if len(result_ids) != len(set(result_ids)):
            errors.append("duplicate_result_case_id")
        if sorted(result_ids) != sorted(self.selected_case_ids):
            errors.append("selected_case_result_mismatch")
        if totals["total"] != sum(
            totals[key] for key in ("pass", "fail", "error", "skipped")
        ):
            errors.append("case_totals_mismatch")
        if self.actual_calls > self.max_calls:
            errors.append("call_budget_exceeded")
        if self.retry_count > self.max_retries:
            errors.append("retry_budget_exceeded")
        if self.retry_count != sum(result.retries for result in self.results):
            errors.append("retry_total_mismatch")
        if self.product_followup_calls != sum(
            result.product_followup_calls for result in self.results
        ):
            errors.append("product_followup_total_mismatch")
        if self.local_followup_fallback_count != sum(
            result.local_followup_fallback_used for result in self.results
        ):
            errors.append("followup_fallback_total_mismatch")
        if any(
            result.retries + result.product_followup_calls > result.calls
            for result in self.results
        ):
            errors.append("call_classification_invalid")
        if any(
            result.error_class == "local_chat_rate_limit"
            and result.status != "error"
            for result in self.results
        ):
            errors.append("local_rate_limit_misclassified")
        if any(
            result.error_class == "local_chat_rate_limit" for result in self.results
        ) and not self.incomplete:
            errors.append("local_rate_limit_not_incomplete")
        if self.finished_at is None:
            errors.append("run_not_finished")
        if not self.results:
            errors.append("case_totals_mismatch")
        return sorted(set(errors))

    @property
    def exit_code(self) -> int:
        if self.invariant_errors:
            return 1
        if self.incomplete:
            return 3
        if self.case_totals["fail"] or self.case_totals["error"]:
            return 1
        return 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "corpus_version": self.corpus_version,
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "git_sha": self.git_sha,
            "dirty_worktree": self.dirty_worktree,
            "model": self.model,
            "provider": self.provider,
            "live": self.live,
            "mode": self.mode,
            "max_calls": self.max_calls,
            "actual_calls": self.actual_calls,
            "actual_calls_definition": (
                "outer_litellm_completion_attempts_sdk_retries_disabled"
            ),
            "retry_count": self.retry_count,
            "product_followup_calls": self.product_followup_calls,
            "local_followup_fallback_count": self.local_followup_fallback_count,
            "max_retries": self.max_retries,
            "token_usage": dict(self.token_usage),
            "estimated_cost_usd": self.estimated_cost_usd,
            "reported_cost_usd": self.reported_cost_usd,
            "api_key_present": self.api_key_present,
            "selected_case_ids": list(self.selected_case_ids),
            "judge_enabled": self.judge_enabled,
            "judge_rubric_version": self.judge_rubric_version,
            "judge_results": list(self.judge_results),
            "incomplete": self.incomplete,
            "invariant_errors": self.invariant_errors,
            "case_totals": self.case_totals,
            "category_totals": self.category_totals(),
            "documents": self.document_totals(),
            "results": [asdict(result) for result in self.results],
        }


def _group_totals(
    results: list[LiveCaseResult], attribute: str
) -> dict[str, dict[str, int]]:
    grouped: dict[str, dict[str, int]] = {}
    for result in results:
        name = getattr(result, attribute)
        totals = grouped.setdefault(
            name,
            {"total": 0, "pass": 0, "fail": 0, "error": 0, "skipped": 0},
        )
        totals["total"] += 1
        if result.status in totals:
            totals[result.status] += 1
    return dict(sorted(grouped.items()))


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
