"""Authoritative Linux container boundary for the contract-quality hard gate."""

from __future__ import annotations

import ctypes
import errno
import json
import os
import socket
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

_EXPECTED_CASES = 703
_EXPECTED_COVERAGE = 715
_EXPECTED_NOT_APPLICABLE = 12
_NETWORK_ROOT = Path("/sys/class/net")
_ROUTE_FILE = Path("/proc/net/route")
_IPV6_ADDRESS_FILE = Path("/proc/net/if_inet6")
_STATUS_FILE = Path("/proc/self/status")
_UNIX_TABLE = Path("/proc/net/unix")
_CONTROL_SOCKET_ROOTS = (Path("/run"), Path("/tmp"))
_KNOWN_CONTROL_SOCKETS = (
    Path("/var/run/docker.sock"),
    Path("/run/docker.sock"),
    Path("/run/containerd/containerd.sock"),
    Path("/run/podman/podman.sock"),
)
_PROBE_ADDRESS = "192.0.2.1"
_PROBE_PORT = 9


class KernelIsolationError(RuntimeError):
    """Stable failure raised when the container boundary is not fail closed."""


class _SockaddrIn(ctypes.Structure):
    _fields_ = [
        ("sin_family", ctypes.c_ushort),
        ("sin_port", ctypes.c_ushort),
        ("sin_addr", ctypes.c_ubyte * 4),
        ("sin_zero", ctypes.c_ubyte * 8),
    ]


def _fail(reason: str, detail: str | None = None) -> None:
    suffix = f":{detail}" if detail else ""
    raise KernelIsolationError(f"kernel_isolation_failed:{reason}{suffix}")


def _read_status() -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in _STATUS_FILE.read_text().splitlines():
        key, separator, value = line.partition(":")
        if separator:
            fields[key] = value.strip()
    return fields


def _assert_unprivileged_boundary() -> None:
    if sys.platform != "linux":
        _fail("linux_required", sys.platform)
    if os.geteuid() == 0:
        _fail("root_user")
    status = _read_status()
    if int(status.get("CapEff", "-1"), 16) != 0:
        _fail("effective_capabilities_present", status.get("CapEff"))
    if status.get("NoNewPrivs") != "1":
        _fail("no_new_privileges_missing", status.get("NoNewPrivs"))
    print("kernel_isolation_unprivileged_boundary_ok", file=sys.stderr)


def _ipv4_route_interfaces() -> set[str]:
    routes: set[str] = set()
    lines = _ROUTE_FILE.read_text().splitlines()
    for line in lines[1:]:
        columns = line.split()
        if columns:
            routes.add(columns[0])
    return routes


def _non_loopback_ipv6_interfaces() -> set[str]:
    interfaces: set[str] = set()
    if not _IPV6_ADDRESS_FILE.exists():
        return interfaces
    for line in _IPV6_ADDRESS_FILE.read_text().splitlines():
        columns = line.split()
        if len(columns) >= 6 and columns[5] != "lo":
            interfaces.add(columns[5])
    return interfaces


def _assert_network_namespace() -> None:
    active_non_loopback: set[str] = set()
    for entry in _NETWORK_ROOT.iterdir():
        state_file = entry / "operstate"
        if entry.name == "lo" or not state_file.exists():
            continue
        if state_file.read_text().strip() != "down":
            active_non_loopback.add(entry.name)
    if active_non_loopback:
        _fail(
            "active_non_loopback_interface",
            ",".join(sorted(active_non_loopback)),
        )
    route_interfaces = _ipv4_route_interfaces()
    if route_interfaces:
        _fail("ipv4_route_present", ",".join(sorted(route_interfaces)))
    ipv6_interfaces = _non_loopback_ipv6_interfaces()
    if ipv6_interfaces:
        _fail("non_loopback_ipv6_address", ",".join(sorted(ipv6_interfaces)))
    print("kernel_isolation_network_namespace_ok:routes=none", file=sys.stderr)


def _filesystem_socket_paths() -> set[str]:
    sockets: set[str] = set()
    for root in _CONTROL_SOCKET_ROOTS:
        if not root.exists():
            continue
        for directory, names, files in os.walk(root, followlinks=False):
            for name in [*names, *files]:
                path = Path(directory, name)
                try:
                    if stat.S_ISSOCK(path.lstat().st_mode):
                        sockets.add(str(path))
                except FileNotFoundError:
                    continue
    return sockets


def _unix_table_socket_paths() -> set[str]:
    paths: set[str] = set()
    for line in _UNIX_TABLE.read_text().splitlines()[1:]:
        columns = line.split(maxsplit=7)
        if len(columns) == 8:
            paths.add(columns[7])
    return paths


def _assert_no_local_control_plane() -> None:
    known = {str(path) for path in _KNOWN_CONTROL_SOCKETS if path.exists()}
    discovered = _filesystem_socket_paths() | _unix_table_socket_paths()
    sockets = sorted(known | discovered)
    if sockets:
        _fail("local_control_socket_present", ",".join(sockets))
    print("kernel_isolation_control_sockets_absent", file=sys.stderr)


def _probe_native_process() -> None:
    result = ctypes.CDLL(None).system(b"/usr/bin/true")
    if result != 0:
        _fail("native_process_probe_failed", str(result))
    print("kernel_isolation_native_process_rc=0", file=sys.stderr)


def _probe_native_network() -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    libc.socket.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
    libc.socket.restype = ctypes.c_int
    libc.connect.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint]
    libc.connect.restype = ctypes.c_int
    libc.close.argtypes = [ctypes.c_int]
    libc.close.restype = ctypes.c_int

    descriptor = libc.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
    if descriptor < 0:
        _fail("native_socket_creation_failed", errno.errorcode.get(ctypes.get_errno()))
    address = _SockaddrIn()
    address.sin_family = socket.AF_INET
    address.sin_port = socket.htons(_PROBE_PORT)
    address.sin_addr[:] = socket.inet_aton(_PROBE_ADDRESS)
    try:
        result = libc.connect(
            descriptor,
            ctypes.byref(address),
            ctypes.sizeof(address),
        )
        error_number = ctypes.get_errno()
    finally:
        libc.close(descriptor)

    if result == 0:
        _fail("native_network_escape_connected")
    if error_number not in {errno.ENETUNREACH, errno.EHOSTUNREACH}:
        _fail(
            "native_network_unexpected_errno",
            errno.errorcode.get(error_number, str(error_number)),
        )
    marker = errno.errorcode.get(error_number, str(error_number))
    print(f"kernel_isolation_native_network_blocked:{marker}", file=sys.stderr)


def _assert_environment() -> None:
    if "OPENROUTER_API_KEY" in os.environ:
        _fail("openrouter_key_present")
    print("kernel_isolation_openrouter_key_absent", file=sys.stderr)


def _validate_report(report: Any) -> None:
    if not isinstance(report, dict) or report.get("schema_version") != 1:
        _fail("invalid_report_schema")
    expected = {
        "total_cases": _EXPECTED_CASES,
        "passed_cases": _EXPECTED_CASES,
        "failed_cases": 0,
        "invariant_errors": [],
    }
    for key, value in expected.items():
        if report.get(key) != value:
            _fail("quality_report_mismatch", key)
    coverage = report.get("coverage")
    if not isinstance(coverage, dict):
        _fail("quality_report_mismatch", "coverage")
    if coverage.get("expected_count") != _EXPECTED_COVERAGE:
        _fail("quality_report_mismatch", "coverage.expected_count")
    if coverage.get("actual_count") != _EXPECTED_COVERAGE:
        _fail("quality_report_mismatch", "coverage.actual_count")
    not_applicable = coverage.get("not_applicable")
    if (
        not isinstance(not_applicable, list)
        or len(not_applicable) != _EXPECTED_NOT_APPLICABLE
    ):
        _fail("quality_report_mismatch", "coverage.not_applicable")


def _run_evaluator() -> int:
    completed = subprocess.run(
        [sys.executable, "-m", "quality_evals.offline_worker"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.stderr:
        sys.stderr.write(completed.stderr)
    if completed.returncode != 0:
        if completed.stdout:
            sys.stdout.write(completed.stdout)
        return completed.returncode
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        _fail("invalid_json_report", str(exc.lineno))
    _validate_report(report)
    sys.stdout.write(completed.stdout)
    print(
        "kernel_isolation_quality_report_ok:703/703:715/715:na=12",
        file=sys.stderr,
    )
    return 0


def main() -> int:
    try:
        _assert_environment()
        _assert_unprivileged_boundary()
        _assert_network_namespace()
        _assert_no_local_control_plane()
        _probe_native_process()
        _probe_native_network()
        return _run_evaluator()
    except (KernelIsolationError, OSError, ValueError) as exc:
        if isinstance(exc, KernelIsolationError):
            marker = str(exc)
        else:
            marker = f"kernel_isolation_failed:preflight_error:{type(exc).__name__}"
        print(marker, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
