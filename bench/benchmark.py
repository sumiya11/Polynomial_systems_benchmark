#!/usr/bin/env python3

from __future__ import annotations

import argparse
from collections import Counter
import csv
import dataclasses
import functools
import hashlib
import importlib.util
import io
import json
import math
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
    "input_ref",
    "software",
    "version",
    "runner",
    "threads",
    "field",
    "order",
    "hardware_track",
    "timeout_s",
    "memory_limit_mb",
    "peak_memory_mb",
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
    "label",
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
    "shared_memory_limit_mb",
    "shared_peak_memory_mb",
    "notes",
    "replay_command",
]

TRACK_CONFIG_NAME = "config.json"
TRACK_REQUIRED_KEYS = [
    "examples",
    "software",
    "label",
]

ALIASES = {
    "local": "test",
    "small": "test",
    "published": "test",
}

GF_PATTERN = re.compile(r"^GF\((\d+)\)$", re.IGNORECASE)
GBBENCH_TIME_PATTERN = re.compile(r"^GBBENCH_WALL_TIME=(.+)$", re.MULTILINE)
GBBENCH_VERSION_PATTERN = re.compile(r"^GBBENCH_VERSION=(.+)$", re.MULTILINE)
CUTE_MACHINE_ADJECTIVES = [
    "Amber",
    "Brisk",
    "Cloudy",
    "Dapper",
    "Gentle",
    "Lucky",
    "Merry",
    "Misty",
    "Nimble",
    "Pebble",
    "Quiet",
    "Sandy",
    "Silver",
    "Sleepy",
    "Snowy",
    "Sunny",
    "Velvet",
    "Willow",
]
CUTE_MACHINE_COLORS = [
    "Aqua",
    "Berry",
    "Cedar",
    "Coral",
    "Ember",
    "Honey",
    "Ivory",
    "Juniper",
    "Maple",
    "Moss",
    "Ocean",
    "Olive",
    "Saffron",
    "Sky",
    "Slate",
    "Walnut",
]
CUTE_MACHINE_ANIMALS = [
    "Badger",
    "Fox",
    "Heron",
    "Lynx",
    "Marten",
    "Otter",
    "Panda",
    "Quail",
    "Raccoon",
    "Seal",
    "Stoat",
    "Swift",
    "Tern",
    "Walrus",
    "Wren",
    "Yak",
]


@dataclasses.dataclass(frozen=True)
class TrackOutputLayout:
    output_track: str
    machine_label: str | None
    experiment_title: str
    results_path: Path
    experiment_path: Path
    logs_dir: Path


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


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


def slugify_track_fragment(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")
    if not slug:
        raise ValueError("Machine label must contain at least one ASCII letter or digit")
    return slug


def slugify_job_fragment(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    if not slug:
        raise ValueError("Generated software entries must contain at least one ASCII letter or digit")
    return slug


def output_track_name(track_name: str, machine_label: str | None) -> str:
    label = (machine_label or "").strip()
    if not label:
        return track_name
    return f"{track_name}__{slugify_track_fragment(label)}"


def output_track_paths(root: Path, output_track: str) -> tuple[Path, Path, Path]:
    results_dir = root / "results" / output_track
    return results_dir / "runs.tsv", results_dir / "experiment.txt", results_dir / "logs"


def machine_label_seed() -> str:
    parts = [
        platform.node(),
        runner_os(),
        platform.release(),
        runner_processor(),
        runner_machine(),
        runner_cpu_count(),
        str(struct.calcsize("P") * 8),
    ]
    return " | ".join(part.strip() for part in parts if part and part.strip())


def automatic_machine_label() -> str:
    seed = machine_label_seed() or "gbbench-machine"
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    adjective = CUTE_MACHINE_ADJECTIVES[digest[0] % len(CUTE_MACHINE_ADJECTIVES)]
    color = CUTE_MACHINE_COLORS[digest[1] % len(CUTE_MACHINE_COLORS)]
    animal = CUTE_MACHINE_ANIMALS[digest[2] % len(CUTE_MACHINE_ANIMALS)]
    return f"{adjective} {color} {animal}"


def track_config_path(root: Path, track_name: str) -> Path:
    return root / "bench" / track_name / TRACK_CONFIG_NAME


def inferred_track_defaults(track_name: str) -> dict[str, object]:
    results_dir = Path("results") / track_name
    return {
        "results": (results_dir / "runs.tsv").as_posix(),
        "experiment": (results_dir / "experiment.txt").as_posix(),
        "logs_dir": (results_dir / "logs").as_posix(),
        "run_stage": "benchmark",
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


def iso_timestamp(now: datetime) -> str:
    return now.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_optional_positive_int_text(value: object, field_name: str) -> str:
    text = stringify_config_value(value).strip()
    if not text:
        return ""
    try:
        normalized = int(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a positive integer") from exc
    if normalized <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return str(normalized)


def parse_optional_positive_int_text(value: str | None, field_name: str) -> int | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        normalized = int(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a positive integer") from exc
    if normalized <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return normalized


def clean_hardware_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def normalize_machine_architecture(value: object) -> str:
    cleaned = clean_hardware_text(value)
    if not cleaned:
        return ""

    lowered = cleaned.lower()
    aliases = {
        "amd64": "x86_64",
        "x86_64": "x86_64",
        "x64": "x86_64",
        "arm64": "aarch64",
        "aarch64": "aarch64",
        "x86": "i686",
        "i386": "i686",
        "i686": "i686",
    }
    return aliases.get(lowered, cleaned)


def runner_os() -> str:
    system = clean_hardware_text(platform.system())
    if system == "Darwin":
        return "macOS"
    if system:
        return system
    if os.name == "nt":
        return "Windows"
    if sys.platform.startswith("linux"):
        return "Linux"
    return clean_hardware_text(sys.platform)


def _windows_cpu_brand() -> str:
    if os.name != "nt":
        return ""

    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            return clean_hardware_text(value)
    except OSError:
        return ""


def _linux_cpu_brand() -> str:
    if not sys.platform.startswith("linux"):
        return ""

    cpuinfo = Path("/proc/cpuinfo")
    if not cpuinfo.is_file():
        return ""

    candidates: dict[str, str] = {}
    for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        normalized_key = key.strip().lower()
        cleaned_value = clean_hardware_text(value)
        if cleaned_value and normalized_key not in candidates:
            candidates[normalized_key] = cleaned_value

    for key in ("model name", "hardware", "processor"):
        value = candidates.get(key, "")
        if value and not value.isdigit():
            return value
    return ""


def _macos_cpu_brand() -> str:
    if sys.platform != "darwin":
        return ""

    for query in ("machdep.cpu.brand_string", "hw.model"):
        try:
            completed = subprocess.run(
                ["sysctl", "-n", query],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if completed.returncode == 0:
            value = clean_hardware_text(completed.stdout)
            if value:
                return value
    return ""


@functools.lru_cache(maxsize=1)
def runner_processor() -> str:
    values = [
        _windows_cpu_brand(),
        _linux_cpu_brand(),
        _macos_cpu_brand(),
        os.environ.get("PROCESSOR_IDENTIFIER", ""),
        platform.processor(),
        platform.uname().processor,
        platform.machine(),
    ]
    for value in values:
        cleaned = clean_hardware_text(value)
        if cleaned:
            return cleaned
    return ""


@functools.lru_cache(maxsize=1)
def runner_machine() -> str:
    values = [platform.machine(), platform.uname().machine]
    for value in values:
        cleaned = normalize_machine_architecture(value)
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


def julia_binary() -> str:
    binary = os.environ.get("JULIA_BINARY") or shutil.which("julia") or shutil.which("julia.exe")
    if binary and sys.platform.startswith("linux") and Path(binary).suffix.lower() == ".exe":
        raise FileNotFoundError(
            "Found a Windows Julia executable while running on Linux/WSL. "
            "Install a Linux Julia in WSL or set JULIA_BINARY to that Linux executable."
        )
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


def default_version_for_runner(runner_name: str, configured_version: str) -> str:
    if runner_name == "groebner_jl":
        return groebner_jl_version() or configured_version
    if runner_name == "axf4":
        return configured_version or "local-copy"
    return configured_version


def ensure_groebner_runtime() -> None:
    julia = julia_binary()
    check = subprocess.run(
        [julia, "--startup-file=no", "-e", "using Groebner, AbstractAlgebra"],
        capture_output=True,
        text=True,
    )
    if check.returncode != 0:
        raise RuntimeError(
            "Julia runtime is missing required packages for Groebner.jl benchmarking.\n"
            f"stdout:\n{check.stdout}\n"
            f"stderr:\n{check.stderr}"
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


def command_text(command: list[str] | str) -> str:
    if isinstance(command, str):
        return command
    return format_command(command)


def coerce_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def memory_limit_bytes(memory_limit_mb: int | None) -> int | None:
    if memory_limit_mb is None:
        return None
    return memory_limit_mb * 1024 * 1024


def memory_limit_mb_from_gb(memory_limit_gb: float | None) -> int | None:
    if memory_limit_gb is None:
        return None
    if memory_limit_gb <= 0:
        raise ValueError("memory_limit_gb must be positive")
    return max(1, math.ceil(memory_limit_gb * 1024))


def limit_process_address_space(memory_limit_mb: int):
    limit_bytes = memory_limit_bytes(memory_limit_mb)
    if limit_bytes is None:
        return None

    def apply_limit() -> None:
        import resource

        for name in ("RLIMIT_AS", "RLIMIT_DATA", "RLIMIT_RSS"):
            if hasattr(resource, name):
                resource.setrlimit(getattr(resource, name), (limit_bytes, limit_bytes))

    return apply_limit


def run_captured_subprocess(
    command: list[str] | str,
    cwd: Path,
    timeout_s: float | None,
    env: dict[str, str],
    shell: bool = False,
    memory_limit_mb: int | None = None,
) -> subprocess.CompletedProcess[str]:
    if os.name == "nt":
        import benchmark_windows

        return benchmark_windows.run_process(command, cwd, timeout_s, env, shell, memory_limit_mb)

    if sys.platform.startswith("linux"):
        import benchmark_linux

        return benchmark_linux.run_process(command, cwd, timeout_s, env, shell, memory_limit_mb)

    if sys.platform == "darwin":
        import benchmark_macos

        return benchmark_macos.run_process(command, cwd, timeout_s, env, shell, memory_limit_mb)

    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        env=env,
        shell=shell,
        preexec_fn=limit_process_address_space(memory_limit_mb),
    )
    completed.peak_memory_mb = None
    return completed


def run_process(
    command: list[str],
    cwd: Path,
    timeout_s: float | None,
    env: dict[str, str] | None = None,
    memory_limit_mb: int | None = None,
) -> dict[str, str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    completed = run_captured_subprocess(
        command,
        cwd,
        timeout_s,
        merged_env,
        memory_limit_mb=memory_limit_mb,
    )
    return {
        "status": "ok" if completed.returncode == 0 else "error",
        "exit_code": str(completed.returncode),
        "stdout": coerce_text(completed.stdout),
        "stderr": coerce_text(completed.stderr),
        "peak_memory_mb": stringify_config_value(getattr(completed, "peak_memory_mb", None)),
        "command": command_text(command),
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
    memory_limit_mb: int | None = None,
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
        result = run_process(command, root, timeout_s, memory_limit_mb=memory_limit_mb)

    result["runner"] = "axf4"
    result["threads"] = configured_threads
    return result


def run_groebner_jl(
    job: dict[str, str],
    root: Path,
    input_path: Path,
    timeout_s: float | None,
    memory_limit_mb: int | None = None,
) -> dict[str, str]:
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
    result = run_process(command, root, timeout_s, env={"JULIA_NUM_THREADS": threads}, memory_limit_mb=memory_limit_mb)
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


def main_refs_for_system(system_id: str) -> tuple[str, str, str]:
    system_ref = f"systems/{system_id}/{system_id}.md"
    input_ref = f"systems/{system_id}/txt/{system_id}.txt"
    return system_id, system_ref, input_ref


def default_refs_for_instance(instance_id: str, system_id: str | None = None) -> tuple[str, str, str]:
    inferred_system_id, suffix = split_instance_id(instance_id)
    resolved_system_id = stringify_config_value(system_id).strip() or inferred_system_id
    system_ref = f"systems/{resolved_system_id}/{resolved_system_id}.md"
    input_ref = f"systems/{resolved_system_id}/txt/{resolved_system_id}_{suffix}.txt"
    return resolved_system_id, system_ref, input_ref


@functools.lru_cache(maxsize=None)
def default_refs_for_input_name(input_name: str) -> tuple[str, str, str]:
    raw = stringify_config_value(input_name).strip()
    if not raw:
        raise ValueError("Each string example entry must be a non-empty .txt file name")
    if not raw.lower().endswith(".txt"):
        raise ValueError(f"String example entry '{raw}' must end with .txt")

    instance_id = raw[:-4]
    root = repo_root()
    _, main_system_ref, main_input_ref = main_refs_for_system(instance_id)
    main_system_path = resolve_path(root, main_system_ref)
    main_input_path = resolve_path(root, main_input_ref)
    if main_system_path.is_file() and main_input_path.is_file():
        return instance_id, main_system_ref, main_input_ref

    system_id, suffix = split_instance_id(instance_id)
    system_ref = f"systems/{system_id}/{system_id}.md"
    input_ref = f"systems/{system_id}/txt/{system_id}_{suffix}.txt"
    return instance_id, system_ref, input_ref


def stringify_config_value(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def experiment_label(track: dict[str, object], track_name: str, machine_label: str | None) -> str:
    base_label = stringify_config_value(track.get("label")).strip() or track_name.replace("_", " ").title()
    suffix = (machine_label or "").strip()
    if not suffix:
        return base_label
    return f"{base_label} ({suffix})"


def resolve_track_output_layout(
    root: Path,
    track_name: str,
    track: dict[str, object],
) -> TrackOutputLayout:
    resolved_machine_label = automatic_machine_label()
    output_track = output_track_name(track_name, resolved_machine_label)
    results_path, experiment_path, logs_dir = output_track_paths(root, output_track)
    return TrackOutputLayout(
        output_track=output_track,
        machine_label=resolved_machine_label,
        experiment_title=experiment_label(track, track_name, resolved_machine_label),
        results_path=results_path,
        experiment_path=experiment_path,
        logs_dir=logs_dir,
    )


def normalized_example_entry(track: dict[str, object], entry: object) -> dict[str, str]:
    if isinstance(entry, str):
        instance_id, default_system_ref, default_input_ref = default_refs_for_input_name(entry)
        inferred_system_id = instance_id if default_input_ref.endswith(f"/{instance_id}.txt") else split_instance_id(instance_id)[0]
        raw: dict[str, object] = {"instance_id": instance_id}
        derived_system_ref = default_system_ref
        derived_input_ref = default_input_ref
    elif isinstance(entry, dict):
        raw = dict(entry)
        instance_id = stringify_config_value(raw.get("instance_id")).strip()
        if not instance_id:
            raise ValueError("Each example entry must define a non-empty instance_id")
        inferred_system_id, default_system_ref, default_input_ref = default_refs_for_instance(instance_id)
        system_id = stringify_config_value(raw.get("system_id") or inferred_system_id).strip()
        _, derived_system_ref, derived_input_ref = default_refs_for_instance(instance_id, system_id)
    else:
        raise ValueError("Each example entry must be either a string instance id or an object")

    system_id = stringify_config_value(raw.get("system_id") or inferred_system_id).strip()

    return {
        "instance_id": instance_id,
        "system_id": system_id,
        "system_ref": stringify_config_value(raw.get("system_ref") or derived_system_ref or default_system_ref).strip(),
        "input_ref": stringify_config_value(raw.get("input_ref") or derived_input_ref or default_input_ref).strip(),
        "field": stringify_config_value(raw.get("field", track.get("field"))).strip(),
        "order": stringify_config_value(raw.get("order", track.get("order"))).strip(),
        "hardware_track": stringify_config_value(raw.get("hardware_track", track.get("hardware_track"))).strip(),
        "timeout_s": stringify_config_value(raw.get("timeout_s", track.get("timeout_s"))).strip(),
        "memory_limit_mb": normalize_optional_positive_int_text(raw.get("memory_limit_mb", track.get("memory_limit_mb")), "memory_limit_mb"),
    }


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
        "memory_limit_mb": normalize_optional_positive_int_text(entry.get("memory_limit_mb"), "memory_limit_mb"),
    }
    if not software["runner"] and not software["command"]:
        label = software["job_id_suffix"] or software["software"] or software["command"] or "<unknown>"
        raise ValueError(f"Software entry '{label}' must define either a runner or a command")
    return software


def default_generated_job_id_suffix(software: dict[str, str]) -> str:
    runner_name = software["runner"]
    if runner_name == "groebner_jl":
        return slugify_job_fragment(software["method"] or "groebner")
    if runner_name == "axf4":
        return "axf4"
    if software["software"]:
        return slugify_job_fragment(software["software"])
    if runner_name:
        return slugify_job_fragment(runner_name)
    return slugify_job_fragment(software["command"])


def disambiguated_generated_job_id_suffix(base_suffix: str, software: dict[str, str]) -> str:
    threads = software["threads"].strip()
    if threads:
        return slugify_job_fragment(f"{base_suffix} t{threads}")

    for candidate_text in (software["method"], software["software"], software["command"], software["runner"]):
        if not candidate_text:
            continue
        candidate = slugify_job_fragment(candidate_text)
        if candidate != base_suffix:
            return candidate

    return base_suffix


def resolved_generated_software_entries(entries: list[object]) -> list[dict[str, str]]:
    normalized_entries = [normalized_generated_software(entry) for entry in entries]
    initial_suffixes = [entry["job_id_suffix"] or default_generated_job_id_suffix(entry) for entry in normalized_entries]
    initial_counts = Counter(initial_suffixes)
    resolved_entries = []

    for entry, initial_suffix in zip(normalized_entries, initial_suffixes):
        resolved_suffix = entry["job_id_suffix"] or initial_suffix
        if not entry["job_id_suffix"] and initial_counts[initial_suffix] > 1:
            resolved_suffix = disambiguated_generated_job_id_suffix(initial_suffix, entry)
        resolved_entries.append({**entry, "job_id_suffix": resolved_suffix})

    duplicate_suffixes = [
        suffix
        for suffix, count in Counter(entry["job_id_suffix"] for entry in resolved_entries).items()
        if count > 1
    ]
    if duplicate_suffixes:
        raise ValueError(
            "Generated software entries must resolve to unique job_id_suffix values: "
            + ", ".join(sorted(duplicate_suffixes))
        )

    return resolved_entries


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
    software_entries = resolved_generated_software_entries(track.get("software", []))
    jobs = []
    for example in track.get("examples", []):
        normalized_example = normalized_example_entry(track, example)
        for software in software_entries:
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
                "memory_limit_mb": software["memory_limit_mb"] or normalized_example["memory_limit_mb"],
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
        "memory_limit_mb": normalize_optional_positive_int_text(entry.get("memory_limit_mb") or base["memory_limit_mb"], "memory_limit_mb"),
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


def job_memory_limit_mb(job: dict[str, str], override: int | None) -> int | None:
    if override is not None:
        return override
    return parse_optional_positive_int_text(job.get("memory_limit_mb", ""), "memory_limit_mb")


def report_runner_result(result: dict[str, str], elapsed: float) -> int:
    status = result.get("status")
    if status == "timeout":
        print("Timeout")
        return 124
    if status != "ok":
        print(result.get("stderr") or result.get("stdout") or "Run failed")
        return 1

    summary = result.get("wall_time_seconds") or f"{elapsed:.6f}"
    peak_memory_mb = result.get("peak_memory_mb", "").strip()
    if peak_memory_mb:
        summary = f"{summary} {peak_memory_mb}MB"
    print(summary)
    return 0


def run_named_runner(
    runner_name: str,
    track_name: str,
    timeout_override: float | None = None,
    axf4_binary: str | None = None,
    memory_limit_mb_override: int | None = None,
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
        try:
            ensure_groebner_runtime()
        except (OSError, RuntimeError) as exc:
            print(str(exc), file=sys.stderr)
            return 1

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
        memory_limit_mb = job_memory_limit_mb(job, memory_limit_mb_override)
        for attempt in range(3):
            started = time.perf_counter()
            try:
                result = runner(job, root, input_path, timeout_s, memory_limit_mb)
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
    stdout_text = coerce_text(stdout)
    stderr_text = coerce_text(stderr)
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
        f"memory_limit_mb: {row['memory_limit_mb']}",
        f"peak_memory_mb: {row['peak_memory_mb']}",
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
        stdout_text.rstrip(),
        "",
        "[stderr]",
        stderr_text.rstrip(),
        "",
    ]
    log_path.write_text("\n".join(lines), encoding="utf-8")


def run_legacy_command(
    job: dict[str, str],
    root: Path,
    timeout_s: float | None,
    memory_limit_mb: int | None = None,
) -> dict[str, str]:
    completed = run_captured_subprocess(
        job["command"],
        root,
        timeout_s,
        os.environ.copy(),
        shell=True,
        memory_limit_mb=memory_limit_mb,
    )
    return {
        "status": "ok" if completed.returncode == 0 else "error",
        "exit_code": str(completed.returncode),
        "stdout": coerce_text(completed.stdout),
        "stderr": coerce_text(completed.stderr),
        "peak_memory_mb": stringify_config_value(getattr(completed, "peak_memory_mb", None)),
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
    memory_limit_mb_override: int | None = None,
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
    memory_limit_mb = job_memory_limit_mb(job, memory_limit_mb_override)
    runner_name = job.get("runner", "").strip()
    fallback_version = default_version_for_runner(runner_name, job["version"])

    try:
        if runner_name:
            runner = configured_runner(runner_name, axf4_binary)
            result = runner(job, root, input_path, timeout_s, memory_limit_mb)
        else:
            result = run_legacy_command(job, root, timeout_s, memory_limit_mb)
    except subprocess.TimeoutExpired as exc:
        result = {
            "status": "timeout",
            "exit_code": "",
            "stdout": coerce_text(exc.stdout),
            "stderr": coerce_text(exc.stderr),
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
        "input_ref": job["input_ref"],
        "software": result.get("software", job["software"]),
        "version": result.get("version", fallback_version),
        "runner": result.get("runner", job.get("runner", "").strip() or "command"),
        "threads": result.get("threads", job["threads"]),
        "field": job["field"],
        "order": job["order"],
        "hardware_track": job["hardware_track"],
        "timeout_s": job["timeout_s"],
        "memory_limit_mb": str(memory_limit_mb) if memory_limit_mb is not None else "",
        "peak_memory_mb": result.get("peak_memory_mb", ""),
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
    label: str,
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
        "label": label,
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
        "shared_memory_limit_mb": shared_value(rows, "memory_limit_mb"),
        "shared_peak_memory_mb": shared_value(rows, "peak_memory_mb"),
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


def persist_track_outputs(
    layout: TrackOutputLayout,
    root: Path,
    definition_path: Path,
    rows: list[dict[str, str]],
    track: dict[str, object],
    canonical_track: str,
    jobs: list[dict[str, str]],
    memory_limit_gb: float | None,
) -> None:
    write_results(layout.results_path, rows)
    if not rows:
        return

    write_experiment_bundle(
        track_name=layout.output_track,
        label=layout.experiment_title,
        experiment_path=layout.experiment_path,
        root=root,
        definition_path=definition_path,
        results_path=layout.results_path,
        logs_dir=layout.logs_dir,
        rows=rows,
        run_stage=str(track["run_stage"]),
        notes=stringify_config_value(track.get("notes")).strip(),
        replay_command=replay_command_for_track(canonical_track, jobs, memory_limit_gb),
    )


def replay_command_for_track(
    track_name: str,
    jobs: list[dict[str, str]],
    memory_limit_gb: float | None,
) -> str:
    command = ["python", "bench/benchmark.py", track_name]
    if memory_limit_gb is not None:
        command.extend(["--memory-limit-gb", f"{memory_limit_gb:g}"])
    if any(job.get("runner", "").strip() == "axf4" for job in jobs):
        command.extend(["--axf4-binary", "PATH_TO_AXF4"])
    return format_command(command)


def print_run_banner(
    track_name: str,
    layout: TrackOutputLayout,
    job_count: int,
    memory_limit_gb: float | None,
) -> None:
    print(f"Running benchmark track: {track_name}", flush=True)
    if layout.output_track != track_name:
        print(f"Output track: {layout.output_track}", flush=True)
    if layout.machine_label:
        print(f"Machine label: {layout.machine_label}", flush=True)
    print(f"Jobs: {job_count}", flush=True)
    if memory_limit_gb is not None:
        print(f"Memory limit: {memory_limit_gb:g} GB per run", flush=True)
    print(f"Results file: {layout.results_path}", flush=True)


def print_job_progress(index: int, total: int, job: dict[str, str]) -> None:
    software = " ".join(part for part in [job.get("software", "").strip(), job.get("version", "").strip()] if part)
    suffix = f" - {software}" if software else ""
    print(f"[{index}/{total}] {job['job_id']}{suffix}", flush=True)


def print_job_summary(row: dict[str, str]) -> None:
    status = row.get("status", "error")
    wall_time = row.get("wall_time_seconds", "").strip()
    peak_memory_mb = row.get("peak_memory_mb", "").strip()
    summary = status
    details = []
    if wall_time:
        details.append(f"{wall_time}s")
    if peak_memory_mb:
        details.append(f"{peak_memory_mb}MB peak")
    if details:
        summary = f"{summary} ({', '.join(details)})"
    print(f"    {summary}", flush=True)


def run_track(
    track_name: str,
    axf4_binary: str | None,
    memory_limit_gb: float | None,
) -> None:
    root = repo_root()
    canonical_track, track = resolve_track(root, track_name)
    definition_path = track_config_path(root, canonical_track)
    jobs = load_track_jobs(canonical_track, track)
    layout = resolve_track_output_layout(root, canonical_track, track)
    memory_limit_mb = memory_limit_mb_from_gb(memory_limit_gb)
    print_run_banner(canonical_track, layout, len(jobs), memory_limit_gb)
    resolved_axf4_binary = resolve_axf4_binary(
        root,
        axf4_binary,
        required=any(job.get("runner", "").strip() == "axf4" for job in jobs),
    )
    if any(job.get("runner", "").strip() == "groebner_jl" for job in jobs):
        ensure_groebner_runtime()

    rows = []
    persist_track_outputs(layout, root, definition_path, rows, track, canonical_track, jobs, memory_limit_gb)
    for index, job in enumerate(jobs, start=1):
        print_job_progress(index, len(jobs), job)
        row = run_job(job, layout.output_track, root, layout.logs_dir, resolved_axf4_binary, memory_limit_mb)
        rows.append(row)
        persist_track_outputs(layout, root, definition_path, rows, track, canonical_track, jobs, memory_limit_gb)
        print_job_summary(row)

    if not rows:
        write_experiment_bundle(
            track_name=layout.output_track,
            label=layout.experiment_title,
            experiment_path=layout.experiment_path,
            root=root,
            definition_path=definition_path,
            results_path=layout.results_path,
            logs_dir=layout.logs_dir,
            rows=rows,
            run_stage=str(track["run_stage"]),
            notes=stringify_config_value(track.get("notes")).strip(),
            replay_command=replay_command_for_track(canonical_track, jobs, memory_limit_gb),
        )

    print(f"Wrote {len(rows)} runs to {layout.results_path}", flush=True)
    print(f"Wrote experiment bundle to {layout.experiment_path}", flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one named benchmark track.")
    choices = sorted(set(available_tracks(repo_root())) | set(ALIASES))
    parser.add_argument("track", nargs="?", default="test", choices=choices, help="Named benchmark track to run.")
    parser.add_argument("--axf4-binary", help="Path to the axf4 executable. Required when the selected track includes axf4 jobs.")
    parser.add_argument("--memory-limit-gb", type=float, help="Override the memory limit for each run in gigabytes.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_track(args.track, args.axf4_binary, args.memory_limit_gb)


if __name__ == "__main__":
    main()