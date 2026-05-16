#!/usr/bin/env python3

from __future__ import annotations

import functools
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def _command_text(command: list[str] | str) -> str:
    if isinstance(command, str):
        return command
    return subprocess.list2cmdline(command)


def _scope_unit_name() -> str:
    return f"gbbench-{os.getpid()}-{time.time_ns():x}.scope"


def _exec_command(command: list[str] | str, shell: bool) -> list[str]:
    if shell:
        return ["/bin/sh", "-c", _command_text(command)]
    if isinstance(command, str):
        return [command]
    return command


def _stop_systemd_user_unit(unit_name: str) -> None:
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return
    try:
        subprocess.run(
            [systemctl, "--user", "stop", unit_name],
            capture_output=True,
            text=True,
            timeout=10.0,
            env=os.environ.copy(),
        )
    except (OSError, subprocess.SubprocessError):
        return


@functools.lru_cache(maxsize=1)
def _systemd_memory_limit_available() -> bool:
    if not sys.platform.startswith("linux"):
        return False

    systemd_run = shutil.which("systemd-run")
    if not systemd_run:
        return False

    probe_command = shutil.which("true") or "/bin/true"
    unit_name = _scope_unit_name()
    try:
        probe = subprocess.run(
            [
                systemd_run,
                "--user",
                "--scope",
                "--quiet",
                f"--unit={unit_name}",
                "--property=MemoryMax=32M",
                probe_command,
            ],
            capture_output=True,
            text=True,
            timeout=10.0,
            env=os.environ.copy(),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return probe.returncode == 0


def _resource_limit_preexec(memory_limit_mb: int):
    import resource

    limit_bytes = memory_limit_mb * 1024 * 1024
    resource_name = "RLIMIT_AS"
    if not hasattr(resource, resource_name):
        return None

    resource_type = getattr(resource, resource_name)

    def apply_limit() -> None:
        try:
            _current_soft, current_hard = resource.getrlimit(resource_type)
        except (OSError, ValueError):
            return

        if current_hard in (-1, resource.RLIM_INFINITY):
            target_limit = limit_bytes
        else:
            target_limit = min(limit_bytes, current_hard)

        if target_limit <= 0:
            return

        try:
            resource.setrlimit(resource_type, (target_limit, target_limit))
        except (OSError, ValueError):
            # Best effort only: falling back to no pre-exec limit is better than
            # aborting the child process before exec.
            return

    return apply_limit


def _gnu_time_binary() -> str | None:
    candidate = shutil.which("time")
    if candidate:
        return candidate

    fallback = Path("/usr/bin/time")
    if fallback.is_file():
        return str(fallback)
    return None


def _peak_memory_mb_from_kb(peak_memory_kb: int | None) -> int | None:
    if peak_memory_kb is None or peak_memory_kb <= 0:
        return None
    return max(1, (peak_memory_kb + 1023) // 1024)


def _read_peak_memory_kb(stats_path: Path) -> int | None:
    if not stats_path.is_file():
        return None

    text = stats_path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return None

    try:
        return int(text.splitlines()[-1].strip())
    except ValueError:
        return None


def _attach_peak_memory(
    completed: subprocess.CompletedProcess[str],
    peak_memory_kb: int | None,
) -> subprocess.CompletedProcess[str]:
    completed.peak_memory_mb = _peak_memory_mb_from_kb(peak_memory_kb)
    return completed


def _timed_exec_command(command: list[str] | str, shell: bool, stats_path: Path) -> list[str] | None:
    time_binary = _gnu_time_binary()
    if not time_binary:
        return None

    return [time_binary, "-f", "%M", "-o", str(stats_path), *_exec_command(command, shell)]


def _run_timed_command(
    command: list[str] | str,
    cwd: Path,
    timeout_s: float | None,
    env: dict[str, str],
    shell: bool,
    preexec_fn=None,
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="gbbench-time-") as temp_dir:
        stats_path = Path(temp_dir) / "peak_memory_kb.txt"
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


def _run_with_resource_limit(
    command: list[str] | str,
    cwd: Path,
    timeout_s: float | None,
    env: dict[str, str],
    shell: bool,
    memory_limit_mb: int,
) -> subprocess.CompletedProcess[str]:
    return _run_timed_command(command, cwd, timeout_s, env, shell, preexec_fn=_resource_limit_preexec(memory_limit_mb))


def run_process(
    command: list[str] | str,
    cwd: Path,
    timeout_s: float | None,
    env: dict[str, str],
    shell: bool,
    memory_limit_mb: int | None = None,
) -> subprocess.CompletedProcess[str]:
    if memory_limit_mb is None:
        return _run_timed_command(command, cwd, timeout_s, env, shell)

    if not _systemd_memory_limit_available():
        return _run_with_resource_limit(command, cwd, timeout_s, env, shell, memory_limit_mb)

    systemd_run = shutil.which("systemd-run")
    if not systemd_run:
        return _run_with_resource_limit(command, cwd, timeout_s, env, shell, memory_limit_mb)

    with tempfile.TemporaryDirectory(prefix="gbbench-time-") as temp_dir:
        stats_path = Path(temp_dir) / "peak_memory_kb.txt"
        timed_command = _timed_exec_command(command, shell, stats_path)
        if timed_command is None:
            return _run_with_resource_limit(command, cwd, timeout_s, env, shell, memory_limit_mb)

        unit_name = _scope_unit_name()
        process = subprocess.Popen(
            [
                systemd_run,
                "--user",
                "--scope",
                "--quiet",
                f"--unit={unit_name}",
                f"--property=MemoryMax={memory_limit_mb}M",
                *timed_command,
            ],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )

        try:
            stdout, stderr = process.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired as exc:
            _stop_systemd_user_unit(unit_name)
            try:
                stdout, stderr = process.communicate(timeout=10.0)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
            raise subprocess.TimeoutExpired(_command_text(command), exc.timeout, output=stdout, stderr=stderr) from exc
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

        peak_memory_kb = _read_peak_memory_kb(stats_path)

    tracked = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    return _attach_peak_memory(tracked, peak_memory_kb)


def run_process_with_memory_limit(
    command: list[str] | str,
    cwd: Path,
    timeout_s: float | None,
    env: dict[str, str],
    shell: bool,
    memory_limit_mb: int,
) -> subprocess.CompletedProcess[str]:
    return run_process(command, cwd, timeout_s, env, shell, memory_limit_mb)