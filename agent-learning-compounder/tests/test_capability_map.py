from __future__ import annotations

import pathlib
import re
import sys
import unittest
import importlib.util


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
BIN = ROOT / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

from alc_mcp.catalog import MCP_TOOLS


MAP = ROOT / "skills" / "alc-core" / "references" / "capability-map.md"
MID_RE = re.compile(r"\bM\d+\b")

_DASHBOARD_SPEC = importlib.util.spec_from_file_location(
    "alc_dashboard_server",
    ROOT / "skills" / "alc-dashboard" / "server.py",
)
dashboard_server = importlib.util.module_from_spec(_DASHBOARD_SPEC)
assert _DASHBOARD_SPEC and _DASHBOARD_SPEC.loader
_DASHBOARD_SPEC.loader.exec_module(dashboard_server)


def _rows() -> list[dict[str, str]]:
    lines = [line.strip() for line in MAP.read_text(encoding="utf-8").splitlines() if line.startswith("|")]
    header = [cell.strip().lower().replace(" ", "_") for cell in lines[0].strip("|").split("|")]
    rows = []
    for line in lines[2:]:
        values = [cell.strip() for cell in line.strip("|").split("|")]
        rows.append(dict(zip(header, values)))
    return rows


def _is_runnable_cli(value: str) -> bool:
    normalized = value.strip().strip("`")
    token = normalized.split()[0] if normalized else ""
    if not token:
        return False
    if token in {"python", "python3"}:
        parts = normalized.split()
        token = parts[1] if len(parts) > 1 else ""
    if token.startswith("bin/"):
        return (ROOT / token).exists()
    return "/" in token


class CapabilityMapTests(unittest.TestCase):
    def test_dashboard_actions_have_at_least_two_invocation_paths(self) -> None:
        rows = _rows()
        for section in dashboard_server.authored_sections:
            matches = [row for row in rows if row["dashboard_section"] == section]
            self.assertTrue(matches, f"missing dashboard section in capability map: {section}")
            for row in matches:
                count = sum(bool(row[name].strip()) for name in ("command", "mcp_tool", "cli"))
                self.assertGreaterEqual(count, 2, row)

    def test_every_mcp_tool_has_command_or_cli_partner(self) -> None:
        for row in _rows():
            if MID_RE.search(row["mcp_tool"]):
                self.assertTrue(row["command"] or row["cli"], row)

    def test_every_catalog_mid_appears(self) -> None:
        mapped = set()
        for row in _rows():
            mapped.update(MID_RE.findall(row["mcp_tool"]))
        expected = {spec.id for spec in MCP_TOOLS.values()}
        self.assertEqual(expected - mapped, set())

    def test_every_dashboard_section_has_mid_partner(self) -> None:
        rows = _rows()
        for section in dashboard_server.authored_sections:
            partners = [row for row in rows if row["dashboard_section"] == section and MID_RE.search(row["mcp_tool"])]
            self.assertTrue(partners, f"dashboard section lacks M-ID partner: {section}")

    def test_cli_column_names_runnable_entrypoints_not_library_modules(self) -> None:
        for row in _rows():
            cli = row["cli"]
            if not cli:
                continue
            self.assertTrue(_is_runnable_cli(cli), f"CLI entry is not a runnable path: {row}")
            self.assertNotRegex(cli, r"(?<!bin/)\b[a-zA-Z_]\w*\.[a-zA-Z_]\w*\b", row)


if __name__ == "__main__":
    unittest.main()
