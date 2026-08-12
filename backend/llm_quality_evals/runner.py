"""Live evaluator that drives the authenticated production chat route."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import unicodedata
from collections import deque
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app import llm
from app.db import reset_database
from app.main import create_app
from app.manifests import load_manifest, manifest_field_keys
from app.ratelimit import ALL_LIMITERS
from llm_quality_evals.corpus import LiveEvalCase, ValidatedLiveEvalCorpus
from llm_quality_evals.report import (
    AssertionResult,
    LiveCaseResult,
    LiveEvalReport,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_REQUIRED_RESPONSE_KEYS = {
    "assistant_message",
    "selected_doc_id",
    "mnda_updates",
    "field_updates",
    "done",
}
_QUESTION_MARKS = ("?", "？")
_SECRET_PATTERNS = (
    "OPENROUTER_API_KEY=",
    "Authorization: Bearer",
    "Bearer sk-",
)


class LiveEvalConfigurationError(RuntimeError):
    pass


class UpstreamRunIncomplete(RuntimeError):
    pass


class CallBudget:
    """Count outer provider attempts with LiteLLM transport retries disabled."""

    def __init__(self, max_calls: int):
        if type(max_calls) is not int or max_calls <= 0:
            raise LiveEvalConfigurationError("invalid_max_calls")
        self.max_calls = max_calls
        self.actual_calls = 0
        self.blocked_attempts = 0
        self.token_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        self.reported_cost_usd: float | None = None
        self._case_calls = 0

    def begin_case(self) -> None:
        self._case_calls = 0

    def wrap(self, completion: Callable[..., Any]) -> Callable[..., Any]:
        def bounded_completion(**kwargs: Any) -> Any:
            if self.actual_calls >= self.max_calls:
                self.blocked_attempts += 1
                raise LiveEvalConfigurationError("call_budget_exhausted")
            # The evaluator owns retries at a visible, run-wide layer. Disable
            # LiteLLM/OpenAI transport retries so one counted call is one
            # provider attempt rather than an unbounded SDK retry bundle.
            kwargs["max_retries"] = 0
            self.actual_calls += 1
            self._case_calls += 1
            response = completion(**kwargs)
            self._record_usage(response)
            return response

        return bounded_completion

    def _record_usage(self, response: Any) -> None:
        usage = getattr(response, "usage", None)
        for name in self.token_usage:
            value = _get_value(usage, name)
            if type(value) is int and value >= 0:
                self.token_usage[name] += value
        hidden = getattr(response, "_hidden_params", None)
        cost = _get_value(hidden, "response_cost")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost >= 0:
            self.reported_cost_usd = (self.reported_cost_usd or 0.0) + float(cost)


class RetryBudget:
    """Run-wide evaluator retry budget; product follow-ups are not retries."""

    def __init__(self, max_retries: int):
        if type(max_retries) is not int or max_retries < 0:
            raise LiveEvalConfigurationError("invalid_max_retries")
        self.max_retries = max_retries
        self.used = 0

    def consume(self) -> bool:
        if self.used >= self.max_retries:
            return False
        self.used += 1
        return True


class RequestPacer:
    """Serially respect the production chat limiter's 20-request window."""

    def __init__(
        self,
        *,
        max_requests: int = 20,
        window_seconds: float = 60.0,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.monotonic = monotonic
        self.sleeper = sleeper
        self._requests: deque[float] = deque()

    def wait(self) -> None:
        now = self.monotonic()
        self._expire(now)
        if len(self._requests) >= self.max_requests:
            delay = max(0.0, self._requests[0] + self.window_seconds - now)
            if delay:
                self.sleeper(delay)
            now = self.monotonic()
            self._expire(now)
        self._requests.append(now)

    def _expire(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._requests and self._requests[0] <= cutoff:
            self._requests.popleft()


class FollowupFallbackObserver:
    """Observe the product's local fallback without changing its output."""

    def __init__(self, fallback: Callable[[str], str]):
        self.fallback = fallback
        self.count = 0

    def __call__(self, message: str) -> str:
        self.count += 1
        return self.fallback(message)


def select_cases(
    corpus: ValidatedLiveEvalCorpus,
    *,
    smoke: bool,
    case_ids: set[str],
    categories: set[str],
    doc_ids: set[str],
) -> tuple[LiveEvalCase, ...]:
    selected = corpus.smoke_cases if smoke else corpus.cases
    if case_ids:
        selected = tuple(case for case in selected if case.id in case_ids)
        missing = case_ids - {case.id for case in corpus.cases}
        if missing:
            raise LiveEvalConfigurationError(f"unknown_case:{sorted(missing)}")
    if categories:
        selected = tuple(case for case in selected if case.category in categories)
        missing = categories - corpus.categories
        if missing:
            raise LiveEvalConfigurationError(f"unknown_category:{sorted(missing)}")
    if doc_ids:
        selected = tuple(case for case in selected if case.doc_id in doc_ids)
        missing = doc_ids - set(corpus.catalog_doc_ids)
        if missing:
            raise LiveEvalConfigurationError(f"unknown_doc:{sorted(missing)}")
    if not selected:
        raise LiveEvalConfigurationError("no_cases_selected")
    return selected


def run_live_evaluation(
    *,
    corpus: ValidatedLiveEvalCorpus,
    cases: Iterable[LiveEvalCase],
    max_calls: int,
    max_retries: int,
    mode: str,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> LiveEvalReport:
    selected = tuple(cases)
    if not selected:
        raise LiveEvalConfigurationError("no_cases_selected")
    if len(selected) > max_calls:
        raise LiveEvalConfigurationError(
            f"minimum_call_budget_too_small:selected={len(selected)} max={max_calls}"
        )
    if llm.MODEL != "openrouter/openai/gpt-oss-120b":
        raise LiveEvalConfigurationError("unexpected_model")
    if llm.PROVIDER_ROUTING != {"order": ["cerebras"], "allow_fallbacks": False}:
        raise LiveEvalConfigurationError("unexpected_provider_routing")
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise LiveEvalConfigurationError("api_key_missing")

    git_sha, dirty = _git_state()
    report = LiveEvalReport.start(
        corpus_version=corpus.corpus.corpus_version,
        git_sha=git_sha,
        dirty_worktree=dirty,
        mode=mode,
        max_calls=max_calls,
        max_retries=max_retries,
        api_key_present=True,
        selected_case_ids=tuple(case.id for case in selected),
    )
    budget = CallBudget(max_calls=max_calls)
    retry_budget = RetryBudget(max_retries=max_retries)
    pacer = RequestPacer(monotonic=monotonic, sleeper=sleeper)
    product_followup_calls = 0
    local_followup_fallback_count = 0
    original_completion = llm.litellm.completion
    original_followup_fallback = llm._ensure_followup
    fallback_observer = FollowupFallbackObserver(original_followup_fallback)
    llm.litellm.completion = budget.wrap(original_completion)
    llm._ensure_followup = fallback_observer
    try:
        with _authenticated_client() as (client, headers):
            for index, case in enumerate(selected):
                budget.begin_case()
                result = _run_case_with_retries(
                    client=client,
                    headers=headers,
                    case=case,
                    corpus=corpus,
                    budget=budget,
                    retry_budget=retry_budget,
                    pacer=pacer,
                    fallback_observer=fallback_observer,
                )
                report.results.append(result)
                product_followup_calls += result.product_followup_calls
                local_followup_fallback_count += int(
                    result.local_followup_fallback_used
                )
                if result.status == "error":
                    report.incomplete = True
                    for skipped in selected[index + 1 :]:
                        report.results.append(
                            LiveCaseResult(
                                case_id=skipped.id,
                                category=skipped.category,
                                doc_id=skipped.doc_id,
                                status="skipped",
                                latency_ms=0,
                                http_status=None,
                                calls=0,
                                retries=0,
                                error_class="prior_upstream_error",
                            )
                        )
                    break
    finally:
        llm.litellm.completion = original_completion
        llm._ensure_followup = original_followup_fallback
        report.actual_calls = budget.actual_calls
        report.retry_count = retry_budget.used
        report.product_followup_calls = product_followup_calls
        report.local_followup_fallback_count = local_followup_fallback_count
        report.token_usage = dict(budget.token_usage)
        report.reported_cost_usd = budget.reported_cost_usd
        report.finish()
    return report


def _run_case_with_retries(
    *,
    client: TestClient,
    headers: dict[str, str],
    case: LiveEvalCase,
    corpus: ValidatedLiveEvalCorpus,
    budget: CallBudget,
    retry_budget: RetryBudget,
    pacer: RequestPacer,
    fallback_observer: FollowupFallbackObserver,
) -> LiveCaseResult:
    first_calls = budget.actual_calls
    first_usage = dict(budget.token_usage)
    first_cost = budget.reported_cost_usd
    first_blocked_attempts = budget.blocked_attempts
    first_fallbacks = fallback_observer.count
    started = time.perf_counter()
    response = None
    error_class: str | None = None
    evaluator_retries = 0
    product_followup_calls = 0
    while True:
        pacer.wait()
        calls_before_request = budget.actual_calls
        response = client.post(
            "/api/chat",
            headers=headers,
            json=_request_payload(case),
        )
        request_calls = budget.actual_calls - calls_before_request
        product_followup_calls += max(0, request_calls - 1)
        if response.status_code != 502:
            break
        error_class = _classify_error_response(response)
        if budget.blocked_attempts > first_blocked_attempts:
            error_class = "call_budget_exhausted"
        if error_class in {"upstream_rate_limit", "call_budget_exhausted"}:
            break
        if not retry_budget.consume():
            break
        evaluator_retries += 1
    latency_ms = max(0, round((time.perf_counter() - started) * 1000))
    calls = budget.actual_calls - first_calls
    if response is None:
        raise AssertionError("response loop did not execute")
    case_usage = {
        name: budget.token_usage[name] - first_usage[name]
        for name in budget.token_usage
    }
    case_cost = _cost_delta(budget.reported_cost_usd, first_cost)
    local_fallback_used = fallback_observer.count > first_fallbacks
    if response.status_code == 429:
        return LiveCaseResult(
            case_id=case.id,
            category=case.category,
            doc_id=case.doc_id,
            status="error",
            latency_ms=latency_ms,
            http_status=429,
            calls=calls,
            retries=evaluator_retries,
            product_followup_calls=product_followup_calls,
            local_followup_fallback_used=local_fallback_used,
            token_usage=case_usage,
            reported_cost_usd=case_cost,
            error_class="local_chat_rate_limit",
        )
    if response.status_code == 502:
        return LiveCaseResult(
            case_id=case.id,
            category=case.category,
            doc_id=case.doc_id,
            status="error",
            latency_ms=latency_ms,
            http_status=502,
            calls=calls,
            retries=evaluator_retries,
            product_followup_calls=product_followup_calls,
            local_followup_fallback_used=local_fallback_used,
            token_usage=case_usage,
            reported_cost_usd=case_cost,
            error_class=error_class or "upstream_unavailable",
        )

    try:
        body = response.json()
    except (json.JSONDecodeError, TypeError):
        body = None
    assertions = _evaluate_response(
        case=case,
        body=body,
        status_code=response.status_code,
        catalog_doc_ids=set(corpus.catalog_doc_ids),
    )
    status = (
        "pass" if assertions and all(item.passed for item in assertions) else "fail"
    )
    return LiveCaseResult(
        case_id=case.id,
        category=case.category,
        doc_id=case.doc_id,
        status=status,
        latency_ms=latency_ms,
        http_status=response.status_code,
        calls=calls,
        retries=evaluator_retries,
        product_followup_calls=product_followup_calls,
        local_followup_fallback_used=local_fallback_used,
        assertions=tuple(assertions),
        token_usage=case_usage,
        reported_cost_usd=case_cost,
    )


def _request_payload(case: LiveEvalCase) -> dict[str, Any]:
    open_doc_id = "" if case.category == "catalog_routing" else case.doc_id
    if case.document_state is not None:
        document_state = case.document_state
    elif case.state_fixture == "required_complete":
        document_state = {
            "doc_id": case.doc_id,
            "fields": _all_manifest_values(case.doc_id),
        }
    else:
        document_state = {"doc_id": open_doc_id, "fields": {}}
    return {
        "messages": list(case.messages),
        "mnda_state": {},
        "doc_id": open_doc_id,
        "document_state": document_state,
    }


def _evaluate_response(
    *,
    case: LiveEvalCase,
    body: Any,
    status_code: int,
    catalog_doc_ids: set[str],
) -> list[AssertionResult]:
    assertions = [
        AssertionResult("http_200", status_code == 200, f"status={status_code}"),
        AssertionResult(
            "response_schema",
            isinstance(body, dict) and set(body) == _REQUIRED_RESPONSE_KEYS,
            "exact_response_keys_required",
        ),
    ]
    if not isinstance(body, dict):
        return assertions
    message = body.get("assistant_message")
    selected_doc_id = body.get("selected_doc_id")
    fields = body.get("field_updates")
    expectations = case.expectations

    if expectations.get("selected_doc_must_exist"):
        assertions.append(
            AssertionResult(
                "selected_doc_must_exist",
                selected_doc_id in catalog_doc_ids,
                "selected_doc_id_not_in_catalog"
                if selected_doc_id not in catalog_doc_ids
                else None,
            )
        )
    expected_ids = expectations.get("selected_doc_ids")
    if expected_ids:
        assertions.append(
            AssertionResult(
                "selected_doc_ids",
                selected_doc_id in expected_ids,
                "selected_doc_id_mismatch"
                if selected_doc_id not in expected_ids
                else None,
            )
        )
    if expectations.get("field_keys_manifest_only"):
        allowed = set(manifest_field_keys(load_manifest(case.doc_id)))
        actual = set(fields) if isinstance(fields, dict) else set()
        manifest_only = isinstance(fields, dict) and actual <= allowed
        assertions.append(
            AssertionResult(
                "field_keys_manifest_only",
                manifest_only,
                "manifest_key_violation" if not manifest_only else None,
            )
        )
    forbidden_fields = set(expectations.get("forbidden_field_keys", []))
    if forbidden_fields:
        actual = set(fields) if isinstance(fields, dict) else set()
        assertions.append(
            AssertionResult(
                "forbidden_field_keys",
                not bool(actual & forbidden_fields),
                "forbidden_field_present" if actual & forbidden_fields else None,
            )
        )
    field_expectation = expectations.get("field_updates_expectation")
    if field_expectation is not None:
        matches, detail = _field_updates_match(fields, field_expectation)
        assertions.append(
            AssertionResult(
                "field_updates_expectation",
                matches,
                detail,
            )
        )
    if "done" in expectations:
        assertions.append(
            AssertionResult(
                "done",
                body.get("done") is expectations["done"],
                "done_mismatch"
                if body.get("done") is not expectations["done"]
                else None,
            )
        )
    if expectations.get("requires_question"):
        is_question = isinstance(message, str) and message.rstrip().endswith(
            _QUESTION_MARKS
        )
        assertions.append(
            AssertionResult(
                "requires_question",
                is_question,
                "assistant_did_not_end_with_question" if not is_question else None,
            )
        )
    if expectations.get("assistant_contains_cjk"):
        has_cjk = isinstance(message, str) and _contains_cjk(message)
        assertions.append(
            AssertionResult(
                "assistant_contains_cjk",
                has_cjk,
                "assistant_missing_cjk" if not has_cjk else None,
            )
        )
    forbidden_substrings = tuple(expectations.get("forbidden_substrings", []))
    if forbidden_substrings:
        encoded = _normalized_response(body)
        leaked = any(
            unicodedata.normalize("NFKC", value).casefold() in encoded
            for value in forbidden_substrings
        )
        assertions.append(
            AssertionResult(
                "forbidden_substrings",
                not leaked,
                "forbidden_substring_present" if leaked else None,
            )
        )
    if expectations.get("forbid_secret_patterns"):
        raw_encoded = json.dumps(body, ensure_ascii=False, sort_keys=True)
        encoded = unicodedata.normalize("NFKC", raw_encoded).casefold()
        leaked = any(
            unicodedata.normalize("NFKC", pattern).casefold() in encoded
            for pattern in _SECRET_PATTERNS
        )
        assertions.append(
            AssertionResult(
                "forbid_secret_patterns",
                not leaked,
                "secret_pattern_present" if leaked else None,
            )
        )
        api_key = os.environ.get("OPENROUTER_API_KEY")
        value_leaked = bool(api_key) and api_key in raw_encoded
        assertions.append(
            AssertionResult(
                "api_key_value_not_leaked",
                not value_leaked,
                "api_key_value_present" if value_leaked else None,
            )
        )
    return assertions


def _field_updates_match(
    actual: Any, expectation: dict[str, Any]
) -> tuple[bool, str | None]:
    if not isinstance(actual, dict):
        return False, "field_updates_not_object"
    if any(
        type(key) is not str or type(value) is not str
        for key, value in actual.items()
    ):
        return False, "field_updates_non_string_value"

    normalized_actual = {key: value.strip() for key, value in actual.items()}
    mode = expectation["mode"]
    if mode == "empty":
        matches = normalized_actual == {}
        return matches, None if matches else "field_updates_not_empty"

    normalized_expected = {
        key: value.strip() for key, value in expectation["values"].items()
    }
    if mode == "exact":
        matches = normalized_actual == normalized_expected
        return matches, None if matches else "field_updates_exact_mismatch"

    matches = all(
        normalized_actual.get(key) == value
        for key, value in normalized_expected.items()
    )
    return matches, None if matches else "field_updates_contains_mismatch"


def _normalized_response(body: dict[str, Any]) -> str:
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return unicodedata.normalize("NFKC", encoded).casefold()


@contextmanager
def _authenticated_client():
    old_db = os.environ.get("PRELEGAL_DB_PATH")
    with tempfile.TemporaryDirectory(prefix="prelegal-live-eval-") as directory:
        os.environ["PRELEGAL_DB_PATH"] = str(Path(directory) / "eval.sqlite")
        reset_database()
        for limiter in ALL_LIMITERS:
            limiter.reset()
        try:
            with TestClient(create_app()) as client:
                registration = client.post(
                    "/api/auth/register",
                    json={
                        "email": "pl24b-evaluator@example.com",
                        "password": "PL24B-synthetic-password",
                        "name": "PL-24B Evaluator",
                    },
                )
                if registration.status_code != 201:
                    raise LiveEvalConfigurationError("temporary_registration_failed")
                token = registration.json()["token"]
                yield client, {"Authorization": f"Bearer {token}"}
        finally:
            for limiter in ALL_LIMITERS:
                limiter.reset()
            if old_db is None:
                os.environ.pop("PRELEGAL_DB_PATH", None)
            else:
                os.environ["PRELEGAL_DB_PATH"] = old_db


def _all_manifest_values(doc_id: str) -> dict[str, str]:
    manifest = load_manifest(doc_id)
    if manifest is None:
        return {}
    values: dict[str, str] = {}
    for field in manifest.get("fields", []):
        key = field.get("key")
        if not isinstance(key, str):
            continue
        example = field.get("example")
        choices = field.get("enum") or field.get("options")
        if isinstance(example, str) and example.strip():
            values[key] = example
        elif isinstance(choices, list) and choices and isinstance(choices[0], str):
            values[key] = choices[0]
        elif field.get("type") == "date":
            values[key] = "2026-08-12"
        else:
            values[key] = "示例值"
    return values


def _classify_error_response(response: Any) -> str:
    try:
        detail = response.json().get("detail", "")
    except (AttributeError, json.JSONDecodeError, TypeError):
        detail = ""
    text = detail.casefold() if isinstance(detail, str) else ""
    if "unparseable" in text or "incomplete reply" in text:
        return "malformed_structured_response"
    if "rate-limit" in text or "429" in text:
        return "upstream_rate_limit"
    if "timed out" in text or "timeout" in text:
        return "upstream_timeout"
    if "api key" in text or "openrouter_api_key" in text:
        return "provider_authentication"
    if "call budget" in text or "retry budget" in text:
        return "call_budget_exhausted"
    return "upstream_unavailable"


def _git_state() -> tuple[str, bool]:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=_REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise LiveEvalConfigurationError("git_state_unavailable") from exc
    return sha, bool(status.strip())


def _contains_cjk(text: str) -> bool:
    return any("一" <= char <= "鿿" or "㐀" <= char <= "䶿" for char in text)


def _get_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _cost_delta(current: float | None, previous: float | None) -> float | None:
    if current is None:
        return None
    return current - (previous or 0.0)
