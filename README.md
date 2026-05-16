# Polynomial systems benchmark

This repository powers [GroebnerBenchmark](https://sumiya11.github.io/GroebnerBenchmark).

## Build the website locally

Create and populate a virtual environment if needed:

```text
python -m venv venv
python -m pip install -r requirements.txt
```

Then build the static site:

```text
python website/build.py
```

If the active Python does not have `markdown`, the repository venv also works directly on Windows:

```text
.\venv\Scripts\python.exe website/build.py
```

The generated HTML is written to `build/`.

## Benchmark entrypoint

Benchmarking has one aggregate entrypoint and two public per-runner helpers:

```text
python bench/benchmark.py test --axf4-binary PATH_TO_AXF4
python bench/benchmark.py apply_vs_axf4 --axf4-binary PATH_TO_AXF4
python bench/benchmark.py test --axf4-binary PATH_TO_AXF4 --memory-limit-gb 4
python bench/run_axf4.py test --axf4-binary PATH_TO_AXF4
python bench/run_axf4.py test --axf4-binary PATH_TO_AXF4 --memory-limit-gb 4
python bench/run_groebner_jl.py test
python bench/run_groebner_jl.py test --memory-limit-gb 4
```

The current layout is intentionally small:

- `bench/benchmark.py`: the experiment orchestrator.
- `bench/run_axf4.py`: run the axf4 backend across one named experiment such as `test`.
- `bench/run_groebner_jl.py`: run the Groebner.jl backend across one named experiment such as `test` or `apply_vs_axf4`.
- `bench/<experiment>/config.json`: the complete experiment definition, including examples, software, timeouts, and optional inline jobs for special cases.
- `system_tools/`: utilities that operate on the canonical Julia system definitions.
- `results/<track>/runs.tsv`: one TSV table per benchmark result.
- `results/<track>/experiment.txt`: one plaintext experiment bundle per benchmark result.
- `results/<track>/logs/`: raw logs grouped inside each benchmark result directory.

Each run now records a `peak_memory_mb` field alongside the timing data, and the runner no longer stores SHA digests for the input and system files.

The source `results/` tree intentionally does not keep generated index files. The website build infers experiments directly from the discovered result directories and built-in metadata for the named tracks.

## Benchmark experiments

```text
python bench/benchmark.py test --axf4-binary PATH_TO_AXF4
python bench/benchmark.py apply_vs_axf4 --axf4-binary PATH_TO_AXF4
```

- `test` is the baseline local comparison from `bench/test/`.
- `apply_vs_axf4` compares `Groebner.groebner`, `Groebner.groebner_apply!`, `axf4 -t 1`, and `axf4 -t 8` over the 31-bit prime field `GF(2147483647)`.

An optional `memory_limit_mb` can be set at the experiment level, per example, per generated software entry, or per inline job. The CLI accepts `--memory-limit-gb` to override the per-run limit for one invocation.

Peak memory is tracked per run as an OS-reported peak memory figure in megabytes. On Windows it comes from the Job Object accounting, and on Linux or macOS it comes from the platform `time` tool wrapped around the benchmarked command.

On Linux, the runner now prefers `systemd-run --user` with `MemoryMax=` so the whole benchmarked run sits inside a transient memory-limited scope. If a user systemd manager is not available, it falls back to the existing POSIX `resource` limits, which are closer to a per-process `ulimit`.

The axf4 executable is no longer auto-discovered or built from the repository source tree. Pass the binary you want to benchmark explicitly with `--axf4-binary`. Relative paths are resolved from the repository root, so a repo-local copy still works with `--axf4-binary axgrob/axf4.exe` on Windows.

On Linux or WSL, Groebner.jl runs require a Linux Julia executable. If `PATH` or `JULIA_BINARY` points at a Windows `julia.exe`, the runner now stops early with a setup error instead of emitting per-job Groebner failures.

Groebner.jl runs also assume the Julia environment already has `Groebner` and `AbstractAlgebra` installed. The runner checks that up front, but it no longer tries to install Julia packages automatically.

Automatic machine labels are now the default for `bench/benchmark.py`. A plain run writes to a machine-specific results directory and title, so different hosts do not overwrite one another.

The benchmark runner always derives a deterministic cute label from the local machine fingerprint and uses that for both the results directory and the displayed experiment title.

## Runner-specific loops

For a simpler runner-per-system layout similar to `gamba`, use:

```text
python bench/run_axf4.py test --axf4-binary PATH_TO_AXF4
python bench/run_groebner_jl.py test
python bench/run_groebner_jl.py apply_vs_axf4
```

Feed an experiment directory name such as `test` or `apply_vs_axf4` to these scripts. They use the corresponding `bench/<experiment>/config.json` definition. The Groebner runner script executes every Groebner-based competitor enabled in that experiment, and the axf4 runner requires an explicit executable path.
