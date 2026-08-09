"""CLI entry point for the deterministic contract-quality hard gate."""

from __future__ import annotations

import argparse
import json

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
    report = run_contract_quality_evaluation()
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
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
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
