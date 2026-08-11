"""Local fresh-process tripwire runner for the deterministic evaluator.

The authoritative CI no-network guarantee is provided by the Linux container
entry point in ``quality_evals.kernel_gate``.
"""

from __future__ import annotations

import json
import subprocess
import sys


def main(argv: list[str] | None = None) -> int:
    command = [sys.executable, "-m", "quality_evals.offline_worker", *(argv or [])]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.stdout:
        sys.stdout.write(completed.stdout)
    if completed.stderr:
        sys.stderr.write(completed.stderr)
    if argv:
        return completed.returncode
    if completed.stdout:
        try:
            report = json.loads(completed.stdout)
        except json.JSONDecodeError:
            print("offline_gate_invalid_json_report", file=sys.stderr)
            return 1
        if not isinstance(report, dict) or report.get("schema_version") != 1:
            print("offline_gate_invalid_report_schema", file=sys.stderr)
            return 1
    elif completed.returncode == 0:
        print("offline_gate_missing_json_report", file=sys.stderr)
        return 1
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
