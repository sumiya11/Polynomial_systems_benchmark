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
python bench/run_axf4.py test --axf4-binary PATH_TO_AXF4
python bench/run_groebner_jl.py test
```

The current layout is intentionally small:

- `bench/benchmark.py`: the experiment orchestrator.
- `bench/run_axf4.py`: run the axf4 backend across one named experiment such as `test`.
- `bench/run_groebner_jl.py`: run the Groebner.jl backend across one named experiment such as `test` or `apply_vs_axf4`.
- `bench/<experiment>/config.json`: the complete experiment definition, including examples, software, timeouts, and optional inline jobs for special cases.
- `website/build.py`: the single website build script.
- `system_tools/`: utilities that operate on the canonical Julia system definitions.
- `results/<track>/runs.tsv`: one TSV table per benchmark result.
- `results/<track>/experiment.txt`: one plaintext experiment bundle per benchmark result.
- `results/<track>/logs/`: raw logs grouped inside each benchmark result directory.

The source `results/` tree intentionally does not keep generated index files. The website build infers experiments directly from the discovered result directories and built-in metadata for the named tracks.

## Benchmark experiments

```text
python bench/benchmark.py test --axf4-binary PATH_TO_AXF4
python bench/benchmark.py apply_vs_axf4 --axf4-binary PATH_TO_AXF4
```

- `test` is the baseline local comparison from `bench/test/`.
- `apply_vs_axf4` compares `Groebner.groebner`, `Groebner.groebner_apply!`, `axf4 -t 1`, and `axf4 -t 8` over the 31-bit prime field `GF(2147483647)`.

Both experiments rebuild the website by default.

The axf4 executable is no longer auto-discovered or built from the repository source tree. Pass the binary you want to benchmark explicitly with `--axf4-binary`. Relative paths are resolved from the repository root, so a repo-local copy still works with `--axf4-binary axgrob/axf4.exe` on Windows.

## Runner-specific loops

For a simpler runner-per-system layout similar to `gamba`, use:

```text
python bench/run_axf4.py test --axf4-binary PATH_TO_AXF4
python bench/run_groebner_jl.py test
python bench/run_groebner_jl.py apply_vs_axf4
```

Feed an experiment directory name such as `test` or `apply_vs_axf4` to these scripts. They use the corresponding `bench/<experiment>/config.json` definition. The Groebner runner script executes every Groebner-based competitor enabled in that experiment, and the axf4 runner requires an explicit executable path.
