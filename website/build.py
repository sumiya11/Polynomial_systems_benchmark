#!/usr/bin/env python3

from __future__ import annotations

import csv
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import markdown
except ModuleNotFoundError:
    markdown = None


SUPPORTED_EXTENSIONS = [".md"]
TRACK_ORDER = ["test", "apply_vs_axf4"]
SUMMARY_COLUMNS = ["profile", "cases", "solved", "wins", "geomean_ratio"]
COLORS = ["#0b6e4f", "#c84c09", "#005f99", "#8f2d56", "#6b8e23", "#6a4c93"]
PROFILE_MIN_BEST_TIME_SECONDS = 0.1
REPO_ROOT = Path(__file__).resolve().parent.parent
WEBSITE_ROOT = Path(__file__).resolve().parent
FALLBACK_EXPERIMENTS = {
    "test": {
        "label": "Baseline test experiment",
        "is_default": True,
        "sort_order": 10,
        "definition_path": "bench/test/config.json",
        "replay_command": "python bench/benchmark.py test",
    },
    "apply_vs_axf4": {
        "label": "Apply vs axf4",
        "is_default": False,
        "sort_order": 20,
        "definition_path": "bench/apply_vs_axf4/config.json",
        "replay_command": "python bench/benchmark.py apply_vs_axf4",
    },
}
EXPERIMENT_INDEX_COLUMNS = [
    "experiment_id",
    "label",
    "is_default",
    "sort_order",
    "definition_path",
    "results_table",
    "experiment_bundle",
    "logs_dir",
    "replay_command",
    "hardware_summary",
]
COMMON_HEAD_PLACEHOLDER = "{{COMMON_HEAD}}"
SITE_HEADER_PLACEHOLDER = "{{SITE_HEADER}}"
SITE_SCRIPTS_PLACEHOLDER = "{{SITE_SCRIPTS}}"
COMMON_HEAD_HTML = """  <meta charset=\"UTF-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
  <link href=\"./resources/css/index.css\" type=\"text/css\" rel=\"stylesheet\">"""
SITE_HEADER_HTML = """<h1>Polynomial systems benchmark</h1>

<div class=\"navbar\" id=\"myNavbar\">
    <a href=\"about.html\">About</a>
    <a href=\"index.html\">Systems</a>
    <a href=\"results.html\">Results</a>
    <a href=\"contribute.html\">Contribute</a>
    <a href=\"https://github.com/sumiya11/Polynomial_systems_benchmark\">GitHub</a>

    <a href=\"javascript:void(0);\"
       class=\"icon\"
       onclick=\"toggleMenu()\">
      &#9776;
    </a>
  </div>"""
SITE_SCRIPTS_HTML = '  <script src="./resources/js/site.js"></script>'

HTML_TEMPLATE = f"""

<!DOCTYPE html>
<html>

<head>
{COMMON_HEAD_PLACEHOLDER}
  <title>Polynomial systems benchmark</title>
</head>

<body>

{SITE_HEADER_PLACEHOLDER}

<@ @>

{SITE_SCRIPTS_PLACEHOLDER}

</body>
</html>
"""


def render_shared_page_fragments(text: str) -> str:
    return (
        text.replace(COMMON_HEAD_PLACEHOLDER, COMMON_HEAD_HTML)
        .replace(SITE_HEADER_PLACEHOLDER, SITE_HEADER_HTML)
        .replace(SITE_SCRIPTS_PLACEHOLDER, SITE_SCRIPTS_HTML)
    )


def render_static_pages(build_dir: Path) -> None:
    for html_path in build_dir.glob("*.html"):
        html_path.write_text(render_shared_page_fragments(html_path.read_text(encoding="utf-8")), encoding="utf-8")


def ensure_markdown() -> None:
    global markdown
    if markdown is not None:
        return

    for candidate in [REPO_ROOT / "venv" / "Scripts" / "python.exe", REPO_ROOT / "venv" / "bin" / "python"]:
        if not candidate.is_file():
            continue

        probe = subprocess.run([str(candidate), "-c", "import markdown"], capture_output=True, text=True)
        if probe.returncode == 0:
            completed = subprocess.run([str(candidate), str(Path(__file__).resolve())])
            raise SystemExit(completed.returncode)

    raise RuntimeError(
        "Cannot build the website because no Python interpreter with the markdown package was found. "
        "Install requirements into the active Python or use the repository venv."
    )


def read_systems_data(systems_dir: Path) -> dict[str, dict[str, str]]:
    print(f"Reading systems from: {systems_dir.resolve().absolute()}")
    systems = {}
    for root in sorted(path for path in systems_dir.iterdir() if path.is_dir()):
        system = root.name
        print(f"  Reading {system}")
        description_path = root / f"{system}{SUPPORTED_EXTENSIONS[0]}"
        systems[system] = {"content": description_path.read_text(encoding="utf-8")}
    return systems


def trim_system_markdown(text: str) -> str:
    lines = text.splitlines()
    heading = next((line for line in lines if line.startswith("### ")), None)
    keywords = next((line for line in lines if line.startswith("- Keywords:")), None)
    try:
        sources_start = lines.index("- Sources:")
    except ValueError:
        sources_start = None

    if heading is None or keywords is None or sources_start is None:
        return text

    source_lines = ["- Sources:"]
    for line in lines[sources_start + 1 :]:
        if line.startswith("- ") and not line.startswith("    - "):
            break
        source_lines.append(line)

    return "\n".join([heading, "", keywords, *source_lines, ""])


def populate_html(systems: dict[str, dict[str, str]]) -> str:
    print("Populating index.html")
    body = "<hr>"
    for system in sorted(systems):
        content = markdown.markdown(trim_system_markdown(systems[system]["content"]))
        content = re.sub(
            "<h3>(.+)</h3>",
            f'<h3 id="{system}"><a href="#{system}" style="color: black">\\g<1></a></h3>',
            content,
        )
        body += f'<div class="container">{content}</div>\n<hr>\n'
    return HTML_TEMPLATE.replace("<@ @>", body)


def load_rows(results_path: Path) -> list[dict[str, str]]:
    with open(results_path, "r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def is_axf4_row(row: dict[str, str]) -> bool:
    return row.get("runner", "").strip() == "axf4" or row.get("software", "").strip().startswith("axf4")


def profile_name(row: dict[str, str]) -> str:
    if is_axf4_row(row):
        return row["software"]
    return f"{row['software']} {row['version']} ({row['threads']}t)"


def problem_name(row: dict[str, str]) -> str:
    return " | ".join([row["instance_id"], row["field"], row["order"], row["hardware_track"]])


def geometric_mean(values: list[float]) -> float:
    if not values:
        return math.inf
    return math.exp(sum(math.log(value) for value in values) / len(values))


def truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y"}


def safe_int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def fallback_experiment_metadata(experiment_id: str) -> dict[str, object]:
    defaults = {
        "label": f"{experiment_id.replace('_', ' ').title()} experiment",
        "is_default": False,
        "sort_order": TRACK_ORDER.index(experiment_id) * 10 if experiment_id in TRACK_ORDER else 9999,
        "definition_path": "",
        "replay_command": f"python bench/benchmark.py {experiment_id}",
    }
    defaults.update(FALLBACK_EXPERIMENTS.get(experiment_id, {}))
    return defaults


def load_experiment_bundle_metadata(experiment_bundle_path: Path) -> dict[str, str]:
    if not experiment_bundle_path.is_file():
        return {}

    metadata: dict[str, str] = {}
    for line in experiment_bundle_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == "[runs]":
            break
        if not stripped or ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()
    return metadata


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


def compute_profile(
    rows: list[dict[str, str]],
) -> tuple[list[float], dict[str, list[tuple[float, float]]], list[dict[str, str]], dict[str, str]]:
    valid_rows = [row for row in rows if row.get("status") == "ok" and row.get("wall_time_seconds")]
    solved_problems: dict[str, list[dict[str, str]]] = {}
    for row in valid_rows:
        solved_problems.setdefault(problem_name(row), []).append(row)

    problems: list[tuple[list[dict[str, str]], float]] = []
    for problem_rows in solved_problems.values():
        best_time = min(float(row["wall_time_seconds"]) for row in problem_rows)
        if best_time <= PROFILE_MIN_BEST_TIME_SECONDS:
            continue
        problems.append((problem_rows, best_time))

    if not problems:
        return [1.0], {}, [], {}

    ratios_by_profile: dict[str, list[float]] = {}
    wins_by_profile: dict[str, int] = {}
    solved_by_profile: dict[str, int] = {}
    software_by_profile: dict[str, str] = {}

    for problem_rows, best_time in problems:
        for row in problem_rows:
            profile = profile_name(row)
            ratio = float(row["wall_time_seconds"]) / best_time
            ratios_by_profile.setdefault(profile, []).append(ratio)
            solved_by_profile[profile] = solved_by_profile.get(profile, 0) + 1
            software_by_profile.setdefault(profile, row["software"])
            if math.isclose(ratio, 1.0, rel_tol=1e-9, abs_tol=1e-12):
                wins_by_profile[profile] = wins_by_profile.get(profile, 0) + 1

    total_cases = len(problems)
    max_ratio = max(max(ratios) for ratios in ratios_by_profile.values())
    upper = max(2.0, max_ratio * 1.05)
    taus = [math.exp(math.log(upper) * index / 79.0) for index in range(80)]
    taus[0] = 1.0

    series: dict[str, list[tuple[float, float]]] = {}
    summary_rows: list[dict[str, str]] = []
    for profile in sorted(ratios_by_profile):
        ratios = sorted(ratios_by_profile[profile])
        points = []
        for tau in taus:
            covered = sum(1 for ratio in ratios if ratio <= tau)
            points.append((tau, covered / total_cases))
        series[profile] = points
        summary_rows.append(
            {
                "profile": profile,
                "cases": str(total_cases),
                "solved": str(solved_by_profile.get(profile, 0)),
                "wins": str(wins_by_profile.get(profile, 0)),
                "geomean_ratio": f"{geometric_mean(ratios):.4f}",
            }
        )
    return taus, series, summary_rows, software_by_profile


def svg_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def estimated_svg_text_width(text: str, font_size: float = 16.0) -> float:
    return max(0.0, len(text) * font_size * 0.58)


def format_tau_tick_label(tick: float) -> str:
    if tick < 10.0:
        return f"{tick:g}"
    return f"{tick:.0f}"


def profile_x_ticks(max_tau: float) -> list[tuple[float, str]]:
    ticks = [tick for tick in [1.0, 1.25, 1.5, 2.0, 3.0, 5.0] if tick <= max_tau]

    scale = 10.0
    while scale <= max_tau * 1.001:
        for multiplier in (1.0, 2.0, 5.0):
            tick = scale * multiplier
            if tick <= max_tau * 1.001:
                ticks.append(tick)
        scale *= 10.0

    return [(tick, format_tau_tick_label(tick)) for tick in ticks]


def render_profile_svg(
    taus: list[float],
    series: dict[str, list[tuple[float, float]]],
    software_by_profile: dict[str, str],
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    legend_labels = sorted(series)
    legend_label_width = max((estimated_svg_text_width(label) for label in legend_labels), default=0.0)
    left = 84
    top = 24
    right = 28
    plot_width = 700
    plot_height = 348
    legend_gap_x = 24
    legend_row_height = 30
    legend_line_width = 30
    legend_text_gap = 10
    legend_cell_width = max(172, int(math.ceil(legend_line_width + legend_text_gap + legend_label_width + 8)))
    legend_columns = 1
    if legend_labels:
        legend_columns = 2 if len(legend_labels) > 1 else 1
    legend_rows = math.ceil(len(legend_labels) / legend_columns) if legend_labels else 0
    legend_block_width = (
        legend_columns * legend_cell_width + max(0, legend_columns - 1) * legend_gap_x if legend_labels else 0
    )
    tick_label_band = 36
    axis_label_band = 30
    legend_gap_top = 18 if legend_rows else 0
    legend_top = top + plot_height + tick_label_band + axis_label_band + legend_gap_top
    height = legend_top + legend_rows * legend_row_height + (20 if legend_rows else 12)
    width = left + max(plot_width, legend_block_width) + right

    if not series:
        output_path.write_text(
            f"<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 {width} {height}\" role=\"img\" aria-labelledby=\"title desc\">\n"
            f"  <title id=\"title\">Performance profile</title>\n"
            f"  <desc id=\"desc\">No profile data was available.</desc>\n"
            f"  <text x=\"{width / 2}\" y=\"{height / 2}\" text-anchor=\"middle\" font-family=\"Helvetica, Arial, sans-serif\" font-size=\"20\" fill=\"#444\">No profile data available</text>\n"
            f"</svg>\n",
            encoding="utf-8",
        )
        return

    max_tau = max(taus)
    log_max = math.log(max_tau)

    def x_coord(tau: float) -> float:
        if log_max == 0:
            return left
        return left + plot_width * math.log(tau) / log_max

    def y_coord(value: float) -> float:
        return top + plot_height * (1.0 - value)

    grid_lines = []
    for y_tick in [0.0, 0.25, 0.5, 0.75, 1.0]:
        y = y_coord(y_tick)
        grid_lines.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_width}" y2="{y:.1f}" stroke="#d8d2c4" stroke-width="1"/>')
        grid_lines.append(f'<text x="{left - 12}" y="{y + 5:.1f}" text-anchor="end" font-size="15" fill="#444">{y_tick:.2f}</text>')

    previous_x_label_right = float("-inf")
    for tick, tick_label in profile_x_ticks(max_tau):
        x = x_coord(tick)
        grid_lines.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + plot_height}" stroke="#ece6da" stroke-width="1"/>')
        label_half_width = estimated_svg_text_width(tick_label, font_size=15.0) / 2.0
        if x - label_half_width <= previous_x_label_right + 8.0:
            continue
        grid_lines.append(
            f'<text x="{x:.1f}" y="{top + plot_height + 28}" text-anchor="middle" font-size="15" fill="#444">{tick_label}</text>'
        )
        previous_x_label_right = x + label_half_width

    paths = []
    legend = []
    legend_origin_x = left + max(0.0, (plot_width - legend_block_width) / 2.0)
    for index, profile in enumerate(sorted(series)):
        color = COLORS[index % len(COLORS)]
        software = software_by_profile.get(profile, profile)
        profile_attr = svg_escape(profile)
        software_attr = svg_escape(software)
        tooltip = svg_escape(f"{profile} | {software}")
        path_commands = []
        for point_index, (tau, value) in enumerate(series[profile]):
            command = "M" if point_index == 0 else "L"
            path_commands.append(f"{command} {x_coord(tau):.2f} {y_coord(value):.2f}")
        paths.append(
            f'<g class="profile-series" data-profile="{profile_attr}" data-software="{software_attr}" tabindex="0">'
            f"<title>{tooltip}</title>"
            f'<path class="profile-series-hitbox" d="{" ".join(path_commands)}" fill="none" stroke="transparent" stroke-width="14"/>'
            f'<path class="profile-series-line" d="{" ".join(path_commands)}" fill="none" stroke="{color}" stroke-width="3"/>'
            f"</g>"
        )
        legend_row = index // legend_columns
        legend_column = index % legend_columns
        legend_x = legend_origin_x + legend_column * (legend_cell_width + legend_gap_x)
        legend_y = legend_top + legend_row * legend_row_height
        legend.append(
            f'<g class="profile-legend-entry" data-profile="{profile_attr}" data-software="{software_attr}" tabindex="0">'
            f"<title>{tooltip}</title>"
            f'<line class="profile-legend-line" x1="{legend_x:.1f}" y1="{legend_y:.1f}" x2="{legend_x + legend_line_width:.1f}" y2="{legend_y:.1f}" stroke="{color}" stroke-width="4"/>'
            f'<text class="profile-legend-label" x="{legend_x + legend_line_width + legend_text_gap:.1f}" y="{legend_y + 6:.1f}" font-size="16" fill="#222">{svg_escape(profile)}</text>'
            f"</g>"
        )

    output_path.write_text(
        f"<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 {width} {height}\" role=\"img\" aria-labelledby=\"title desc\" class=\"interactive-profile-svg\">\n"
        f"  <title id=\"title\">Performance profile</title>\n"
        f"  <desc id=\"desc\">Fraction of cases with best runtime above {PROFILE_MIN_BEST_TIME_SECONDS:g} seconds solved within a factor tau of the best runtime.</desc>\n"
        f"  <rect x=\"{left}\" y=\"{top}\" width=\"{plot_width}\" height=\"{plot_height}\" fill=\"none\" stroke=\"#b7ae98\" stroke-width=\"1.5\"/>\n"
        f"  {''.join(grid_lines)}\n"
        f"  {''.join(paths)}\n"
        f"  {''.join(legend)}\n"
        f"  <text x=\"{left + plot_width / 2}\" y=\"{top + plot_height + tick_label_band + 18}\" text-anchor=\"middle\" font-size=\"16\" fill=\"#333\">tau = runtime / best-runtime-on-case</text>\n"
        f"  <text x=\"26\" y=\"{top + plot_height / 2}\" text-anchor=\"middle\" transform=\"rotate(-90 26 {top + plot_height / 2})\" font-size=\"16\" fill=\"#333\">fraction of cases</text>\n"
        f"</svg>\n",
        encoding="utf-8",
    )


def write_summary(output_path: Path, rows: list[dict[str, str]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_COLUMNS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build_profile_assets(results_path: Path, output_svg: Path, output_summary: Path) -> None:
    taus, series, summary_rows, software_by_profile = compute_profile(load_rows(results_path))
    render_profile_svg(taus, series, software_by_profile, output_svg)
    write_summary(output_summary, summary_rows)


def discover_result_tracks(results_dir: Path) -> list[tuple[str, Path]]:
    discovered = {}
    for path in results_dir.glob("*/runs.tsv"):
        discovered[path.parent.name] = path

    ordered = []
    for track_name in TRACK_ORDER:
        if track_name in discovered:
            ordered.append((track_name, discovered.pop(track_name)))
    for track_name in sorted(discovered):
        ordered.append((track_name, discovered[track_name]))
    return ordered


def load_experiment_registry(build_root: Path, build_results_dir: Path) -> list[dict[str, object]]:
    build_root = build_root.resolve()
    build_results_dir = build_results_dir.resolve()
    registry_path = build_root / "results" / "index.tsv"
    discovered_results = {experiment_id: path for experiment_id, path in discover_result_tracks(build_results_dir)}
    registry_rows: list[dict[str, str]] = []

    if registry_path.is_file():
        with open(registry_path, "r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            for row in reader:
                normalized_row = {column: row.get(column, "") for column in EXPERIMENT_INDEX_COLUMNS}
                if not normalized_row.get("definition_path", "").strip():
                    normalized_row["definition_path"] = row.get("jobs_manifest", "")
                registry_rows.append(normalized_row)

    experiments: list[dict[str, object]] = []
    used_ids: set[str] = set()
    for row in registry_rows:
        experiment_id = row.get("experiment_id", "").strip()
        if not experiment_id:
            continue

        fallback = fallback_experiment_metadata(experiment_id)
        experiment_bundle = row.get("experiment_bundle", "").strip() or f"results/{experiment_id}/experiment.txt"
        bundle_metadata = load_experiment_bundle_metadata(build_root / experiment_bundle)

        results_table = row.get("results_table", "").strip() or f"results/{experiment_id}/runs.tsv"
        results_path = build_root / Path(results_table)
        if not results_path.is_file():
            fallback_path = discovered_results.get(experiment_id)
            if fallback_path is None:
                continue
            results_path = fallback_path
            results_table = results_path.relative_to(build_root).as_posix()

        experiment_rows = load_rows(results_path)

        experiments.append(
            {
                "experiment_id": experiment_id,
                "label": row.get("label", "").strip() or bundle_metadata.get("label", "").strip() or str(fallback["label"]),
                "is_default": truthy(row.get("is_default", "")) if row.get("is_default", "").strip() else bool(fallback["is_default"]),
                "sort_order": safe_int(row.get("sort_order", ""), int(fallback["sort_order"])),
                "definition_path": row.get("definition_path", "").strip() or bundle_metadata.get("definition_path", "").strip() or str(fallback["definition_path"]),
                "results_table": results_table,
                "experiment_bundle": experiment_bundle,
                "logs_dir": row.get("logs_dir", "").strip() or bundle_metadata.get("logs_dir", "").strip() or f"results/{experiment_id}/logs",
                "replay_command": row.get("replay_command", "").strip() or bundle_metadata.get("replay_command", "").strip() or str(fallback["replay_command"]),
                "hardware_summary": row.get("hardware_summary", "").strip() or hardware_summary(experiment_rows),
            }
        )
        used_ids.add(experiment_id)

    for experiment_id, results_path in discover_result_tracks(build_results_dir):
        if experiment_id in used_ids:
            continue
        experiment_rows = load_rows(results_path)
        fallback = fallback_experiment_metadata(experiment_id)
        experiment_bundle = f"results/{experiment_id}/experiment.txt"
        bundle_metadata = load_experiment_bundle_metadata(build_root / experiment_bundle)
        experiments.append(
            {
                "experiment_id": experiment_id,
                "label": bundle_metadata.get("label", "").strip() or str(fallback["label"]),
                "is_default": bool(fallback["is_default"]),
                "sort_order": int(fallback["sort_order"]),
                "definition_path": bundle_metadata.get("definition_path", "").strip() or str(fallback["definition_path"]),
                "results_table": results_path.relative_to(build_root).as_posix(),
                "experiment_bundle": experiment_bundle,
                "logs_dir": bundle_metadata.get("logs_dir", "").strip() or f"results/{experiment_id}/logs",
                "replay_command": bundle_metadata.get("replay_command", "").strip() or str(fallback["replay_command"]),
                "hardware_summary": hardware_summary(experiment_rows),
            }
        )

    experiments.sort(key=lambda experiment: (int(experiment["sort_order"]), str(experiment["experiment_id"])))
    return experiments
def default_experiment_id(experiments: list[dict[str, object]]) -> str:
    for experiment in experiments:
        if bool(experiment.get("is_default")):
            return str(experiment["experiment_id"])
    for preferred_id in ["test"]:
        for experiment in experiments:
            if experiment.get("experiment_id") == preferred_id:
                return str(experiment["experiment_id"])
    return str(experiments[0]["experiment_id"]) if experiments else ""


def build_track_assets(
    build_root: Path,
    build_results_dir: Path,
    build_resources_dir: Path,
) -> tuple[list[dict[str, object]], dict[str, str], dict[str, str], dict[str, str], str]:
    experiments = load_experiment_registry(build_root, build_results_dir)
    embedded_runs = {}
    embedded_summaries: dict[str, str] = {}
    embedded_profiles: dict[str, str] = {}

    for experiment in experiments:
        experiment_id = str(experiment["experiment_id"])
        runs_path = build_root / str(experiment["results_table"])
        summary_path = build_results_dir / f"profile_summary_{experiment_id}.tsv"
        svg_path = build_resources_dir / f"performance_profile_{experiment_id}.svg"
        build_profile_assets(runs_path, svg_path, summary_path)
        experiment["results_path"] = f"./{experiment['results_table']}"
        experiment["summary_path"] = f"./results/profile_summary_{experiment_id}.tsv"
        experiment["profile_path"] = f"./resources/generated/performance_profile_{experiment_id}.svg"
        experiment["experiment_path"] = f"./{experiment['experiment_bundle']}"
        experiment["logs_path"] = f"./{str(experiment['logs_dir']).rstrip('/')}/index.html"
        embedded_runs[experiment_id] = runs_path.read_text(encoding="utf-8")

    default_id = default_experiment_id(experiments)
    if experiments:
        alias_experiment_id = default_id or str(experiments[0]["experiment_id"])
        shutil.copyfile(build_resources_dir / f"performance_profile_{alias_experiment_id}.svg", build_resources_dir / "performance_profile.svg")
        shutil.copyfile(build_results_dir / f"profile_summary_{alias_experiment_id}.tsv", build_results_dir / "profile_summary.tsv")

    for experiment in experiments:
        experiment["is_default"] = str(experiment["experiment_id"]) == default_id

    return experiments, embedded_runs, embedded_summaries, embedded_profiles, default_id


def embed_results_data(
    results_html_path: Path,
    embedded_experiments: list[dict[str, object]],
    embedded_runs: dict[str, str],
    embedded_summaries: dict[str, str],
    embedded_profiles: dict[str, str],
    default_experiment: str,
) -> None:
    page = results_html_path.read_text(encoding="utf-8")
    page = page.replace(
        '<script id="embeddedExperiments" type="application/json">[]</script>',
        f'<script id="embeddedExperiments" type="application/json">{json.dumps(embedded_experiments)}</script>',
    )
    page = page.replace(
        '<script id="embeddedTrackRuns" type="application/json">{}</script>',
        f'<script id="embeddedTrackRuns" type="application/json">{json.dumps(embedded_runs)}</script>',
    )
    page = page.replace(
        '<script id="embeddedTrackSummaries" type="application/json">{}</script>',
        f'<script id="embeddedTrackSummaries" type="application/json">{json.dumps(embedded_summaries)}</script>',
    )
    page = page.replace(
        '<script id="embeddedTrackProfiles" type="application/json">{}</script>',
        f'<script id="embeddedTrackProfiles" type="application/json">{json.dumps(embedded_profiles)}</script>',
    )
    page = page.replace(
        '<script id="embeddedDefaultExperimentId" type="application/json">""</script>',
        f'<script id="embeddedDefaultExperimentId" type="application/json">{json.dumps(default_experiment)}</script>',
    )
    results_html_path.write_text(page, encoding="utf-8")


def write_build(build_dir: Path, systems_dir: Path, sources_dir: Path, results_dir: Path, html: str) -> None:
    print(f"Writing build files to: {build_dir.resolve().absolute()}")
    if build_dir.exists():
        shutil.rmtree(build_dir)

    build_dir.mkdir(parents=True)
    shutil.copytree(systems_dir, build_dir / systems_dir.stem)
    shutil.copytree(results_dir, build_dir / results_dir.stem)
    shutil.copytree(sources_dir, build_dir, dirs_exist_ok=True)
    render_static_pages(build_dir)

    embedded_experiments, embedded_runs, embedded_summaries, embedded_profiles, default_experiment = build_track_assets(
        build_dir,
        build_dir / results_dir.stem,
        build_dir / "resources" / "generated",
    )
    embed_results_data(
        build_dir / "results.html",
        embedded_experiments,
        embedded_runs,
        embedded_summaries,
        embedded_profiles,
        default_experiment,
    )
    (build_dir / "index.html").write_text(render_shared_page_fragments(html), encoding="utf-8")



def main(systems_dir: Path, sources_dir: Path, results_dir: Path, build_dir: Path) -> None:
    ensure_markdown()
    systems = read_systems_data(systems_dir)
    html = populate_html(systems)
    write_build(build_dir, systems_dir, sources_dir, results_dir, html)


if __name__ == "__main__":
    main(
        systems_dir=REPO_ROOT / "systems",
        sources_dir=WEBSITE_ROOT,
        results_dir=REPO_ROOT / "results",
        build_dir=REPO_ROOT / "build",
    )
