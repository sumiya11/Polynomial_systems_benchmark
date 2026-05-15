#!/usr/bin/env python3

from __future__ import annotations

import argparse
import atexit
import shutil
import tempfile
from pathlib import Path


JULIA_WORKER_SOURCE = r'''using AbstractAlgebra
using Groebner

function parse_args(args)
    values = Dict{String, String}()
    index = 1
    while index <= length(args)
        key = args[index]
        if !startswith(key, "--") || index == length(args)
            error("invalid arguments")
        end
        values[key[3:end]] = args[index + 1]
        index += 2
    end
    return values
end

function read_problem(path)
    raw_lines = readlines(path)
    lines = [strip(line) for line in raw_lines if !isempty(strip(line))]
    length(lines) >= 3 || error("input file is too short")
    variable_names = [strip(part) for part in split(lines[1], ",") if !isempty(strip(part))]
    file_char = parse(Int, strip(lines[2]))
    polynomials = [replace(strip(line), r",$" => "") for line in lines[3:end] if !isempty(strip(line))]
    return variable_names, file_char, polynomials
end

function resolve_base_ring(field_spec, file_char)
    text = strip(field_spec)
    if isempty(text)
        text = file_char == 0 ? "QQ" : "GF($(file_char))"
    end
    if uppercase(text) == "QQ" || text == "0"
        return QQ
    end
    match_result = match(r"^GF\((\d+)\)$"i, text)
    match_result === nothing && error("unsupported field specification: $(text)")
    return GF(parse(Int, match_result.captures[1]))
end

function resolve_order(order_name)
    normalized = lowercase(replace(strip(order_name), "-" => ""))
    if normalized in ("degrevlex", "grevlex")
        return DegRevLex()
    elseif normalized == "lex"
        return Lex()
    end
    error("unsupported monomial order: $(order_name)")
end

function build_system(variable_names, polynomials, base_ring)
    ring, generators = polynomial_ring(base_ring, variable_names)
    for (name, generator) in zip(Symbol.(variable_names), generators)
        @eval const $(name) = $generator
    end
    expr = Expr(:vect, [Meta.parse(polynomial) for polynomial in polynomials]...)
    system = Core.eval(@__MODULE__, expr)
    return ring, system
end

function thread_flag(thread_count)
    return max(thread_count, 1)
end

params = parse_args(ARGS)
input_path = params["input"]
field_spec = get(params, "field", "")
order_name = get(params, "order", "degrevlex")
thread_count = parse(Int, get(params, "threads", "1"))
method_name = lowercase(strip(get(params, "method", "groebner")))

variable_names, file_char, polynomials = read_problem(input_path)
base_ring = resolve_base_ring(field_spec, file_char)
ordering = resolve_order(order_name)
_, system = build_system(variable_names, polynomials, base_ring)

if method_name == "groebner"
    groebner(system, ordering=ordering, tasks=thread_flag(thread_count))
    timing = @timed groebner(system, ordering=ordering, tasks=thread_flag(thread_count))
elseif method_name in ("groebner_apply", "groebner_apply!", "apply", "apply!")
    warm_trace, _ = groebner_learn(system, ordering=ordering, tasks=thread_flag(thread_count))
    groebner_apply!(warm_trace, system)

    trace, _ = groebner_learn(system, ordering=ordering, tasks=thread_flag(thread_count))
    timing = @timed groebner_apply!(trace, system)
else
    error("unsupported Groebner.jl method: $(method_name)")
end

println("GBBENCH_WALL_TIME=" * string(timing.time))
println("GBBENCH_BYTES=" * string(timing.bytes))
if isdefined(Base, :pkgversion)
    println("GBBENCH_VERSION=" * string(Base.pkgversion(Groebner)))
end
'''

_WORKER_DIR: Path | None = None


def cleanup_worker_script() -> None:
    global _WORKER_DIR
    if _WORKER_DIR is None:
        return
    shutil.rmtree(_WORKER_DIR, ignore_errors=True)
    _WORKER_DIR = None


def worker_script_path() -> Path:
    global _WORKER_DIR
    if _WORKER_DIR is None:
        _WORKER_DIR = Path(tempfile.mkdtemp(prefix="gbbench-groebner-jl-"))
        atexit.register(cleanup_worker_script)
        (_WORKER_DIR / "groebner_jl_worker.jl").write_text(JULIA_WORKER_SOURCE, encoding="utf-8")
    return _WORKER_DIR / "groebner_jl_worker.jl"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Groebner.jl across one named experiment directory.")
    parser.add_argument("experiment", nargs="?", default="test", help="Experiment directory under bench/ to use.")
    parser.add_argument("--timeout-s", type=float, help="Override the timeout for each single run.")
    parser.add_argument("--bootstrap", dest="bootstrap", action="store_true", help="Force Julia dependency bootstrapping before the run.")
    parser.add_argument("--no-bootstrap", dest="bootstrap", action="store_false", help="Skip Julia dependency bootstrapping.")
    parser.set_defaults(bootstrap=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    import benchmark

    args = build_parser().parse_args(argv)
    return benchmark.run_named_runner("groebner_jl", args.experiment, args.timeout_s, args.bootstrap)


if __name__ == "__main__":
    raise SystemExit(main())