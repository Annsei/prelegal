"""Fresh-process worker that proves the deterministic evaluator is offline."""

from __future__ import annotations

import _socket
import argparse
import builtins
import os
import socket
import subprocess
import sys
from typing import Any

_ORIGINAL_SOCKET_CONSTRUCTOR = socket.socket
_ORIGINAL_LOW_LEVEL_SOCKET_CONSTRUCTOR = _socket.socket
_ORIGINAL_GETADDRINFO = socket.getaddrinfo
_ORIGINAL_POPEN = subprocess.Popen
_GUARDS_INSTALLED = False
_DNS_ENTRY_POINTS = (
    "getaddrinfo",
    "getfqdn",
    "gethostbyaddr",
    "gethostbyname",
    "gethostbyname_ex",
    "getnameinfo",
)
_DNS_AUDIT_EVENTS = {f"socket.{name}" for name in _DNS_ENTRY_POINTS}
_PROCESS_AUDIT_EVENTS = {
    "os.exec",
    "os.fork",
    "os.forkpty",
    "os.posix_spawn",
    "os.spawn",
    "os.system",
    "pty.spawn",
    "subprocess.Popen",
}
_OS_PROCESS_ENTRY_POINTS = (
    "execl",
    "execle",
    "execlp",
    "execlpe",
    "execv",
    "execve",
    "execvp",
    "execvpe",
    "fork",
    "forkpty",
    "popen",
    "posix_spawn",
    "posix_spawnp",
    "spawnl",
    "spawnle",
    "spawnlp",
    "spawnlpe",
    "spawnv",
    "spawnve",
    "spawnvp",
    "spawnvpe",
    "system",
)


class _ForbiddenImportFinder:
    def find_spec(self, fullname: str, _path=None, _target=None):
        if _is_forbidden_import(fullname):
            raise ImportError(f"offline_guard_blocked_import:{fullname}")
        return None


def _is_forbidden_import(name: str) -> bool:
    return (
        name == "app.llm"
        or name.startswith("app.llm.")
        or name == "litellm"
        or name.startswith("litellm.")
    )


def _socket_family_marker(family: int) -> str:
    try:
        return socket.AddressFamily(family).name
    except ValueError:
        return str(family)


def _require_local_socket_family(family: int) -> None:
    effective_family = socket.AF_INET if family == -1 else family
    allowed_family = getattr(socket, "AF_UNIX", None)
    if allowed_family is not None and effective_family == allowed_family:
        return
    raise RuntimeError(
        f"offline_guard_blocked_socket_family:{_socket_family_marker(effective_family)}"
    )


def _offline_audit_hook(event: str, args: tuple[Any, ...]) -> None:
    if event == "socket.__new__":
        _require_local_socket_family(args[1])
    if event in _DNS_AUDIT_EVENTS:
        _blocked_dns()
    if event in _PROCESS_AUDIT_EVENTS:
        _blocked_subprocess()


def _blocked_create_connection(*_args: Any, **_kwargs: Any) -> None:
    raise RuntimeError("offline_guard_blocked_create_connection")


def _blocked_dns(*_args: Any, **_kwargs: Any) -> None:
    raise RuntimeError("offline_guard_blocked_dns")


def _blocked_subprocess(*_args: Any, **_kwargs: Any) -> None:
    raise RuntimeError("offline_guard_blocked_subprocess")


def _install_guards() -> None:
    global _GUARDS_INSTALLED
    if _GUARDS_INSTALLED:
        return

    original_import = builtins.__import__

    def guarded_import(name: str, *args: Any, **kwargs: Any):
        if _is_forbidden_import(name):
            raise ImportError(f"offline_guard_blocked_import:{name}")
        return original_import(name, *args, **kwargs)

    builtins.__import__ = guarded_import
    sys.meta_path.insert(0, _ForbiddenImportFinder())

    # Python's C-level socket audit event also covers constructor references
    # captured before this guard and direct _socket usage. That closes TCP,
    # UDP/sendto/sendmsg, raw-socket, and third-party client paths together;
    # AF_UNIX stays available for socketpair-based local runtimes.
    # This hook is intentionally irreversible; the worker is a fresh process.
    sys.addaudithook(_offline_audit_hook)
    socket.create_connection = _blocked_create_connection

    for module in (socket, _socket):
        for name in _DNS_ENTRY_POINTS:
            if hasattr(module, name):
                setattr(module, name, _blocked_dns)

    subprocess.Popen = _blocked_subprocess
    subprocess.run = _blocked_subprocess
    subprocess.call = _blocked_subprocess
    subprocess.check_call = _blocked_subprocess
    subprocess.check_output = _blocked_subprocess
    subprocess.getoutput = _blocked_subprocess
    subprocess.getstatusoutput = _blocked_subprocess
    for name in _OS_PROCESS_ENTRY_POINTS:
        if hasattr(os, name):
            setattr(os, name, _blocked_subprocess)

    _GUARDS_INSTALLED = True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--probe",
        choices=(
            "socket",
            "inet_socket",
            "low_level_socket",
            "udp",
            "ipv6",
            "dns",
            "subprocess",
            "unix_socket",
            "app_llm",
            "litellm",
        ),
    )
    args = parser.parse_args(argv)
    _install_guards()
    if args.probe == "socket":
        socket.create_connection(("127.0.0.1", 9))
        return 0
    if args.probe == "inet_socket":
        _ORIGINAL_SOCKET_CONSTRUCTOR(socket.AF_INET, socket.SOCK_STREAM)
        return 0
    if args.probe == "low_level_socket":
        _ORIGINAL_LOW_LEVEL_SOCKET_CONSTRUCTOR(socket.AF_INET, socket.SOCK_STREAM)
        return 0
    if args.probe == "udp":
        sock = _ORIGINAL_SOCKET_CONSTRUCTOR(socket.AF_INET, socket.SOCK_DGRAM)
        print(f"udp_bytes_sent={sock.sendto(b'X', ('127.0.0.1', 9))}")
        return 0
    if args.probe == "ipv6":
        _ORIGINAL_SOCKET_CONSTRUCTOR(socket.AF_INET6, socket.SOCK_STREAM)
        return 0
    if args.probe == "dns":
        _ORIGINAL_GETADDRINFO("offline-probe.invalid", 443)
        return 0
    if args.probe == "subprocess":
        process = _ORIGINAL_POPEN([sys.executable, "-c", "pass"])
        process.wait()
        return 0
    if args.probe == "unix_socket":
        sock = _ORIGINAL_SOCKET_CONSTRUCTOR(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.close()
        return 0
    if args.probe == "app_llm":
        __import__("app.llm")
        return 0
    if args.probe == "litellm":
        __import__("litellm")
        return 0

    from quality_evals.__main__ import main as evaluator_main

    exit_code = evaluator_main(["--json"])
    forbidden = [name for name in sys.modules if _is_forbidden_import(name)]
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
