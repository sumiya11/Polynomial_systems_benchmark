#!/usr/bin/env python3

from __future__ import annotations

import argparse

import benchmark


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run axf4 across one named experiment directory.")
    parser.add_argument("experiment", nargs="?", default="test", help="Experiment directory under bench/ to use.")
    parser.add_argument("--axf4-binary", required=True, help="Path to the axf4 executable to benchmark.")
    parser.add_argument("--timeout-s", type=float, help="Override the timeout for each single run.")
    parser.add_argument("--memory-limit-gb", type=float, help="Override the memory limit for each single run in gigabytes.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return benchmark.run_named_runner(
        "axf4",
        args.experiment,
        timeout_override=args.timeout_s,
        axf4_binary=args.axf4_binary,
        memory_limit_mb_override=benchmark.memory_limit_mb_from_gb(args.memory_limit_gb),
    )


if __name__ == "__main__":
    raise SystemExit(main())