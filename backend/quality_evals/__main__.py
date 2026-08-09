"""CLI entry point for the deterministic contract-quality hard gate."""

from __future__ import annotations

import argparse
import json
import sys

from app.draft_state import DraftPatchRejected
from quality_evals.corpus import CorpusValidationError
from quality_evals.runner import run_contract_quality_evaluation


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run deterministic Prelegal contract-quality evaluations."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the stable JSON report instead of the compact text summary.",
    )
    args = parser.parse_args()
    try:
        report = run_contract_quality_evaluation()
    except CorpusValidationError as exc:
        print(f"corpus_validation_failed:{exc.kind}: {exc}", file=sys.stderr)
        return 1
    except DraftPatchRejected as exc:
        kinds = ",".join(error.kind for error in exc.errors)
        print(f"evaluation_patch_failed:{kinds}", file=sys.stderr)
        return 1
    if args.json:
        try:
            encoded = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
        except (TypeError, ValueError) as exc:
            print(
                f"report_serialization_failed: {type(exc).__name__}",
                file=sys.stderr,
            )
            return 1
        print(encoded)
    else:
        print(
            "contract-quality: "
            f"total={report.total_cases} passed={report.passed_cases} "
            f"failed={report.failed_cases}"
        )
        for name, count in report.metrics.items():
            print(
                f"{name}={count} "
                f"evaluated={report.metric_denominators[name]}"
            )
        if report.failed_cases:
            print(report.failure_summary())
        for error in report.invariant_errors:
            print(f"report_invariant={error}")
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
