#!/usr/bin/env python3

from __future__ import annotations

import ctypes
import subprocess
from ctypes import wintypes
from pathlib import Path


SIZE_T = ctypes.c_size_t
ULONG_PTR = SIZE_T
JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
JobObjectExtendedLimitInformation = 9


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", SIZE_T),
        ("MaximumWorkingSetSize", SIZE_T),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ULONG_PTR),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", SIZE_T),
        ("JobMemoryLimit", SIZE_T),
        ("PeakProcessMemoryUsed", SIZE_T),
        ("PeakJobMemoryUsed", SIZE_T),
    ]


def _memory_limit_bytes(memory_limit_mb: int) -> int:
    return memory_limit_mb * 1024 * 1024


def _peak_memory_mb_from_bytes(peak_memory_bytes: int | None) -> int | None:
    if peak_memory_bytes is None or peak_memory_bytes <= 0:
        return None
    one_mb = 1024 * 1024
    return max(1, (peak_memory_bytes + one_mb - 1) // one_mb)


def _query_peak_job_memory_bytes(kernel32, job_handle) -> int | None:
    limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    if not kernel32.QueryInformationJobObject(
        job_handle,
        JobObjectExtendedLimitInformation,
        ctypes.byref(limits),
        ctypes.sizeof(limits),
        None,
    ):
        return None

    peak_memory_bytes = int(max(limits.PeakJobMemoryUsed, limits.PeakProcessMemoryUsed))
    return peak_memory_bytes or None


def _attach_peak_memory(
    completed: subprocess.CompletedProcess[str],
    peak_memory_bytes: int | None,
) -> subprocess.CompletedProcess[str]:
    completed.peak_memory_mb = _peak_memory_mb_from_bytes(peak_memory_bytes)
    return completed


def run_process(
    command: list[str] | str,
    cwd: Path,
    timeout_s: float | None,
    env: dict[str, str],
    shell: bool,
    memory_limit_mb: int | None = None,
) -> subprocess.CompletedProcess[str]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    job_handle = kernel32.CreateJobObjectW(None, None)
    if not job_handle:
        raise ctypes.WinError(ctypes.get_last_error())

    peak_memory_bytes: int | None = None
    try:
        if memory_limit_mb is not None:
            limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_PROCESS_MEMORY
            limits.ProcessMemoryLimit = _memory_limit_bytes(memory_limit_mb)
            if not kernel32.SetInformationJobObject(
                job_handle,
                JobObjectExtendedLimitInformation,
                ctypes.byref(limits),
                ctypes.sizeof(limits),
            ):
                raise ctypes.WinError(ctypes.get_last_error())

        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            shell=shell,
        )
        try:
            process_handle = wintypes.HANDLE(int(process._handle))
            if not kernel32.AssignProcessToJobObject(job_handle, process_handle):
                error = ctypes.get_last_error()
                process.kill()
                process.communicate()
                raise RuntimeError(f"Failed to assign process to Windows memory limit job: {ctypes.WinError(error)}")

            try:
                stdout, stderr = process.communicate(timeout=timeout_s)
            except subprocess.TimeoutExpired as exc:
                kernel32.TerminateJobObject(job_handle, 1)
                stdout, stderr = process.communicate()
                raise subprocess.TimeoutExpired(exc.cmd, exc.timeout, output=stdout, stderr=stderr) from exc
            peak_memory_bytes = _query_peak_job_memory_bytes(kernel32, job_handle)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
    finally:
        kernel32.CloseHandle(job_handle)

    completed = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    return _attach_peak_memory(completed, peak_memory_bytes)


