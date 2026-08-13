"""CLI for explicit, cost-bounded PL-24B live LLM evaluations."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from llm_quality_evals.corpus import CorpusValidationError, load_corpus, validate_corpus
from llm_quality_evals.runner import (
    LiveEvalConfigurationError,
    run_live_evaluation,
    select_cases,
)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        _validate_startup(args)
        corpus = validate_corpus(load_corpus())
        cases = select_cases(
            corpus,
            smoke=args.smoke,
            case_ids=set(args.case),
            categories=set(args.category),
            doc_ids=set(args.doc),
        )
        if len(cases) > args.max_calls:
            raise LiveEvalConfigurationError(
                "minimum_call_budget_too_small:"
                f"selected={len(cases)} max={args.max_calls}"
            )
        output = _reserve_output(args.output)
        try:
            report = run_live_evaluation(
                corpus=corpus,
                cases=cases,
                max_calls=args.max_calls,
                max_retries=args.max_retries,
                mode=(
                    "smoke"
                    if args.smoke
                    else "selected"
                    if args.case or args.category or args.doc
                    else "full"
                ),
            )
            encoded = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
            if output is not None:
                output.write(encoded)
            if args.json:
                print(encoded)
            else:
                totals = report.case_totals
                print(
                    "live-llm-eval: "
                    f"total={totals['total']} pass={totals['pass']} "
                    f"fail={totals['fail']} error={totals['error']} "
                    f"skipped={totals['skipped']} calls={report.actual_calls}"
                )
            return report.exit_code
        finally:
            if output is not None:
                output.close()
    except (CorpusValidationError, LiveEvalConfigurationError, OSError) as exc:
        print(f"live_eval_configuration_error:{_safe_error(exc)}", file=sys.stderr)
        return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run opt-in live evaluations through Prelegal's /api/chat path."
    )
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--confirm-spend", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--category", action="append", default=[])
    parser.add_argument("--doc", action="append", default=[])
    parser.add_argument(
        "--max-calls",
        type=int,
        default=3,
        help="Hard run-wide provider-attempt budget (SDK retries are disabled).",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=0,
        help="Run-wide evaluator retry budget; product follow-ups are separate.",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser


def _validate_startup(args: argparse.Namespace) -> None:
    if not args.live:
        raise LiveEvalConfigurationError("live_confirmation_missing")
    if not args.confirm_spend:
        raise LiveEvalConfigurationError("spend_confirmation_missing")
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise LiveEvalConfigurationError("api_key_missing")
    if args.max_calls <= 0:
        raise LiveEvalConfigurationError("invalid_max_calls")
    if args.max_retries < 0:
        raise LiveEvalConfigurationError("invalid_max_retries")
    if args.smoke and args.max_calls > 3:
        raise LiveEvalConfigurationError("smoke_call_budget_exceeds_three")


def _reserve_output(path: Path | None):
    if path is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("x", encoding="utf-8")


def _safe_error(exc: BaseException) -> str:
    if isinstance(exc, CorpusValidationError):
        return exc.kind
    text = str(exc)
    allowed = (
        "api_key_missing",
        "call_budget_exhausted",
        "git_state_unavailable",
        "invalid_max_calls",
        "invalid_max_retries",
        "live_confirmation_missing",
        "minimum_call_budget_too_small",
        "no_cases_selected",
        "retry_budget_exhausted",
        "smoke_call_budget_exceeds_three",
        "spend_confirmation_missing",
        "temporary_registration_failed",
        "unexpected_model",
        "unexpected_provider_routing",
        "unknown_case",
        "unknown_category",
        "unknown_doc",
    )
    for marker in allowed:
        if marker in text:
            return marker
    if isinstance(exc, FileExistsError):
        return "output_exists"
    return type(exc).__name__


if __name__ == "__main__":
    raise SystemExit(main())
