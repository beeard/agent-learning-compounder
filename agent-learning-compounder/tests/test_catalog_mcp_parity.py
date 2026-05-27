"""Drift guard: every UQ/UP entry in query-catalog/propose-catalog must
have an MCP partner (or be on the explicit CLI-only allowlist).

This closes the gap that let documented read/propose ops live in their
catalogs without an MCP wrapper.

To intentionally exclude an op from MCP exposure, add its catalog ID
(e.g. ``"UQ9"``) and the reason to ``CLI_ONLY_ALLOWLIST`` below. The
allowlist is the single place where "this catalog op exists, but we
chose not to expose it" gets recorded — it forces an explicit decision.
"""

from __future__ import annotations

import pathlib
import re
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
BIN = ROOT / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

from alc_mcp.catalog import MCP_TOOLS

QUERY_CATALOG = ROOT / "reference-lib" / "query-catalog"
PROPOSE_CATALOG = ROOT / "reference-lib" / "propose-catalog"

# Catalog IDs intentionally NOT exposed via MCP. Adding to this list is the
# explicit decision point — it forces a reason and makes the gap discoverable.
CLI_ONLY_ALLOWLIST: dict[str, str] = {
    # "UQn": "reason this op is intentionally CLI-only",
}


_ROW_RE = re.compile(r"^\|\s*(U[QP]\d+)\s*\|\s*(read|write)\s*\|.*\|\s*([\w\.]+)\s*\|\s*\d+\s*\|\s*$")


def _read_catalog(path: pathlib.Path) -> dict[str, str]:
    """Return {catalog_id: backing} parsed from a UQ/UP catalog table."""
    rows: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _ROW_RE.match(line)
        if m:
            rows[m.group(1)] = m.group(3)
    return rows


def _mcp_backings() -> set[str]:
    return {spec.backing for spec in MCP_TOOLS.values()}


class CatalogMCPParityTests(unittest.TestCase):
    def test_every_query_catalog_op_has_mcp_partner_or_allowlist(self) -> None:
        queries = _read_catalog(QUERY_CATALOG)
        self.assertTrue(queries, "query-catalog parsed to empty — regex drift?")
        backings = _mcp_backings()
        missing: list[str] = []
        for cid, backing in queries.items():
            if cid in CLI_ONLY_ALLOWLIST:
                continue
            if backing not in backings:
                missing.append(f"{cid} ({backing})")
        self.assertFalse(
            missing,
            (
                "query-catalog ops without MCP partner. Either add an MCPToolSpec "
                "with this backing, or add the catalog ID to CLI_ONLY_ALLOWLIST "
                f"with a reason: {missing}"
            ),
        )

    def test_every_propose_catalog_op_has_mcp_partner_or_allowlist(self) -> None:
        proposes = _read_catalog(PROPOSE_CATALOG)
        self.assertTrue(proposes, "propose-catalog parsed to empty — regex drift?")
        backings = _mcp_backings()
        missing: list[str] = []
        for cid, backing in proposes.items():
            if cid in CLI_ONLY_ALLOWLIST:
                continue
            if backing not in backings:
                missing.append(f"{cid} ({backing})")
        self.assertFalse(
            missing,
            (
                "propose-catalog ops without MCP partner. Either add an MCPToolSpec "
                "with this backing, or add the catalog ID to CLI_ONLY_ALLOWLIST "
                f"with a reason: {missing}"
            ),
        )

    def test_every_public_alc_query_function_is_catalogued(self) -> None:
        """Every public state-bound function in alc_query must be catalogued
        somewhere — either as a UQn row in query-catalog, or directly as an
        MCPToolSpec (e.g. M1 get_gates, M2 get_skill_context). Catches
        orphan reads like ``get_skill_usage_summary`` where a real public
        read API exists in code but never made it into any mirror.
        """
        import inspect
        import alc_query

        catalogued_backings = set(_read_catalog(QUERY_CATALOG).values()) | _mcp_backings()
        # Allowlist for non-query public surface that should NOT need a catalog row.
        non_query_public = {
            "QueryError",
            "StateHandle",
            "Scope",
            "Any",
            "Literal",
            "Path",
        }
        missing: list[str] = []
        for name in dir(alc_query):
            if name.startswith("_") or name in non_query_public:
                continue
            attr = getattr(alc_query, name)
            if not (callable(attr) and not isinstance(attr, type)):
                continue
            try:
                sig = inspect.signature(attr)
            except (TypeError, ValueError):
                continue
            params = list(sig.parameters.values())
            if not params or params[0].name != "state":
                continue  # not a state-bound read API
            backing = f"alc_query.{name}"
            if backing not in catalogued_backings:
                missing.append(backing)
        self.assertFalse(
            missing,
            (
                "public state-bound functions in alc_query that are catalogued nowhere. "
                "Either add a UQn row in reference-lib/query-catalog (and optionally "
                "an MCPToolSpec), expose directly as an MCPToolSpec, or rename to "
                f"_private if not intended as public API: {missing}"
            ),
        )


if __name__ == "__main__":
    unittest.main()
