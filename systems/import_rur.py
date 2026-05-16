#!/usr/bin/env python3

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = REPO_ROOT / "RationalUnivariateRepresentation.jl" / "Data" / "Systems"
TARGET_DIR = REPO_ROOT / "systems"

SKIP_STEMS = {
    "benchmark",
    "chandra10",
    "chandra11",
    "eco10",
    "eco11",
    "eco12",
    "eco13",
    "eco14",
    "goodwin",
    "katsura9",
    "katsura11",
    "katsura12",
    "katsura13",
    "katsura14",
    "noon6",
    "noon7",
}


def target_slug(source_stem: str) -> str:
    return source_stem.lower()


def function_name(source_stem: str) -> str:
    sanitized = re.sub(r"[^0-9a-zA-Z_]", "_", source_stem.lower())
    if sanitized and sanitized[0].isdigit():
        sanitized = f"system_{sanitized}"
    return f"rur_{sanitized}"


def convert_body(source_text: str) -> str:
    stripped = source_text.lstrip()
    if not stripped:
        raise ValueError("empty source file")

    lines = stripped.splitlines()
    ring_line = lines[0]
    ring_line = re.sub(r"^\s*R\s*,", "_,", ring_line, count=1)
    ring_line, replacements = re.subn(
        r"polynomial_ring\(\s*QQ\s*,",
        "AbstractAlgebra.polynomial_ring(AbstractAlgebra.QQ,",
        ring_line,
        count=1,
    )
    if replacements != 1:
        raise ValueError("unexpected polynomial_ring declaration")
    ring_line = ring_line.replace(",ordering=", ",internal_ordering=")

    return "\n".join([ring_line, *lines[1:]])


def title_for(source_stem: str) -> str:
    return source_stem


def markdown_for(slug: str, source_stem: str) -> str:
    return f"""### {title_for(source_stem)}

- Keywords: system solving.
- Sources:
    - [{slug}.jl](./systems/{slug}/{slug}.jl)
    - [{slug}.txt](./systems/{slug}/txt/{slug}.txt)
"""


def julia_wrapper(source_stem: str, source_text: str) -> str:
    body = convert_body(source_text)
    indented_body = "\n".join(f"    {line}" if line else "" for line in body.splitlines())
    return f"""function {function_name(source_stem)}()
{indented_body}
    sys
end
"""


def import_system(source_path: Path) -> None:
    source_stem = source_path.stem
    slug = target_slug(source_stem)
    target_dir = TARGET_DIR / slug
    if target_dir.exists():
        print(f"Skipping existing target: {target_dir.relative_to(REPO_ROOT)}")
        return

    source_text = source_path.read_text(encoding="utf-8")
    target_dir.mkdir(parents=True, exist_ok=False)
    (target_dir / f"{slug}.jl").write_text(julia_wrapper(source_stem, source_text), encoding="utf-8")
    (target_dir / f"{slug}.md").write_text(markdown_for(slug, source_stem), encoding="utf-8")
    print(f"Imported {source_stem} -> systems/{slug}")


def main() -> None:
    if not SOURCE_DIR.is_dir():
        raise SystemExit(f"Missing source directory: {SOURCE_DIR}")

    for source_path in sorted(SOURCE_DIR.glob("*.jl")):
        if source_path.stem in SKIP_STEMS:
            continue
        import_system(source_path)


if __name__ == "__main__":
    main()