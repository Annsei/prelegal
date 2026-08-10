"""Fresh-process worker that proves the deterministic evaluator is offline."""

from __future__ import annotations

import argparse
import builtins
import socket
import sys
from typing import Any


def _blocked_network(*_args: Any, **_kwargs: Any) -> None:
    raise RuntimeError("offline_guard_blocked_socket")


def _install_guards() -> None:
    original_import = builtins.__import__

    def guarded_import(name: str, *args: Any, **kwargs: Any):
        if name == "app.llm" or name.startswith("litellm"):
            raise ImportError(f"offline_guard_blocked_import:{name}")
        return original_import(name, *args, **kwargs)

    builtins.__import__ = guarded_import
    socket.socket.connect = _blocked_network
    socket.socket.connect_ex = _blocked_network
    socket.create_connection = _blocked_network


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", choices=("socket", "app_llm", "litellm"))
    args = parser.parse_args(argv)
    _install_guards()
    if args.probe == "socket":
        socket.create_connection(("127.0.0.1", 9))
        return 0
    if args.probe == "app_llm":
        __import__("app.llm")
        return 0
    if args.probe == "litellm":
        __import__("litellm")
        return 0

    from quality_evals.__main__ import main as evaluator_main

    exit_code = evaluator_main(["--json"])
    forbidden = [
        name
        for name in sys.modules
        if name == "app.llm" or name.startswith("litellm")
    ]
    if forbidden:
        print(
            f"offline_guard_imported_forbidden_modules:{sorted(forbidden)}",
            file=sys.stderr,
        )
        return 1
    return exit_code


if __name__ == "__main__":
    try:
        code = main()
    except (ImportError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        code = 1
    raise SystemExit(code)
