#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import functools
import hashlib
import importlib.util
import io
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path


REQUIRED_COLUMNS = [
    "job_id",
    "system_id",
    "instance_id",
    "system_ref",
    "input_ref",
    "software",
    "version",
    "threads",
    "field",
    "order",
    "hardware_track",
    "timeout_s",
]

OUTPUT_COLUMNS = [
    "run_id",
    "track",
    "job_id",
    "system_id",
    "instance_id",
    "system_ref",
    "system_sha256",
    "input_ref",
    "input_sha256",
    "software",
    "version",
    "runner",
    "threads",
    "field",
    "order",
    "hardware_track",
    "timeout_s",
    "status",
    "exit_code",
    "wall_time_seconds",
    "process_wall_time_seconds",
    "started_at_utc",
    "finished_at_utc",
    "runner_host",
    "runner_os",
    "runner_processor",
    "runner_machine",
    "runner_cpu_count",
    "runner_word_size",
    "runner_python",
    "log_ref",
    "command",
]

EXPERIMENT_COLUMNS = [
    "experiment_id",
    "track",
    "run_stage",
    "generated_at_utc",
    "definition_path",
    "results_table",
    "logs_dir",
    "row_count",
    "software_set",
    "instance_set",
    "shared_field",
    "shared_order",
    "shared_hardware_track",
    "shared_runner_host",
    "shared_runner_os",
    "shared_timeout_s",
    "notes",
    "replay_command",
]

TRACK_CONFIG_NAME = "config.json"
TRACK_REQUIRED_KEYS = [
    "examples",
    "software",
    "label",
    "sort_order",
    "default_display",
]

ALIASES = {
    "local": "test",
    "small": "test",
    "published": "test",
}

GF_PATTERN = re.compile(r"^GF\((\d+)\)$", re.IGNORECASE)
GBBENCH_TIME_PATTERN = re.compile(r"^GBBENCH_WALL_TIME=(.+)$", re.MULTILINE)
GBBENCH_VERSION_PATTERN = re.compile(r"^GBBENCH_VERSION=(.+)$", re.MULTILINE)


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def website_build_script(root: Path) -> Path:
    return root / "website" / "build.py"


@functools.lru_cache(maxsize=1)
def groebner_jl_runner_module():
    module_path = Path(__file__).resolve().parent / "run_groebner_jl.py"
    spec = importlib.util.spec_from_file_location("gbbench_run_groebner_jl", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load Groebner runner helper from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def resolve_path(root: Path, path_text: str | Path) -> Path:
    candidate = Path(path_text)
    if candidate.is_absolute():
        return candidate
    return root / candidate


def track_config_path(root: Path, track_name: str) -> Path:
    return root / "bench" / track_name / TRACK_CONFIG_NAME


def inferred_track_defaults(track_name: str) -> dict[str, object]:
    results_dir = Path("results") / track_name
    return {
        "results": (results_dir / "runs.tsv").as_posix(),
        "experiment": (results_dir / "experiment.txt").as_posix(),
        "logs_dir": (results_dir / "logs").as_posix(),
        "run_stage": "benchmark",
        "build_site": True,
        "bootstrap": True,
    }


def available_tracks(root: Path) -> list[str]:
    bench_dir = root / "bench"
    if not bench_dir.is_dir():
        return []
    return sorted(
        path.name
        for path in bench_dir.iterdir()
        if path.is_dir() and (path / TRACK_CONFIG_NAME).is_file()
    )


def load_track_config(root: Path, track_name: str) -> dict[str, object]:
    config_path = track_config_path(root, track_name)
    if not config_path.is_file():
        supported = ", ".join(available_tracks(root))
        raise ValueError(f"Unsupported benchmark track '{track_name}'. Supported tracks: {supported}")

    loaded = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"The benchmark config at {config_path} must be a JSON object")

    track = inferred_track_defaults(track_name)
    track.update(loaded)
    missing = [key for key in TRACK_REQUIRED_KEYS if key not in track]
    if missing:
        raise ValueError(f"Missing required keys in {config_path}: {', '.join(missing)}")
    if not isinstance(track["examples"], list):
        raise ValueError(f"The 'examples' entry in {config_path} must be a list")
    if not isinstance(track["software"], list):
        raise ValueError(f"The 'software' entry in {config_path} must be a list")
    inline_jobs = track.get("jobs")
    if inline_jobs is not None and not isinstance(inline_jobs, list):
        raise ValueError(f"The optional 'jobs' entry in {config_path} must be a list")
    return track


def resolve_track(root: Path, track_name: str) -> tuple[str, dict[str, object]]:
    canonical = ALIASES.get(track_name, track_name)
    return canonical, load_track_config(root, canonical)


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def iso_timestamp(now: datetime) -> str:
    return now.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def runner_processor() -> str:
    values = [
        os.environ.get("PROCESSOR_IDENTIFIER", ""),
        platform.processor(),
        platform.uname().processor,
        platform.machine(),
    ]
    for value in values:
        cleaned = (value or "").strip()
        if cleaned:
            return cleaned
    return ""


def runner_machine() -> str:
    values = [platform.machine(), platform.uname().machine]
    for value in values:
        cleaned = (value or "").strip()
        if cleaned:
            return cleaned
    return ""


def runner_cpu_count() -> str:
    count = os.cpu_count()
    return str(count) if count is not None else ""


def runner_word_size() -> str:
    return str(struct.calcsize("P") * 8)


def relative_text(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def shared_value(rows: list[dict[str, str]], key: str) -> str:
    values = {row.get(key, "") for row in rows}
    if len(values) == 1:
        return next(iter(values))
    return "mixed"


def compact_row_values(rows: list[dict[str, str]], key: str) -> str:
    values = sorted({row.get(key, "").strip() for row in rows if row.get(key, "").strip()})
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    return ", ".join(values)


def hardware_summary(rows: list[dict[str, str]]) -> str:
    parts = [
        compact_row_values(rows, "hardware_track"),
        compact_row_values(rows, "runner_host"),
        compact_row_values(rows, "runner_os"),
    ]
    return " | ".join(part for part in parts if part)


def interpreter_has_module(python_executable: str, module_name: str) -> bool:
    probe = subprocess.run(
        [python_executable, "-c", f"import {module_name}"],
        capture_output=True,
        text=True,
    )
    return probe.returncode == 0


def build_python(root: Path) -> str:
    if interpreter_has_module(sys.executable, "markdown"):
        return sys.executable

    for candidate in [root / "venv" / "Scripts" / "python.exe", root / "venv" / "bin" / "python"]:
        if candidate.is_file() and interpreter_has_module(str(candidate), "markdown"):
            return str(candidate)

    raise RuntimeError(
        "Cannot build the website because no Python interpreter with the markdown package was found. "
        "Install requirements into the active Python or the repository venv."
    )


def julia_binary() -> str:
    binary = os.environ.get("JULIA_BINARY") or shutil.which("julia") or shutil.which("julia.exe")
    if not binary:
        raise FileNotFoundError("Julia executable not found")
    return binary


@functools.lru_cache(maxsize=1)
def groebner_jl_version() -> str:
    try:
        probe = subprocess.run(
            [
                julia_binary(),
                "--startup-file=no",
                "-e",
                'using Groebner; if isdefined(Base, :pkgversion); println(Base.pkgversion(Groebner)); end',
            ],
            capture_output=True,
            text=True,
            timeout=60.0,
        )
    except (OSError, subprocess.SubprocessError):
        return ""

    if probe.returncode != 0:
        return ""
    return probe.stdout.strip()


def ensure_julia_packages() -> None:
    check = subprocess.run(
        [julia_binary(), "-e", "using Groebner, AbstractAlgebra"],
        capture_output=True,
        text=True,
    )
    if check.returncode == 0:
        return

    install = subprocess.run(
        [julia_binary(), "-e", 'import Pkg; Pkg.add(["Groebner", "AbstractAlgebra"])'],
        capture_output=True,
        text=True,
    )
    if install.returncode != 0:
        raise RuntimeError(
            "Failed to install Julia packages for Groebner.jl benchmarking.\n"
            f"stdout:\n{install.stdout}\n"
            f"stderr:\n{install.stderr}"
        )


def parse_benchmark_input(input_path: Path) -> dict[str, object]:
    lines = [line.strip() for line in input_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) < 3:
        raise ValueError(f"Benchmark input is too short: {input_path}")
    return {
        "variables": [part.strip() for part in lines[0].split(",") if part.strip()],
        "characteristic": int(lines[1].strip()),
        "polynomials": [line.rstrip(",").strip() for line in lines[2:] if line.rstrip(",").strip()],
    }


def resolve_field(field_text: str, fallback_characteristic: int) -> dict[str, object]:
    raw = (field_text or "").strip()
    if not raw:
        raw = "QQ" if fallback_characteristic == 0 else f"GF({fallback_characteristic})"

    if raw in {"QQ", "Q", "0"}:
        return {"display": "QQ", "prime": None}

    match = GF_PATTERN.match(raw)
    if match:
        prime = int(match.group(1))
        return {"display": f"GF({prime})", "prime": prime}

    if raw.isdigit() and int(raw) > 0:
        prime = int(raw)
        return {"display": f"GF({prime})", "prime": prime}

    raise ValueError(f"Unsupported field specification: {field_text}")


def format_command(command: list[str]) -> str:
    return subprocess.list2cmdline(command)


def run_process(
    command: list[str],
    cwd: Path,
    timeout_s: float | None,
    env: dict[str, str] | None = None,
) -> dict[str, str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        env=merged_env,
    )
    return {
        "status": "ok" if completed.returncode == 0 else "error",
        "exit_code": str(completed.returncode),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "command": format_command(command),
    }


def axf4_multi_thread_mode(job: dict[str, str]) -> str:
    mode = job.get("multi_thread", "").strip()
    if not mode:
        return ""
    if mode not in {"0", "1"}:
        raise ValueError("axf4 multi_thread must be either '0' or '1'")
    return mode


def resolve_axf4_binary(root: Path, path_text: str | None, required: bool) -> Path | None:
    raw_path = (path_text or "").strip()
    if not raw_path:
        if required:
            raise ValueError("axf4 jobs require --axf4-binary PATH")
        return None

    binary = resolve_path(root, raw_path)
    if not binary.is_file():
        raise FileNotFoundError(f"axf4 binary not found: {binary}")
    return binary


def run_axf4(
    job: dict[str, str],
    root: Path,
    input_path: Path,
    timeout_s: float | None,
    axf4_binary: Path | None = None,
) -> dict[str, str]:
    parsed = parse_benchmark_input(input_path)
    field = resolve_field(job["field"], int(parsed["characteristic"]))
    prime = field["prime"]
    if prime is None:
        raise ValueError("axf4 runner requires a finite field GF(p)")
    if axf4_binary is None:
        raise ValueError("axf4 jobs require --axf4-binary PATH")

    configured_threads = job.get("threads", "").strip() or "1"
    with tempfile.TemporaryDirectory(prefix="gbbench-axf4-") as temp_dir:
        temp_input = Path(temp_dir) / input_path.name
        temp_input.write_text("\n".join(parsed["polynomials"]) + "\n", encoding="utf-8")
        command = [
            str(axf4_binary),
            "-p",
            str(prime),
            "-v",
            f"[{','.join(parsed['variables'])}]",
            "-t",
            configured_threads,
            str(temp_input),
        ]
        result = run_process(command, root, timeout_s)

    result["runner"] = "axf4"
    result["threads"] = configured_threads
    return result


def run_groebner_jl(job: dict[str, str], root: Path, input_path: Path, timeout_s: float | None) -> dict[str, str]:
    parsed = parse_benchmark_input(input_path)
    field = resolve_field(job["field"], int(parsed["characteristic"]))
    threads = job.get("threads", "").strip() or "1"
    method = job.get("method", "").strip() or "groebner"
    runner_script = groebner_jl_runner_module().worker_script_path()
    command = [
        julia_binary(),
        "--startup-file=no",
        str(runner_script),
        "--input",
        str(input_path),
        "--field",
        str(field["display"]),
        "--order",
        job["order"],
        "--threads",
        threads,
        "--method",
        method,
    ]
    result = run_process(command, root, timeout_s, env={"JULIA_NUM_THREADS": threads})
    detected_version = groebner_jl_version()
    if detected_version:
        result["version"] = detected_version
    measured = GBBENCH_TIME_PATTERN.search(result["stdout"])
    if measured:
        result["wall_time_seconds"] = measured.group(1).strip()
    version = GBBENCH_VERSION_PATTERN.search(result["stdout"])
    if version:
        result["version"] = version.group(1).strip()
    result["runner"] = "groebner_jl"
    return result


RUNNERS = {
    "axf4": run_axf4,
    "groebner_jl": run_groebner_jl,
}


def configured_runner(runner_name: str, axf4_binary: Path | None = None):
    try:
        runner = RUNNERS[runner_name]
    except KeyError as exc:
        supported = ", ".join(sorted(RUNNERS))
        raise ValueError(f"Unsupported runner '{runner_name}'. Supported runners: {supported}") from exc

    if runner_name == "axf4":
        return functools.partial(run_axf4, axf4_binary=axf4_binary)
    return runner


def split_instance_id(instance_id: str) -> tuple[str, str]:
    try:
        system_id, suffix = instance_id.rsplit("-", 1)
    except ValueError as exc:
        raise ValueError(f"Instance id '{instance_id}' must contain a trailing '-<size>' suffix") from exc
    if not system_id or not suffix:
        raise ValueError(f"Instance id '{instance_id}' must contain a trailing '-<size>' suffix")
    return system_id, suffix


def default_refs_for_instance(instance_id: str, system_id: str | None = None) -> tuple[str, str, str]:
    inferred_system_id, suffix = split_instance_id(instance_id)
    resolved_system_id = system_id or inferred_system_id
    system_ref = f"systems/{resolved_system_id}/{resolved_system_id}.md"
    input_ref = f"systems/{resolved_system_id}/txt/{resolved_system_id}_{suffix}.txt"
    return resolved_system_id, system_ref, input_ref


def stringify_config_value(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def normalized_example_entry(track: dict[str, object], entry: object) -> dict[str, str]:
    if isinstance(entry, str):
        raw: dict[str, object] = {"instance_id": entry}
    elif isinstance(entry, dict):
        raw = dict(entry)
    else:
        raise ValueError("Each example entry must be either a string instance id or an object")

    instance_id = stringify_config_value(raw.get("instance_id")).strip()
    if not instance_id:
        raise ValueError("Each example entry must define a non-empty instance_id")

    inferred_system_id, default_system_ref, default_input_ref = default_refs_for_instance(instance_id)
    system_id = stringify_config_value(raw.get("system_id") or inferred_system_id).strip()
    _, derived_system_ref, derived_input_ref = default_refs_for_instance(instance_id, system_id)

    return {
        "instance_id": instance_id,
        "system_id": system_id,
        "system_ref": stringify_config_value(raw.get("system_ref") or derived_system_ref or default_system_ref).strip(),
        "input_ref": stringify_config_value(raw.get("input_ref") or derived_input_ref or default_input_ref).strip(),
        "field": stringify_config_value(raw.get("field", track.get("field"))).strip(),
        "order": stringify_config_value(raw.get("order", track.get("order"))).strip(),
        "hardware_track": stringify_config_value(raw.get("hardware_track", track.get("hardware_track"))).strip(),
        "timeout_s": stringify_config_value(raw.get("timeout_s", track.get("timeout_s"))).strip(),
    }


def track_example_ids(track: dict[str, object]) -> list[str]:
    return [normalized_example_entry(track, entry)["instance_id"] for entry in track.get("examples", [])]


def normalized_generated_software(entry: object) -> dict[str, str]:
    if not isinstance(entry, dict):
        raise ValueError("Each generated software entry must be an object")

    software = {
        "runner": stringify_config_value(entry.get("runner")).strip(),
        "command": stringify_config_value(entry.get("command")).strip(),
        "software": stringify_config_value(entry.get("software")).strip(),
        "version": stringify_config_value(entry.get("version")).strip(),
        "threads": stringify_config_value(entry.get("threads")).strip(),
        "job_id_suffix": stringify_config_value(entry.get("job_id_suffix")).strip(),
        "method": stringify_config_value(entry.get("method")).strip(),
        "multi_thread": stringify_config_value(entry.get("multi_thread")).strip(),
    }
    if not software["job_id_suffix"]:
        raise ValueError("Each generated software entry must define a non-empty job_id_suffix")
    if not software["runner"] and not software["command"]:
        raise ValueError(f"Software entry '{software['job_id_suffix']}' must define either a runner or a command")
    return software


def validate_job(job: dict[str, str], source: str) -> dict[str, str]:
    missing = [column for column in REQUIRED_COLUMNS if column not in job]
    if missing:
        raise ValueError(f"Missing required job fields in {source}: {', '.join(missing)}")
    if not job.get("runner", "").strip() and not job.get("command", "").strip():
        raise ValueError(f"{source} must define either a runner or a command")
    return job


def build_generated_jobs(track_name: str, track: dict[str, object]) -> list[dict[str, str]]:
    job_id_prefix = stringify_config_value(track.get("job_id_prefix")).strip()
    prefix = f"{job_id_prefix}-" if job_id_prefix else ""
    jobs = []
    for example in track.get("examples", []):
        normalized_example = normalized_example_entry(track, example)
        for software_entry in track.get("software", []):
            software = normalized_generated_software(software_entry)
            job_id = f"{prefix}{normalized_example['instance_id']}-{software['job_id_suffix']}"
            job = {
                "job_id": job_id,
                "system_id": normalized_example["system_id"],
                "instance_id": normalized_example["instance_id"],
                "system_ref": normalized_example["system_ref"],
                "input_ref": normalized_example["input_ref"],
                "runner": software["runner"],
                "command": software["command"],
                "software": software["software"],
                "version": software["version"],
                "threads": software["threads"],
                "method": software["method"],
                "multi_thread": software["multi_thread"],
                "field": normalized_example["field"],
                "order": normalized_example["order"],
                "hardware_track": normalized_example["hardware_track"],
                "timeout_s": normalized_example["timeout_s"],
            }
            jobs.append(validate_job(job, f"generated job {job_id} in track {track_name}"))
    return jobs


def normalized_inline_job(track_name: str, track: dict[str, object], entry: object) -> dict[str, str]:
    if not isinstance(entry, dict):
        raise ValueError(f"Inline jobs in track {track_name} must be objects")

    base = normalized_example_entry(track, entry)
    job_id = stringify_config_value(entry.get("job_id")).strip()
    if not job_id:
        raise ValueError(f"Inline jobs in track {track_name} must define a non-empty job_id")

    job = {
        "job_id": job_id,
        "system_id": stringify_config_value(entry.get("system_id") or base["system_id"]).strip(),
        "instance_id": base["instance_id"],
        "system_ref": stringify_config_value(entry.get("system_ref") or base["system_ref"]).strip(),
        "input_ref": stringify_config_value(entry.get("input_ref") or base["input_ref"]).strip(),
        "runner": stringify_config_value(entry.get("runner")).strip(),
        "command": stringify_config_value(entry.get("command")).strip(),
        "software": stringify_config_value(entry.get("software")).strip(),
        "version": stringify_config_value(entry.get("version")).strip(),
        "threads": stringify_config_value(entry.get("threads")).strip(),
        "method": stringify_config_value(entry.get("method")).strip(),
        "multi_thread": stringify_config_value(entry.get("multi_thread")).strip(),
        "field": stringify_config_value(entry.get("field") or base["field"]).strip(),
        "order": stringify_config_value(entry.get("order") or base["order"]).strip(),
        "hardware_track": stringify_config_value(entry.get("hardware_track") or base["hardware_track"]).strip(),
        "timeout_s": stringify_config_value(entry.get("timeout_s") or base["timeout_s"]).strip(),
    }
    return validate_job(job, f"inline job {job_id} in track {track_name}")


def load_track_jobs(track_name: str, track: dict[str, object]) -> list[dict[str, str]]:
    inline_jobs = track.get("jobs")
    if inline_jobs:
        return [normalized_inline_job(track_name, track, entry) for entry in inline_jobs]
    return build_generated_jobs(track_name, track)


def configured_runner_names(track: dict[str, object]) -> set[str]:
    return {
        str(entry.get("runner", "")).strip()
        for entry in track.get("software", [])
        if isinstance(entry, dict) and str(entry.get("runner", "")).strip()
    }


def jobs_for_runner(manifest_jobs: list[dict[str, str]], manifest_runner: str) -> list[dict[str, str]]:
    return [job for job in manifest_jobs if job.get("runner") == manifest_runner]


def job_timeout_s(job: dict[str, str], track: dict[str, object], override: float | None) -> float:
    if override is not None:
        return override
    timeout_text = job.get("timeout_s", "").strip()
    if timeout_text:
        return float(timeout_text)
    experiment_timeout = track.get("timeout_s")
    if experiment_timeout is not None:
        return float(experiment_timeout)
    return 86400.0


def report_runner_result(result: dict[str, str], elapsed: float) -> int:
    status = result.get("status")
    if status == "timeout":
        print("Timeout")
        return 124
    if status != "ok":
        print(result.get("stderr") or result.get("stdout") or "Run failed")
        return 1

    print(result.get("wall_time_seconds") or f"{elapsed:.6f}")
    return 0


def run_named_runner(
    runner_name: str,
    track_name: str,
    timeout_override: float | None = None,
    bootstrap: bool | None = None,
    axf4_binary: str | None = None,
) -> int:
    root = repo_root()
    canonical_track, track = resolve_track(root, track_name)
    enabled_runners = configured_runner_names(track)
    if enabled_runners and runner_name not in enabled_runners:
        print(f"Runner {runner_name} is not enabled for experiment {canonical_track}", file=sys.stderr)
        return 1

    jobs = jobs_for_runner(load_track_jobs(canonical_track, track), runner_name)
    if not jobs:
        print(f"Experiment {canonical_track} does not define any jobs for runner {runner_name}.", file=sys.stderr)
        return 1

    if runner_name == "groebner_jl":
        should_bootstrap = bool(track.get("bootstrap")) if bootstrap is None else bootstrap
        if should_bootstrap:
            try:
                ensure_julia_packages()
            except (OSError, RuntimeError) as exc:
                print(f"Warning: Julia bootstrap skipped: {exc}", file=sys.stderr)

    try:
        resolved_axf4_binary = resolve_axf4_binary(root, axf4_binary, required=runner_name == "axf4")
        runner = configured_runner(runner_name, resolved_axf4_binary)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    overall_status = 0
    for job in jobs:
        header = job["job_id"]
        if job["software"] != job["job_id"]:
            header = f"{job['job_id']} ({job['software']})"
        print(header)
        input_path = resolve_path(root, job["input_ref"])
        timeout_s = job_timeout_s(job, track, timeout_override)
        for attempt in range(3):
            started = time.perf_counter()
            try:
                result = runner(job, root, input_path, timeout_s)
            except subprocess.TimeoutExpired:
                print("Timeout")
                overall_status = 1
                break
            except (OSError, RuntimeError, ValueError) as exc:
                print(str(exc))
                overall_status = 1
                break

            exit_code = report_runner_result(result, time.perf_counter() - started)
            if exit_code != 0:
                overall_status = 1
                break
        print("=======================")

    return overall_status


def write_log_file(log_path: Path, row: dict[str, str], stdout: str, stderr: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"run_id: {row['run_id']}",
        f"track: {row['track']}",
        f"job_id: {row['job_id']}",
        f"system_ref: {row['system_ref']}",
        f"input_ref: {row['input_ref']}",
        f"software: {row['software']}",
        f"version: {row['version']}",
        f"runner: {row['runner']}",
        f"threads: {row['threads']}",
        f"field: {row['field']}",
        f"order: {row['order']}",
        f"hardware_track: {row['hardware_track']}",
        f"timeout_s: {row['timeout_s']}",
        f"status: {row['status']}",
        f"exit_code: {row['exit_code']}",
        f"wall_time_seconds: {row['wall_time_seconds']}",
        f"process_wall_time_seconds: {row['process_wall_time_seconds']}",
        f"started_at_utc: {row['started_at_utc']}",
        f"finished_at_utc: {row['finished_at_utc']}",
        f"runner_host: {row['runner_host']}",
        f"runner_os: {row['runner_os']}",
        f"runner_machine: {row['runner_machine']}",
        f"runner_cpu_count: {row['runner_cpu_count']}",
        f"runner_word_size: {row['runner_word_size']}",
        f"runner_python: {row['runner_python']}",
        f"command: {row['command']}",
        "",
        "[stdout]",
        stdout.rstrip(),
        "",
        "[stderr]",
        stderr.rstrip(),
        "",
    ]
    log_path.write_text("\n".join(lines), encoding="utf-8")


def run_legacy_command(job: dict[str, str], root: Path, timeout_s: float | None) -> dict[str, str]:
    completed = subprocess.run(
        job["command"],
        cwd=root,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    return {
        "status": "ok" if completed.returncode == 0 else "error",
        "exit_code": str(completed.returncode),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "command": job["command"],
        "wall_time_seconds": "",
        "runner": job.get("runner", "").strip() or "command",
    }


def run_job(
    job: dict[str, str],
    track_name: str,
    root: Path,
    track_logs_dir: Path,
    axf4_binary: Path | None = None,
) -> dict[str, str]:
    system_path = resolve_path(root, job["system_ref"])
    input_path = resolve_path(root, job["input_ref"])
    if not system_path.is_file():
        raise FileNotFoundError(f"Job {job['job_id']} points to missing system_ref: {job['system_ref']}")
    if not input_path.is_file():
        raise FileNotFoundError(f"Job {job['job_id']} points to missing input_ref: {job['input_ref']}")

    started = datetime.now(timezone.utc)
    started_perf = time.perf_counter()
    timeout_s = float(job["timeout_s"].strip()) if job["timeout_s"].strip() else None

    try:
        runner_name = job.get("runner", "").strip()
        if runner_name:
            runner = configured_runner(runner_name, axf4_binary)
            result = runner(job, root, input_path, timeout_s)
        else:
            result = run_legacy_command(job, root, timeout_s)
    except subprocess.TimeoutExpired as exc:
        result = {
            "status": "timeout",
            "exit_code": "",
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "command": job.get("command", ""),
            "wall_time_seconds": "",
            "runner": job.get("runner", "").strip() or "command",
        }
    except (OSError, RuntimeError) as exc:
        result = {
            "status": "error",
            "exit_code": "",
            "stdout": "",
            "stderr": str(exc),
            "command": job.get("command", ""),
            "wall_time_seconds": "",
            "runner": job.get("runner", "").strip() or "command",
        }

    finished = datetime.now(timezone.utc)
    elapsed = time.perf_counter() - started_perf
    log_rel = Path("results") / track_name / "logs" / f"{job['job_id']}.log"
    row = {
        "run_id": job["job_id"],
        "track": track_name,
        "job_id": job["job_id"],
        "system_id": job["system_id"],
        "instance_id": job["instance_id"],
        "system_ref": job["system_ref"],
        "system_sha256": compute_sha256(system_path),
        "input_ref": job["input_ref"],
        "input_sha256": compute_sha256(input_path),
        "software": result.get("software", job["software"]),
        "version": result.get("version", job["version"]),
        "runner": result.get("runner", job.get("runner", "").strip() or "command"),
        "threads": result.get("threads", job["threads"]),
        "field": job["field"],
        "order": job["order"],
        "hardware_track": job["hardware_track"],
        "timeout_s": job["timeout_s"],
        "status": result.get("status", "error"),
        "exit_code": result.get("exit_code", ""),
        "wall_time_seconds": result.get("wall_time_seconds", "") or f"{elapsed:.6f}",
        "process_wall_time_seconds": f"{elapsed:.6f}",
        "started_at_utc": iso_timestamp(started),
        "finished_at_utc": iso_timestamp(finished),
        "runner_host": platform.node(),
        "runner_os": platform.platform(),
        "runner_processor": runner_processor(),
        "runner_machine": runner_machine(),
        "runner_cpu_count": runner_cpu_count(),
        "runner_word_size": runner_word_size(),
        "runner_python": platform.python_version(),
        "log_ref": log_rel.as_posix(),
        "command": result.get("command", job.get("command", "")),
    }
    write_log_file(track_logs_dir / f"{job['job_id']}.log", row, result.get("stdout", ""), result.get("stderr", ""))
    return row


def write_results(results_path: Path, rows: list[dict[str, str]]) -> None:
    results_path.parent.mkdir(parents=True, exist_ok=True)
    with open(results_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_experiment_bundle(
    track_name: str,
    experiment_path: Path,
    root: Path,
    definition_path: Path,
    results_path: Path,
    logs_dir: Path,
    rows: list[dict[str, str]],
    run_stage: str,
    notes: str,
    replay_command: str,
) -> None:
    experiment_path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "experiment_id": track_name,
        "track": track_name,
        "run_stage": run_stage,
        "generated_at_utc": iso_timestamp(datetime.now(timezone.utc)),
        "definition_path": relative_text(root, definition_path),
        "results_table": relative_text(root, results_path),
        "logs_dir": relative_text(root, logs_dir),
        "row_count": str(len(rows)),
        "software_set": ", ".join(sorted({f"{row['software']} {row['version']}" for row in rows})),
        "instance_set": ", ".join(sorted({row["instance_id"] for row in rows})),
        "shared_field": shared_value(rows, "field"),
        "shared_order": shared_value(rows, "order"),
        "shared_hardware_track": shared_value(rows, "hardware_track"),
        "shared_runner_host": compact_row_values(rows, "runner_host"),
        "shared_runner_os": compact_row_values(rows, "runner_os"),
        "shared_timeout_s": shared_value(rows, "timeout_s"),
        "notes": notes,
        "replay_command": replay_command,
    }

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=OUTPUT_COLUMNS, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)

    lines = [f"{column}: {metadata[column]}" for column in EXPERIMENT_COLUMNS]
    lines.extend(["", "[runs]", buffer.getvalue().rstrip("\n"), ""])
    experiment_path.write_text("\n".join(lines), encoding="utf-8")


def replay_command_for_track(track_name: str, jobs: list[dict[str, str]]) -> str:
    command = f"python bench/benchmark.py {track_name}"
    if any(job.get("runner", "").strip() == "axf4" for job in jobs):
        command += " --axf4-binary PATH_TO_AXF4"
    return command


def run_track(
    track_name: str,
    build_site: bool | None,
    bootstrap: bool | None,
    notes: str | None,
    axf4_binary: str | None,
) -> None:
    root = repo_root()
    canonical_track, track = resolve_track(root, track_name)
    definition_path = track_config_path(root, canonical_track)
    results_path = resolve_path(root, str(track["results"]))
    experiment_path = resolve_path(root, str(track["experiment"]))
    track_logs_dir = resolve_path(root, str(track["logs_dir"]))

    jobs = load_track_jobs(canonical_track, track)
    resolved_axf4_binary = resolve_axf4_binary(
        root,
        axf4_binary,
        required=any(job.get("runner", "").strip() == "axf4" for job in jobs),
    )
    should_bootstrap = bool(track["bootstrap"]) if bootstrap is None else bootstrap
    should_build_site = bool(track["build_site"]) if build_site is None else build_site
    if should_bootstrap and any(job.get("runner", "").strip() == "groebner_jl" for job in jobs):
        try:
            ensure_julia_packages()
        except (OSError, RuntimeError) as exc:
            print(f"Warning: Julia bootstrap skipped: {exc}", file=sys.stderr)

    rows = [run_job(job, canonical_track, root, track_logs_dir, resolved_axf4_binary) for job in jobs]
    write_results(results_path, rows)
    write_experiment_bundle(
        track_name=canonical_track,
        experiment_path=experiment_path,
        root=root,
        definition_path=definition_path,
        results_path=results_path,
        logs_dir=track_logs_dir,
        rows=rows,
        run_stage=str(track["run_stage"]),
        notes=notes or stringify_config_value(track.get("notes")).strip(),
        replay_command=replay_command_for_track(canonical_track, jobs),
    )

    print(f"Wrote {len(rows)} runs to {results_path}")
    print(f"Wrote experiment bundle to {experiment_path}")

    if should_build_site:
        subprocess.run([build_python(root), str(website_build_script(root))], cwd=root, check=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one named benchmark track and optionally rebuild the website.")
    choices = sorted(set(available_tracks(repo_root())) | set(ALIASES))
    parser.add_argument("track", nargs="?", default="test", choices=choices, help="Named benchmark track to run.")
    parser.add_argument("--axf4-binary", help="Path to the axf4 executable. Required when the selected track includes axf4 jobs.")
    parser.add_argument("--build-site", dest="build_site", action="store_true", help="Force a website rebuild after the benchmark finishes.")
    parser.add_argument("--no-build-site", dest="build_site", action="store_false", help="Skip the website rebuild.")
    parser.add_argument("--bootstrap", dest="bootstrap", action="store_true", help="Force Julia dependency bootstrapping before the run.")
    parser.add_argument("--no-bootstrap", dest="bootstrap", action="store_false", help="Skip Julia dependency bootstrapping.")
    parser.add_argument("--notes", help="Override the note stored in the experiment bundle.")
    parser.set_defaults(build_site=None, bootstrap=None)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    run_track(args.track, args.build_site, args.bootstrap, args.notes, args.axf4_binary)


if __name__ == "__main__":
    main()