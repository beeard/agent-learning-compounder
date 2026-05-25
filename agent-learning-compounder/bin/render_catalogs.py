#!/usr/bin/env python3
"""Render catalog markdown from Python registries (KTD-20)."""

from __future__ import annotations

import argparse
import importlib
import json
import pathlib
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "skills"


def _to_entries(obj: Any) -> list[dict[str, Any]]:
    if obj is None:
        return []
    if isinstance(obj, dict):
        return list(obj.values())
    if isinstance(obj, (list, tuple)):
        return [item for item in obj if isinstance(item, dict)]
    return []


def _safe_get(entry: dict[str, Any], name: str, default: str = "") -> Any:
    return entry.get(name, default)


def _readme_header(name: str, source: str) -> str:
    return (
        f"# {name}\n"
        "\n"
        "Generated from Python registry:\n"
        f"`{source}`\n"
        "\n"
    )


def _render_table(entries: list[dict[str, Any]], headers: list[str]) -> str:
    if not entries:
        return ""
    header = "| " + " | ".join(headers) + " |\n"
    sep = "| " + " | ".join("---" for _ in headers) + " |\n"
    rows: list[str] = []
    for entry in entries:
        values = []
        for header_name in headers:
            value = _safe_get(entry, header_name, "")
            if isinstance(value, (dict, list)):
                value = json.dumps(value, sort_keys=True)
            values.append(str(value).replace("|", "\\|"))
        rows.append("| " + " | ".join(values) + " |")
    return header + sep + "\n".join(rows) + "\n"


def _render_catalog(name: str, module_path: str, attr: str, output_path: pathlib.Path) -> tuple[str, int]:
    module = importlib.import_module(module_path)
    entries = _to_entries(getattr(module, attr))
    if not entries:
        raise RuntimeError(f"{module_path}.{attr} was empty or unsupported")

    headers = ["id", "kind", "summary", "backing", "version"]
    body = _render_table(entries, headers)
    payload = _readme_header(name, f"{module_path}.{attr}") + body
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(payload, encoding="utf-8")
    return (str(output_path), len(entries))


def _default_specs() -> list[tuple[str, str, str, pathlib.Path]]:
    return [
        ("mcp-catalog", "alc_mcp.catalog", "MCP_TOOLS", ROOT / "skills" / "alc-core" / "references" / "mcp-catalog.md"),
        ("query-catalog", "bin.analyst_queries", "QUERIES", ROOT / "skills" / "alc-core" / "references" / "analyst-queries-catalog.md"),
        ("generator-catalog", "bin.recommender_generators", "GENERATORS", ROOT / "skills" / "alc-core" / "references" / "generator-catalog.md"),
        ("propose-catalog", "bin.analyst_queries", "PROPOSALS", ROOT / "skills" / "alc-core" / "references" / "propose-catalog.md"),
    ]


def render_catalogs(specs: list[tuple[str, str, str, pathlib.Path]] | None = None) -> list[tuple[str, int]]:
    catalog_specs = specs or _default_specs()
    rendered: list[tuple[str, int]] = []
    for name, module_name, attr, output in catalog_specs:
        try:
            path, count = _render_catalog(name, module_name, attr, pathlib.Path(output))
            rendered.append((path, count))
        except ModuleNotFoundError:
            # Optional registries may not exist yet in early phases.
            continue
    return rendered


def render_all(specs: list[tuple[str, str, str, pathlib.Path]] | None = None) -> list[tuple[str, int]]:
    return render_catalogs(specs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Reserved for drift check mode")
    args = parser.parse_args(argv)

    rendered = render_all()
    for path, count in rendered:
        print(f"rendered {path}: {count}")
    if not rendered:
        print("rendered 0 catalogs: no registries discovered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
