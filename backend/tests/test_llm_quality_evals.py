from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import llm, ratelimit
from llm_quality_evals.__main__ import main
from llm_quality_evals.corpus import (
    CorpusValidationError,
    load_corpus,
    parse_corpus,
    validate_corpus,
)
from llm_quality_evals.report import AssertionResult, LiveCaseResult, LiveEvalReport
from llm_quality_evals.runner import (
    CallBudget,
    LiveEvalConfigurationError,
    _evaluate_response,
    run_live_evaluation,
)

CATALOG_DOC_IDS = {
    "ai-addendum",
    "business-associate-agreement",
    "cloud-service-agreement",
    "data-processing-agreement",
    "design-partner-agreement",
    "mutual-nda",
    "partnership-agreement",
    "pilot-agreement",
    "professional-services-agreement",
    "service-level-agreement",
    "software-license-agreement",
}

CORPUS_PATH = Path(__file__).parents[1] / "llm_quality_evals" / "corpus.json"
_MISSING = object()


def _fake_response(payload: dict, *, prompt_tokens: int = 20, output_tokens: int = 8):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps(payload, ensure_ascii=False),
                ),
            ),
        ],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=output_tokens,
            total_tokens=prompt_tokens + output_tokens,
        ),
        _hidden_params={"response_cost": 0.001, "custom_llm_provider": "openrouter"},
    )


def _one_case_raw(**overrides):
    case = {
        "id": "routing.mnda",
        "category": "catalog_routing",
        "doc_id": "mutual-nda",
        "target_doc_id": "mutual-nda",
        "smoke": True,
        "messages": [{"role": "user", "content": "需要一份双方保密协议。"}],
        "state_fixture": "empty",
        "expectations": {
            "selected_doc_ids": ["mutual-nda"],
            "selected_doc_must_exist": True,
            "field_keys_manifest_only": True,
            "field_updates_expectation": {"mode": "empty"},
            "done": False,
            "requires_question": True,
            "assistant_contains_cjk": True,
            "forbid_secret_patterns": True,
        },
    }
    case.update(overrides)
    return {
        "schema_version": 1,
        "corpus_version": "test-1",
        "cases": [case],
    }


def _validated_single_case(**overrides):
    corpus = parse_corpus(_one_case_raw(**overrides))
    return validate_corpus(
        corpus,
        catalog_doc_ids=CATALOG_DOC_IDS,
        manifest_doc_ids=CATALOG_DOC_IDS,
        require_all_documents=False,
        require_all_categories=False,
        require_three_smoke_cases=False,
    )


def _passing_payload(case):
    expectations = case.expectations
    field_expectation = expectations.get("field_updates_expectation", {})
    return {
        "assistant_message": (
            "封面页信息已完整。"
            if expectations.get("done") is True
            else "已记录，请问还需要补充什么？"
        ),
        "selected_doc_id": expectations.get("selected_doc_ids", [case.doc_id])[0],
        "field_updates": dict(field_expectation.get("values", {})),
        "done": expectations.get("done", False),
    }


def _committed_corpus_raw() -> dict:
    return json.loads(CORPUS_PATH.read_text())


def _raw_case(raw: dict, case_id: str) -> dict:
    return next(case for case in raw["cases"] if case["id"] == case_id)


def _validate_production_corpus(raw: dict):
    return validate_corpus(parse_corpus(raw))


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_committed_live_corpus_is_valid_and_covers_all_documents():
    validated = validate_corpus(load_corpus())

    assert validated.document_ids == CATALOG_DOC_IDS
    assert validated.categories == {
        "catalog_routing",
        "manifest_field_extraction",
        "follow_up",
        "prompt_injection",
    }
    assert len(validated.smoke_cases) == 3
    assert len(validated.cases) == 34
    cases = {case.id: case for case in validated.cases}
    assert {case.id for case in validated.smoke_cases} == {
        "routing.mutual-nda",
        "routing.cloud-service-agreement",
        "routing.data-processing-agreement",
    }
    assert cases["fields.mnda-simplified-chinese"].expectations[
        "field_updates_expectation"
    ] == {
        "mode": "exact",
        "values": {
            "甲方公司名称": "示例甲科技有限公司",
            "保密用途": "评估双方人工智能产品合作",
        },
    }
    assert cases["fields.required-complete"].expectations[
        "field_updates_expectation"
    ] == {"mode": "empty"}
    assert cases["followup.missing-required"].expectations[
        "field_updates_expectation"
    ] == {
        "mode": "exact",
        "values": {"许可方": "示例软件有限公司"},
    }
    assert cases["injection.arbitrary-field"].expectations[
        "field_updates_expectation"
    ] == {"mode": "empty"}


@pytest.mark.parametrize(
    "schema_version",
    [True, False, 1.0, "1", None, _MISSING],
    ids=["true", "false", "float", "string", "null", "missing"],
)
def test_corpus_schema_version_requires_exact_integer_one(schema_version):
    raw = _committed_corpus_raw()
    if schema_version is _MISSING:
        raw.pop("schema_version")
    else:
        raw["schema_version"] = schema_version

    with pytest.raises(CorpusValidationError) as exc_info:
        parse_corpus(raw)

    assert exc_info.value.kind == "unsupported_corpus_schema"


@pytest.mark.parametrize(
    "smoke",
    ["true", "false", 1, 0, None, [], {}, _MISSING],
    ids=[
        "true-string",
        "false-string",
        "one",
        "zero",
        "null",
        "list",
        "object",
        "missing",
    ],
)
@pytest.mark.parametrize(
    "case_id",
    ["routing.mutual-nda", "fields.mnda-simplified-chinese"],
    ids=["smoke-case", "non-smoke-case"],
)
def test_corpus_smoke_flag_requires_exact_boolean(case_id, smoke):
    raw = _committed_corpus_raw()
    raw_case = _raw_case(raw, case_id)
    if smoke is _MISSING:
        raw_case.pop("smoke")
    else:
        raw_case["smoke"] = smoke

    with pytest.raises(CorpusValidationError) as exc_info:
        parse_corpus(raw)

    assert exc_info.value.kind == "invalid_smoke_flag"


def test_corpus_rejects_duplicate_case_ids():
    raw = _one_case_raw()
    raw["cases"].append(dict(raw["cases"][0]))

    with pytest.raises(CorpusValidationError, match="duplicate_case_id"):
        validate_corpus(
            parse_corpus(raw),
            catalog_doc_ids=CATALOG_DOC_IDS,
            manifest_doc_ids=CATALOG_DOC_IDS,
            require_all_documents=False,
            require_all_categories=False,
            require_three_smoke_cases=False,
        )


def test_corpus_rejects_unknown_document_and_expectation_key():
    with pytest.raises(CorpusValidationError, match="unknown_document_id"):
        _validated_single_case(doc_id="not-in-catalog")

    raw = _one_case_raw()
    raw["cases"][0]["expectations"]["invented_expectation"] = True
    with pytest.raises(CorpusValidationError, match="invalid_expectation_key"):
        validate_corpus(
            parse_corpus(raw),
            catalog_doc_ids=CATALOG_DOC_IDS,
            manifest_doc_ids=CATALOG_DOC_IDS,
            require_all_documents=False,
            require_all_categories=False,
            require_three_smoke_cases=False,
        )


@pytest.mark.parametrize(
    ("key", "invalid"),
    [
        ("selected_doc_must_exist", 1),
        ("field_keys_manifest_only", []),
        ("done", "false"),
        ("requires_question", 0),
        ("assistant_contains_cjk", None),
        ("forbid_secret_patterns", {}),
        ("selected_doc_ids", []),
        ("selected_doc_ids", ["", "mutual-nda"]),
        ("selected_doc_ids", [1]),
        ("forbidden_field_keys", []),
        ("forbidden_field_keys", [1]),
        ("forbidden_substrings", []),
        ("forbidden_substrings", [""]),
    ],
)
def test_corpus_expectation_types_fail_closed_before_provider_call(key, invalid):
    raw = _one_case_raw()
    raw["cases"][0]["expectations"][key] = invalid

    with pytest.raises(CorpusValidationError, match="invalid_expectation"):
        validate_corpus(
            parse_corpus(raw),
            catalog_doc_ids=CATALOG_DOC_IDS,
            manifest_doc_ids=CATALOG_DOC_IDS,
            require_all_documents=False,
            require_all_categories=False,
            require_three_smoke_cases=False,
        )


def test_corpus_rejects_removing_all_expectations_before_provider_call():
    raw = _committed_corpus_raw()
    for case in raw["cases"]:
        case["expectations"] = {}

    with pytest.raises(CorpusValidationError, match="category_contract_missing"):
        _validate_production_corpus(raw)


@pytest.mark.parametrize(
    ("case_id", "expectation_key"),
    [
        ("routing.mutual-nda", "selected_doc_ids"),
        ("routing.mutual-nda", "done"),
        ("routing.mutual-nda", "requires_question"),
        ("routing.mutual-nda", "assistant_contains_cjk"),
        ("routing.mutual-nda", "field_keys_manifest_only"),
        ("routing.mutual-nda", "forbid_secret_patterns"),
        ("fields.mnda-simplified-chinese", "field_updates_expectation"),
        ("followup.missing-required", "requires_question"),
        ("followup.missing-required", "field_updates_expectation"),
        ("injection.arbitrary-field", "field_updates_expectation"),
    ],
)
def test_corpus_rejects_missing_category_contract_expectations(
    case_id, expectation_key
):
    raw = _committed_corpus_raw()
    del _raw_case(raw, case_id)["expectations"][expectation_key]

    with pytest.raises(CorpusValidationError, match="category_contract_missing"):
        _validate_production_corpus(raw)


@pytest.mark.parametrize(
    "expectation_key",
    [
        "selected_doc_ids",
        "selected_doc_must_exist",
        "field_keys_manifest_only",
        "field_updates_expectation",
        "done",
        "assistant_contains_cjk",
        "forbid_secret_patterns",
    ],
)
def test_manifest_extraction_rejects_missing_core_expectation_before_provider_call(
    expectation_key,
):
    raw = _committed_corpus_raw()
    del _raw_case(raw, "fields.mnda-simplified-chinese")["expectations"][
        expectation_key
    ]

    with pytest.raises(CorpusValidationError) as exc_info:
        _validate_production_corpus(raw)

    assert exc_info.value.kind == "category_contract_missing"


def test_incomplete_manifest_extraction_requires_question_before_provider_call():
    raw = _committed_corpus_raw()
    del _raw_case(raw, "fields.mnda-simplified-chinese")["expectations"][
        "requires_question"
    ]

    with pytest.raises(CorpusValidationError) as exc_info:
        _validate_production_corpus(raw)

    assert exc_info.value.kind == "category_contract_missing"


def test_manifest_extraction_rejects_different_valid_target_before_provider_call():
    raw = _committed_corpus_raw()
    _raw_case(raw, "fields.mnda-simplified-chinese")["expectations"][
        "selected_doc_ids"
    ] = ["cloud-service-agreement"]

    with pytest.raises(CorpusValidationError) as exc_info:
        _validate_production_corpus(raw)

    assert exc_info.value.kind == "routing_target_mismatch"


@pytest.mark.parametrize(
    "expectation_key",
    [
        "selected_doc_must_exist",
        "field_keys_manifest_only",
        "assistant_contains_cjk",
        "forbid_secret_patterns",
    ],
)
def test_manifest_extraction_rejects_false_core_boolean_before_provider_call(
    expectation_key,
):
    raw = _committed_corpus_raw()
    _raw_case(raw, "fields.mnda-simplified-chinese")["expectations"][
        expectation_key
    ] = False

    with pytest.raises(CorpusValidationError) as exc_info:
        _validate_production_corpus(raw)

    assert exc_info.value.kind == "category_contract_mismatch"


def test_incomplete_manifest_extraction_rejects_false_requires_question():
    raw = _committed_corpus_raw()
    _raw_case(raw, "fields.mnda-simplified-chinese")["expectations"][
        "requires_question"
    ] = False

    with pytest.raises(CorpusValidationError) as exc_info:
        _validate_production_corpus(raw)

    assert exc_info.value.kind == "category_contract_mismatch"


def test_complete_manifest_extraction_allows_omitted_requires_question():
    raw = _committed_corpus_raw()
    complete_case = _raw_case(raw, "fields.required-complete")

    assert complete_case["expectations"]["done"] is True
    assert "requires_question" not in complete_case["expectations"]
    _validate_production_corpus(raw)


def test_complete_manifest_extraction_allows_explicit_false_requires_question():
    raw = _committed_corpus_raw()
    _raw_case(raw, "fields.required-complete")["expectations"][
        "requires_question"
    ] = False

    _validate_production_corpus(raw)


def test_complete_manifest_extraction_rejects_true_requires_question():
    raw = _committed_corpus_raw()
    _raw_case(raw, "fields.required-complete")["expectations"][
        "requires_question"
    ] = True

    with pytest.raises(CorpusValidationError) as exc_info:
        _validate_production_corpus(raw)

    assert exc_info.value.kind == "category_contract_mismatch"


def test_complete_manifest_extraction_rejects_missing_core_expectation():
    raw = _committed_corpus_raw()
    del _raw_case(raw, "fields.required-complete")["expectations"][
        "selected_doc_must_exist"
    ]

    with pytest.raises(CorpusValidationError) as exc_info:
        _validate_production_corpus(raw)

    assert exc_info.value.kind == "category_contract_missing"


def test_corpus_rejects_routing_to_a_different_valid_document():
    raw = _committed_corpus_raw()
    _raw_case(raw, "routing.mutual-nda")["expectations"]["selected_doc_ids"] = [
        "cloud-service-agreement"
    ]

    with pytest.raises(CorpusValidationError, match="routing_target_mismatch"):
        _validate_production_corpus(raw)


def test_corpus_rejects_empty_routing_selection():
    raw = _committed_corpus_raw()
    _raw_case(raw, "routing.mutual-nda")["expectations"]["selected_doc_ids"] = [""]

    with pytest.raises(CorpusValidationError, match="routing_target_mismatch"):
        _validate_production_corpus(raw)


def test_corpus_rejects_prompt_injection_without_specific_prohibition():
    raw = _committed_corpus_raw()
    expectations = _raw_case(raw, "injection.arbitrary-field")["expectations"]
    expectations.pop("forbidden_field_keys")

    with pytest.raises(
        CorpusValidationError, match="injection_contract_missing_prohibition"
    ):
        _validate_production_corpus(raw)


def test_corpus_rejects_moved_smoke_flags():
    raw = _committed_corpus_raw()
    for case in raw["cases"]:
        case["smoke"] = case["id"] in {
            "routing.design-partner-agreement",
            "routing.service-level-agreement",
            "routing.professional-services-agreement",
        }

    with pytest.raises(CorpusValidationError, match="smoke_case_set_mismatch"):
        _validate_production_corpus(raw)


@pytest.mark.parametrize(
    "field_expectation",
    [
        {"mode": "unknown", "values": {"保密用途": "测试"}},
        {"mode": "exact", "values": {}},
        {"mode": "contains", "values": {}},
        {"mode": "empty", "values": {"保密用途": "测试"}},
        {"mode": "exact", "values": {"非清单字段": "测试"}},
        {"mode": "exact", "values": {1: "测试"}},
        {"mode": "exact", "values": {"保密用途": 1}},
    ],
)
def test_corpus_rejects_invalid_field_update_policy(field_expectation):
    raw = _committed_corpus_raw()
    _raw_case(raw, "fields.mnda-simplified-chinese")["expectations"][
        "field_updates_expectation"
    ] = field_expectation

    with pytest.raises(CorpusValidationError, match="invalid_field_update_expectation"):
        _validate_production_corpus(raw)


def test_call_budget_counts_attempts_usage_cost_and_fails_closed():
    captured: list[dict] = []

    def completion(**kwargs):
        captured.append(kwargs)
        return _fake_response({"ok": True})

    budget = CallBudget(max_calls=1)
    wrapped = budget.wrap(completion)

    wrapped(model=llm.MODEL, max_retries=9)
    assert budget.actual_calls == 1
    assert captured == [{"model": llm.MODEL, "max_retries": 0}]
    assert budget.token_usage == {
        "prompt_tokens": 20,
        "completion_tokens": 8,
        "total_tokens": 28,
    }
    assert budget.reported_cost_usd == pytest.approx(0.001)

    with pytest.raises(LiveEvalConfigurationError, match="call_budget_exhausted"):
        wrapped(model=llm.MODEL)
    assert budget.actual_calls == 1
    assert budget.blocked_attempts == 1
    assert len(captured) == 1


def test_product_followup_call_counts_against_hard_budget(monkeypatch):
    corpus = _validated_single_case()
    responses = iter(
        [
            _fake_response(
                {
                    "assistant_message": "已记录。",
                    "selected_doc_id": "mutual-nda",
                    "field_updates": {},
                    "done": False,
                }
            ),
            _fake_response(
                {
                    "assistant_message": "已记录，请问保密用途是什么？",
                    "selected_doc_id": "mutual-nda",
                    "field_updates": {},
                    "done": False,
                }
            ),
        ]
    )
    captured: list[dict] = []

    def completion(**kwargs):
        captured.append(kwargs)
        return next(responses)

    monkeypatch.setattr(llm.litellm, "completion", completion)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    report = run_live_evaluation(
        corpus=corpus,
        cases=corpus.cases,
        max_calls=2,
        max_retries=0,
        mode="smoke",
    )

    assert report.exit_code == 0
    assert report.actual_calls == 2
    assert report.retry_count == 0
    assert report.product_followup_calls == 1
    assert report.results[0].product_followup_calls == 1
    assert [item["max_retries"] for item in captured] == [0, 0]
    assert report.local_followup_fallback_count == 0
    assert report.results[0].local_followup_fallback_used is False
    assert report.actual_calls == sum(result.calls for result in report.results)
    assert report.invariant_errors == []


@pytest.mark.parametrize(
    ("messages", "expected_calls", "expected_followups", "expected_fallback"),
    [
        (["已记录，请问保密用途是什么？"], 1, 0, False),
        (["已记录。", "请问保密用途是什么？"], 2, 1, False),
        (["已记录。", "仍然只是陈述。"], 2, 1, True),
    ],
)
def test_product_followup_fallback_is_observable(
    monkeypatch,
    messages,
    expected_calls,
    expected_followups,
    expected_fallback,
):
    corpus = _validated_single_case(category="follow_up")
    responses = iter(messages)
    monkeypatch.setattr(
        llm.litellm,
        "completion",
        lambda **_kwargs: _fake_response(
            {
                "assistant_message": next(responses),
                "selected_doc_id": "mutual-nda",
                "field_updates": {},
                "done": False,
            }
        ),
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    report = run_live_evaluation(
        corpus=corpus,
        cases=corpus.cases,
        max_calls=2,
        max_retries=0,
        mode="smoke",
    )

    assert report.exit_code == 0
    assert report.actual_calls == expected_calls
    assert report.product_followup_calls == expected_followups
    assert report.local_followup_fallback_count == int(expected_fallback)
    assert report.results[0].local_followup_fallback_used is expected_fallback


def test_call_budget_exhaustion_is_stable_and_never_overruns(monkeypatch):
    corpus = _validated_single_case(category="follow_up")
    monkeypatch.setattr(
        llm.litellm,
        "completion",
        lambda **_kwargs: _fake_response(
            {
                "assistant_message": "已记录。",
                "selected_doc_id": "mutual-nda",
                "field_updates": {},
                "done": False,
            }
        ),
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    report = run_live_evaluation(
        corpus=corpus,
        cases=corpus.cases,
        max_calls=1,
        max_retries=0,
        mode="smoke",
    )

    assert report.actual_calls == 1
    assert report.incomplete is True
    assert report.results[0].error_class == "call_budget_exhausted"
    assert report.actual_calls == sum(result.calls for result in report.results)
    assert report.invariant_errors == []
    assert report.exit_code == 3


def test_evaluator_retry_is_bounded_and_separate_from_product_followup(monkeypatch):
    corpus = _validated_single_case(category="follow_up")
    calls = 0

    captured: list[dict] = []

    def completion(**kwargs):
        nonlocal calls
        calls += 1
        captured.append(kwargs)
        if calls == 1:
            raise TimeoutError("temporary upstream timeout")
        return _fake_response(
            {
                "assistant_message": "请问保密用途是什么？",
                "selected_doc_id": "mutual-nda",
                "field_updates": {},
                "done": False,
            }
        )

    monkeypatch.setattr(llm.litellm, "completion", completion)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    report = run_live_evaluation(
        corpus=corpus,
        cases=corpus.cases,
        max_calls=2,
        max_retries=1,
        mode="smoke",
    )

    assert report.exit_code == 0
    assert report.actual_calls == 2
    assert report.retry_count == 1
    assert report.product_followup_calls == 0
    assert report.actual_calls == sum(result.calls for result in report.results)
    assert report.invariant_errors == []
    assert [item["max_retries"] for item in captured] == [0, 0]


def test_evaluator_retry_budget_is_shared_across_cases(monkeypatch):
    first = _validated_single_case(category="follow_up").cases[0]
    second = deepcopy(first)
    object.__setattr__(second, "id", "followup.second-timeout")
    corpus = _validated_single_case(category="follow_up")
    responses = iter(
        [
            TimeoutError("first timeout"),
            _fake_response(_passing_payload(first)),
            TimeoutError("second timeout"),
        ]
    )
    captured: list[dict] = []

    def completion(**kwargs):
        captured.append(kwargs)
        response = next(responses)
        if isinstance(response, BaseException):
            raise response
        return response

    monkeypatch.setattr(llm.litellm, "completion", completion)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    report = run_live_evaluation(
        corpus=corpus,
        cases=(first, second),
        max_calls=3,
        max_retries=1,
        mode="selected",
    )

    assert report.actual_calls == 3
    assert report.retry_count == 1
    assert [result.status for result in report.results] == ["pass", "error"]
    assert report.incomplete is True
    assert report.exit_code == 3
    assert all(item["max_retries"] == 0 for item in captured)


def test_rate_limit_is_not_retried_even_when_retry_budget_exists(monkeypatch):
    corpus = _validated_single_case(category="follow_up")
    calls = 0

    class RateLimitError(Exception):
        pass

    def rate_limited(**_kwargs):
        nonlocal calls
        calls += 1
        raise RateLimitError("429 rate-limited")

    monkeypatch.setattr(llm.litellm, "completion", rate_limited)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    report = run_live_evaluation(
        corpus=corpus,
        cases=corpus.cases,
        max_calls=2,
        max_retries=1,
        mode="smoke",
    )

    assert calls == 1
    assert report.actual_calls == 1
    assert report.retry_count == 0
    assert report.results[0].error_class == "upstream_rate_limit"
    assert report.exit_code == 3


def test_report_invariants_and_exit_codes():
    report = LiveEvalReport.start(
        corpus_version="test-1",
        git_sha="a" * 40,
        dirty_worktree=False,
        mode="smoke",
        max_calls=3,
        max_retries=0,
        api_key_present=True,
        selected_case_ids=("routing.mnda",),
    )
    report.finish()

    assert "case_totals_mismatch" in report.invariant_errors
    assert report.exit_code == 1

    report.incomplete = True
    assert report.exit_code == 1


def test_report_rejects_retry_overrun_and_false_green_incomplete_run():
    report = LiveEvalReport.start(
        corpus_version="test-1",
        git_sha="a" * 40,
        dirty_worktree=False,
        mode="selected",
        max_calls=3,
        max_retries=1,
        api_key_present=True,
        selected_case_ids=("case.one",),
    )
    report.results.append(
        LiveCaseResult(
            case_id="case.one",
            category="follow_up",
            doc_id="mutual-nda",
            status="pass",
            latency_ms=1,
            http_status=200,
            calls=3,
            retries=2,
            product_followup_calls=1,
        )
    )
    report.actual_calls = 3
    report.retry_count = 2
    report.product_followup_calls = 1
    report.incomplete = True
    report.finish()

    assert "retry_budget_exceeded" in report.invariant_errors
    assert report.exit_code == 1


def test_report_rejects_actual_call_total_mismatch():
    report = LiveEvalReport.start(
        corpus_version="test-1",
        git_sha="a" * 40,
        dirty_worktree=False,
        mode="selected",
        max_calls=3,
        max_retries=0,
        api_key_present=True,
        selected_case_ids=("case.one",),
    )
    report.results.append(
        LiveCaseResult(
            case_id="case.one",
            category="follow_up",
            doc_id="mutual-nda",
            status="pass",
            latency_ms=1,
            http_status=200,
            calls=0,
            retries=0,
        )
    )
    report.actual_calls = 3
    report.finish()

    assert "actual_call_total_mismatch" in report.invariant_errors
    assert report.exit_code == 1


def test_incomplete_report_with_skipped_case_preserves_call_total():
    report = LiveEvalReport.start(
        corpus_version="test-1",
        git_sha="a" * 40,
        dirty_worktree=False,
        mode="selected",
        max_calls=1,
        max_retries=0,
        api_key_present=True,
        selected_case_ids=("case.error", "case.skipped"),
    )
    report.results.extend(
        [
            LiveCaseResult(
                case_id="case.error",
                category="follow_up",
                doc_id="mutual-nda",
                status="error",
                latency_ms=1,
                http_status=502,
                calls=1,
                retries=0,
                error_class="upstream_timeout",
            ),
            LiveCaseResult(
                case_id="case.skipped",
                category="follow_up",
                doc_id="mutual-nda",
                status="skipped",
                latency_ms=0,
                http_status=None,
                calls=0,
                retries=0,
                error_class="prior_upstream_error",
            ),
        ]
    )
    report.actual_calls = 1
    report.incomplete = True
    report.finish()

    assert report.invariant_errors == []
    assert report.exit_code == 3


def test_blocked_call_budget_attempt_counts_neither_global_nor_case_call():
    report = LiveEvalReport.start(
        corpus_version="test-1",
        git_sha="a" * 40,
        dirty_worktree=False,
        mode="selected",
        max_calls=1,
        max_retries=0,
        api_key_present=True,
        selected_case_ids=("case.blocked",),
    )
    report.results.append(
        LiveCaseResult(
            case_id="case.blocked",
            category="follow_up",
            doc_id="mutual-nda",
            status="error",
            latency_ms=1,
            http_status=502,
            calls=0,
            retries=0,
            error_class="call_budget_exhausted",
        )
    )
    report.actual_calls = 0
    report.incomplete = True
    report.finish()

    assert report.actual_calls == sum(result.calls for result in report.results)
    assert report.invariant_errors == []
    assert report.exit_code == 3


def test_report_rejects_missing_duplicate_and_invalid_results():
    report = LiveEvalReport.start(
        corpus_version="test-1",
        git_sha="a" * 40,
        dirty_worktree=False,
        mode="selected",
        max_calls=2,
        max_retries=0,
        api_key_present=True,
        selected_case_ids=("case.one", "case.two"),
    )
    for status in ("pass", "unknown"):
        report.results.append(
            LiveCaseResult(
                case_id="case.one",
                category="follow_up",
                doc_id="mutual-nda",
                status=status,
                latency_ms=1,
                http_status=200,
                calls=1,
                retries=0,
            )
        )
    report.actual_calls = 2
    report.finish()

    assert {
        "duplicate_result_case_id",
        "invalid_result_status",
        "selected_case_result_mismatch",
    } <= set(report.invariant_errors)
    assert report.to_dict()["estimated_cost_usd"] is None
    assert report.exit_code == 1


def test_well_formed_incomplete_report_cannot_exit_zero():
    report = LiveEvalReport.start(
        corpus_version="test-1",
        git_sha="a" * 40,
        dirty_worktree=False,
        mode="smoke",
        max_calls=1,
        max_retries=0,
        api_key_present=True,
        selected_case_ids=("case.one",),
    )
    report.results.append(
        LiveCaseResult(
            case_id="case.one",
            category="follow_up",
            doc_id="mutual-nda",
            status="error",
            latency_ms=1,
            http_status=502,
            calls=1,
            retries=0,
            error_class="upstream_timeout",
        )
    )
    report.actual_calls = 1
    report.incomplete = True
    report.finish()

    assert report.invariant_errors == []
    assert report.exit_code == 3


def test_cli_fails_before_call_without_explicit_live_confirmation(monkeypatch, capsys):
    called = False

    def forbidden_run(**_kwargs):
        nonlocal called
        called = True
        raise AssertionError("runner must not be reached")

    monkeypatch.setattr("llm_quality_evals.__main__.run_live_evaluation", forbidden_run)
    monkeypatch.setenv("OPENROUTER_API_KEY", "present-but-not-printed")

    assert main(["--smoke", "--confirm-spend"]) == 2
    assert main(["--smoke", "--live"]) == 2
    assert called is False
    assert "present-but-not-printed" not in capsys.readouterr().err


def test_cli_rejects_missing_key_and_existing_output_without_call(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    called = False

    def forbidden_run(**_kwargs):
        nonlocal called
        called = True
        raise AssertionError("runner must not be reached")

    monkeypatch.setattr("llm_quality_evals.__main__.run_live_evaluation", forbidden_run)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert main(["--live", "--confirm-spend", "--smoke"]) == 2

    output = tmp_path / "existing.json"
    output.write_text("do not replace")
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret-value")
    assert (
        main(
            [
                "--live",
                "--confirm-spend",
                "--smoke",
                "--output",
                str(output),
            ],
        )
        == 2
    )
    assert output.read_text() == "do not replace"
    assert called is False
    assert "secret-value" not in capsys.readouterr().err


def test_live_runner_uses_authenticated_chat_route_and_records_safe_report(
    monkeypatch,
):
    expectations = deepcopy(_one_case_raw()["cases"][0]["expectations"])
    expectations["field_updates_expectation"] = {
        "mode": "exact",
        "values": {"保密用途": "评估双方人工智能产品合作"},
    }
    corpus = _validated_single_case(
        category="manifest_field_extraction",
        messages=[
            {
                "role": "user",
                "content": "保密用途是评估双方人工智能产品合作。",
            }
        ],
        expectations=expectations,
    )
    captured: dict = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return _fake_response(
            {
                "assistant_message": "好的，请问保密用途是什么？",
                "selected_doc_id": "mutual-nda",
                "field_updates": {"保密用途": "评估双方人工智能产品合作"},
                "done": False,
            }
        )

    monkeypatch.setattr(llm.litellm, "completion", fake_completion)
    monkeypatch.setenv("OPENROUTER_API_KEY", "never-record-this-key")

    report = run_live_evaluation(
        corpus=corpus,
        cases=corpus.cases,
        max_calls=1,
        max_retries=0,
        mode="smoke",
    )
    encoded = json.dumps(report.to_dict(), ensure_ascii=False)

    assert report.exit_code == 0
    assert report.actual_calls == 1
    assert report.results[0].status == "pass"
    assert report.results[0].http_status == 200
    assert captured["model"] == "openrouter/openai/gpt-oss-120b"
    assert captured["extra_body"] == {
        "provider": {"order": ["cerebras"], "allow_fallbacks": False}
    }
    assert captured["response_format"]["type"] == "json_schema"
    assert captured["max_retries"] == 0
    assert "## Field checklist" in captured["messages"][0]["content"]
    assertions = {item.name: item for item in report.results[0].assertions}
    assert assertions["field_updates_expectation"].passed is True
    assert "never-record-this-key" not in encoded
    assert "Authorization" not in encoded


def _field_assertion(case_id: str, field_updates: object) -> AssertionResult:
    raw = _committed_corpus_raw()
    case = parse_corpus(raw).cases[
        next(index for index, item in enumerate(raw["cases"]) if item["id"] == case_id)
    ]
    selected_doc_id = case.expectations["selected_doc_ids"][0]
    assertions = _evaluate_response(
        case=case,
        body={
            "assistant_message": "已记录，请问还需要补充什么？",
            "selected_doc_id": selected_doc_id,
            "mnda_updates": {},
            "field_updates": field_updates,
            "done": case.expectations["done"],
        },
        status_code=200,
        catalog_doc_ids=CATALOG_DOC_IDS,
    )
    return next(
        assertion
        for assertion in assertions
        if assertion.name == "field_updates_expectation"
    )


def test_exact_field_updates_reject_extra_manifest_valid_field():
    assertion = _field_assertion(
        "fields.csa-no-cross-document",
        {
            "服务方": "示例云科技有限公司",
            "客户": "凭空臆造的客户",
        },
    )

    assert assertion.passed is False
    assert assertion.detail == "field_updates_exact_mismatch"


def test_exact_field_updates_trim_string_values_before_comparison():
    assertion = _field_assertion(
        "fields.csa-no-cross-document",
        {"服务方": "  示例云科技有限公司  "},
    )

    assert assertion.passed is True
    assert assertion.detail is None


def test_exact_field_updates_reject_non_string_value():
    assertion = _field_assertion(
        "fields.csa-no-cross-document",
        {"服务方": ["示例云科技有限公司"]},
    )

    assert assertion.passed is False
    assert assertion.detail == "field_updates_non_string_value"


def test_contains_field_updates_allows_extra_manifest_valid_fields():
    raw = _committed_corpus_raw()
    case_raw = _raw_case(raw, "fields.csa-no-cross-document")
    case_raw["expectations"]["field_updates_expectation"]["mode"] = "contains"
    case = parse_corpus(raw).cases[
        next(index for index, item in enumerate(raw["cases"]) if item is case_raw)
    ]

    assertions = _evaluate_response(
        case=case,
        body={
            "assistant_message": "已记录，请问还需要补充什么？",
            "selected_doc_id": "cloud-service-agreement",
            "mnda_updates": {},
            "field_updates": {
                "服务方": "示例云科技有限公司",
                "客户": "示例客户有限公司",
            },
            "done": False,
        },
        status_code=200,
        catalog_doc_ids=CATALOG_DOC_IDS,
    )

    assertion = next(
        item for item in assertions if item.name == "field_updates_expectation"
    )
    assert assertion.passed is True


@pytest.mark.parametrize(
    ("case_id", "field_updates"),
    [
        ("followup.missing-required", {}),
        ("injection.arbitrary-field", {"服务方": "凭空臆造的值"}),
        (
            "injection.change-contract-language",
            {"合作期限": "This agreement shall remain in force for twelve months."},
        ),
    ],
)
def test_field_update_policy_closes_known_false_green_paths(case_id, field_updates):
    assertion = _field_assertion(case_id, field_updates)

    assert assertion.passed is False


def test_runner_filters_cross_document_fields_and_detects_injection_sentinel(
    monkeypatch,
):
    raw = _one_case_raw()
    raw["cases"][0]["category"] = "prompt_injection"
    raw["cases"][0]["expectations"].update(
        {
            "forbidden_field_keys": ["伪造字段"],
            "forbidden_substrings": ["PL24B_INJECTION_SENTINEL"],
        }
    )
    corpus = validate_corpus(
        parse_corpus(raw),
        catalog_doc_ids=CATALOG_DOC_IDS,
        manifest_doc_ids=CATALOG_DOC_IDS,
        require_all_documents=False,
        require_all_categories=False,
        require_three_smoke_cases=False,
    )

    monkeypatch.setattr(
        llm.litellm,
        "completion",
        lambda **_kwargs: _fake_response(
            {
                "assistant_message": "PL24B_INJECTION_SENTINEL？",
                "selected_doc_id": "mutual-nda",
                "field_updates": {"伪造字段": "跨文档值"},
                "done": False,
            }
        ),
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    report = run_live_evaluation(
        corpus=corpus,
        cases=corpus.cases,
        max_calls=1,
        max_retries=0,
        mode="smoke",
    )

    # The production normalizer removes the unknown key; the independent
    # evaluator still catches the assistant-message sentinel leak.
    assertions = {item.name: item for item in report.results[0].assertions}
    assert assertions["field_keys_manifest_only"].passed is True
    assert assertions["forbidden_substrings"].passed is False
    assert report.exit_code == 1


@pytest.mark.parametrize(
    "body",
    [
        {
            "assistant_message": "泄漏 pl24b_injection_sentinel？",
            "selected_doc_id": "mutual-nda",
            "mnda_updates": {},
            "field_updates": {},
            "done": False,
        },
        {
            "assistant_message": "请问还需补充什么？",
            "selected_doc_id": "mutual-nda",
            "mnda_updates": {},
            "field_updates": {"保密用途": "PL24B_INJECTION_SENTINEL"},
            "done": False,
        },
        {
            "assistant_message": "请问还需补充什么？",
            "selected_doc_id": "mutual-nda",
            "mnda_updates": {},
            "field_updates": {"Pl24B_Injection_Sentinel": "值"},
            "done": False,
        },
        {
            "assistant_message": "请问还需补充什么？",
            "selected_doc_id": "pl24b_INJECTION_sentinel",
            "mnda_updates": {},
            "field_updates": {},
            "done": False,
        },
    ],
)
def test_forbidden_substrings_cover_normalized_full_response_body(body):
    raw = _one_case_raw()
    raw["cases"][0]["expectations"]["forbidden_substrings"] = [
        "PL24B_INJECTION_SENTINEL"
    ]
    case = parse_corpus(raw).cases[0]

    assertions = _evaluate_response(
        case=case,
        body=body,
        status_code=200,
        catalog_doc_ids=CATALOG_DOC_IDS,
    )

    by_name = {assertion.name: assertion for assertion in assertions}
    assert by_name["forbidden_substrings"].passed is False


def test_runner_marks_malformed_and_upstream_errors_incomplete(monkeypatch):
    corpus = _validated_single_case()
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setattr(
        llm.litellm,
        "completion",
        lambda **_kwargs: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="not-json"))],
        ),
    )

    malformed = run_live_evaluation(
        corpus=corpus,
        cases=corpus.cases,
        max_calls=1,
        max_retries=0,
        mode="smoke",
    )
    assert malformed.incomplete is True
    assert malformed.results[0].status == "error"
    assert malformed.results[0].error_class == "malformed_structured_response"
    assert malformed.exit_code == 3

    def timeout(**_kwargs):
        raise TimeoutError("secret request details")

    monkeypatch.setattr(llm.litellm, "completion", timeout)
    upstream = run_live_evaluation(
        corpus=corpus,
        cases=corpus.cases,
        max_calls=1,
        max_retries=0,
        mode="smoke",
    )
    assert upstream.results[0].error_class == "upstream_timeout"
    assert "secret request details" not in json.dumps(upstream.to_dict())
    assert upstream.exit_code == 3


def test_runner_rejects_oversized_state_without_provider_call(monkeypatch):
    raw = _one_case_raw(document_state={"payload": "x" * (65 * 1024)})
    corpus = validate_corpus(
        parse_corpus(raw),
        catalog_doc_ids=CATALOG_DOC_IDS,
        manifest_doc_ids=CATALOG_DOC_IDS,
        require_all_documents=False,
        require_all_categories=False,
        require_three_smoke_cases=False,
    )
    calls = 0

    def fake_completion(**_kwargs):
        nonlocal calls
        calls += 1
        return _fake_response({})

    monkeypatch.setattr(llm.litellm, "completion", fake_completion)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    report = run_live_evaluation(
        corpus=corpus,
        cases=corpus.cases,
        max_calls=1,
        max_retries=0,
        mode="smoke",
    )

    assert calls == 0
    assert report.actual_calls == 0
    assert report.results[0].http_status == 422
    assert report.results[0].status == "fail"


def test_full_corpus_paces_local_chat_limit_without_quality_false_fails(monkeypatch):
    corpus = validate_corpus(load_corpus())
    clock = FakeClock()
    responses = iter(_fake_response(_passing_payload(case)) for case in corpus.cases)
    monkeypatch.setattr(llm.litellm, "completion", lambda **_kwargs: next(responses))
    monkeypatch.setattr(ratelimit.time, "monotonic", clock.monotonic)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    report = run_live_evaluation(
        corpus=corpus,
        cases=corpus.cases,
        max_calls=34,
        max_retries=0,
        mode="full",
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
    )

    assert report.case_totals == {
        "total": 34,
        "pass": 34,
        "fail": 0,
        "error": 0,
        "skipped": 0,
    }
    assert report.actual_calls == 34
    assert report.incomplete is False
    assert report.exit_code == 0
    assert clock.sleeps == [60.0]


def test_route_level_chat_rate_limit_is_incomplete_not_quality_fail(monkeypatch):
    corpus = _validated_single_case()
    provider_calls = 0

    def completion(**_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        return _fake_response(_passing_payload(corpus.cases[0]))

    monkeypatch.setattr(llm.litellm, "completion", completion)
    monkeypatch.setattr(ratelimit.CHAT_LIMITER, "allow", lambda _key: False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    report = run_live_evaluation(
        corpus=corpus,
        cases=corpus.cases,
        max_calls=1,
        max_retries=0,
        mode="smoke",
    )

    assert provider_calls == 0
    assert report.results[0].status == "error"
    assert report.results[0].error_class == "local_chat_rate_limit"
    assert report.actual_calls == 0
    assert report.results[0].calls == 0
    assert report.invariant_errors == []
    assert report.incomplete is True
    assert report.exit_code == 3


def test_smoke_hard_budget_never_exceeds_three_provider_attempts(monkeypatch):
    corpus = validate_corpus(load_corpus())
    calls = 0

    def no_question(**_kwargs):
        nonlocal calls
        calls += 1
        return _fake_response(
            {
                "assistant_message": "已记录。",
                "selected_doc_id": "mutual-nda",
                "field_updates": {},
                "done": False,
            }
        )

    monkeypatch.setattr(llm.litellm, "completion", no_question)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    report = run_live_evaluation(
        corpus=corpus,
        cases=corpus.smoke_cases,
        max_calls=3,
        max_retries=0,
        mode="smoke",
    )

    assert calls == 3
    assert report.actual_calls == 3
    assert report.actual_calls <= report.max_calls
    assert report.incomplete is True
    assert report.exit_code == 3
