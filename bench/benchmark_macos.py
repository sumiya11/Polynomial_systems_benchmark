#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
import re


MACOS_TIME_MAXRSS_PATTERN = re.compile(r"^\s*(\d+)\s+maximum resident set size$", re.MULTILINE)


def _resource_limit_preexec(memory_limit_mb: int):
    limit_bytes = memory_limit_mb * 1024 * 1024

    def apply_limit() -> None:
        import resource

        for name in ("RLIMIT_AS", "RLIMIT_DATA", "RLIMIT_RSS"):
            if hasattr(resource, name):
                resource.setrlimit(getattr(resource, name), (limit_bytes, limit_bytes))

    return apply_limit


def _command_text(command: list[str] | str) -> str:
    if isinstance(command, str):
        return command
    return subprocess.list2cmdline(command)


def _exec_command(command: list[str] | str, shell: bool) -> list[str]:
    if shell:
        return ["/bin/sh", "-c", _command_text(command)]
    if isinstance(command, str):
        return [command]
    return command


def _macos_time_binary() -> str | None:
    time_binary = Path("/usr/bin/time")
    if time_binary.is_file():
        return str(time_binary)
    return None


def _peak_memory_mb_from_kb(peak_memory_kb: int | None) -> int | None:
    if peak_memory_kb is None or peak_memory_kb <= 0:
        return None
    return max(1, (peak_memory_kb + 1023) // 1024)


def _read_peak_memory_kb(stats_path: Path) -> int | None:
    if not stats_path.is_file():
        return None

    match = MACOS_TIME_MAXRSS_PATTERN.search(stats_path.read_text(encoding="utf-8", errors="replace"))
    if not match:
        return None
    return int(match.group(1))


def _attach_peak_memory(
    completed: subprocess.CompletedProcess[str],
    peak_memory_kb: int | None,
) -> subprocess.CompletedProcess[str]:
    completed.peak_memory_mb = _peak_memory_mb_from_kb(peak_memory_kb)
    return completed


def _timed_exec_command(command: list[str] | str, shell: bool, stats_path: Path) -> list[str] | None:
    time_binary = _macos_time_binary()
    if not time_binary:
        return None

    return [time_binary, "-l", "-o", str(stats_path), *_exec_command(command, shell)]


def _run_timed_command(
    command: list[str] | str,
    cwd: Path,
    timeout_s: float | None,
    env: dict[str, str],
    shell: bool,
    preexec_fn=None,
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="gbbench-time-") as temp_dir:
        stats_path = Path(temp_dir) / "peak_memory.txt"
        timed_command = _timed_exec_command(command, shell, stats_path)
        if timed_command is None:
            completed = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                env=env,
                shell=shell,
                preexec_fn=preexec_fn,
            )
            completed.peak_memory_mb = None
            return completed

        try:
            completed = subprocess.run(
                timed_command,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                env=env,
                preexec_fn=preexec_fn,
            )
        except subprocess.TimeoutExpired as exc:
            raise subprocess.TimeoutExpired(_command_text(command), exc.timeout, output=exc.output, stderr=exc.stderr) from exc

        peak_memory_kb = _read_peak_memory_kb(stats_path)

    tracked = subprocess.CompletedProcess(command, completed.returncode, completed.stdout, completed.stderr)
    return _attach_peak_memory(tracked, peak_memory_kb)


def run_process(
    command: list[str] | str,
    cwd: Path,
    timeout_s: float | None,
    env: dict[str, str],
    shell: bool,
    memory_limit_mb: int | None = None,
) -> subprocess.CompletedProcess[str]:
    if sys.platform != "darwin":
        raise RuntimeError("benchmark_macos backend can only execute on macOS")

    if memory_limit_mb is None:
        return _run_timed_command(command, cwd, timeout_s, env, shell)

    return _run_timed_command(
        command,
        cwd,
        timeout_s,
        env,
        shell,
        preexec_fn=_resource_limit_preexec(memory_limit_mb),
    )


