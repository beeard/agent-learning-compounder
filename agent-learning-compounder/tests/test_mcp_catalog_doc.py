"""Drift guard: reference-lib/mcp-catalog must mirror alc_mcp.catalog.MCP_TOOLS.

The capability-map and capability-parity tests already enforce that the
M-ID set is consistent between the catalog and their respective docs. This
test closes the matching gap for `reference-lib/mcp-catalog`, which is the
human-readable mirror agents read at session start.
"""

from __future__ import annotations

import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alc_mcp.catalog import MCP_TOOLS
from bin import render_catalogs

CATALOG_DOC = ROOT / "reference-lib" / "mcp-catalog"
SKILL_CATALOG_DOC = ROOT / "skills" / "alc-core" / "references" / "mcp-catalog.md"


class MCPCatalogDocTests(unittest.TestCase):
    def test_doc_exists_and_nonempty(self) -> None:
        self.assertTrue(CATALOG_DOC.is_file(), CATALOG_DOC)
        self.assertGreater(CATALOG_DOC.stat().st_size, 0)

    def test_every_catalog_mid_has_row(self) -> None:
        text = CATALOG_DOC.read_text(encoding="utf-8")
        missing = [spec.id for spec in MCP_TOOLS.values() if f"| {spec.id} |" not in text]
        self.assertFalse(missing, f"mcp-catalog.md missing rows for: {missing}")

    def test_every_tool_name_has_row(self) -> None:
        text = CATALOG_DOC.read_text(encoding="utf-8")
        missing = [name for name in MCP_TOOLS if f"`{name}`" not in text]
        self.assertFalse(missing, f"mcp-catalog.md missing tool names: {missing}")

    def test_no_stale_mids_documented(self) -> None:
        import re

        text = CATALOG_DOC.read_text(encoding="utf-8")
        doc_mids = set(re.findall(r"\|\s*(M\d+)\s*\|", text))
        catalog_mids = {spec.id for spec in MCP_TOOLS.values()}
        stale = doc_mids - catalog_mids
        self.assertFalse(stale, f"mcp-catalog.md has rows for retired M-IDs: {stale}")

    def test_reference_catalog_matches_renderer(self) -> None:
        rendered, count = render_catalogs._render_catalog_payload(
            "mcp-catalog",
            "alc_mcp.catalog",
            "MCP_TOOLS",
        )
        self.assertEqual(count, len(MCP_TOOLS))
        self.assertEqual(CATALOG_DOC.read_text(encoding="utf-8"), rendered)

    def test_skill_reference_catalog_matches_renderer(self) -> None:
        rendered, _count = render_catalogs._render_catalog_payload(
            "mcp-catalog",
            "alc_mcp.catalog",
            "MCP_TOOLS",
        )
        self.assertEqual(SKILL_CATALOG_DOC.read_text(encoding="utf-8"), rendered)


if __name__ == "__main__":
    unittest.main()
