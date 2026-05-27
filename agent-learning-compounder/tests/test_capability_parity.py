from __future__ import annotations

import ast
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
BIN = ROOT / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import alc_next_action
import alc_propose
import alc_query
import analyst_queries
import recommender_generators
from alc_mcp.catalog import MCP_TOOLS


PARITY = ROOT / "skills" / "alc-core" / "references" / "capability-parity.md"


PARITY_PARTNERS = {
    "M1": ["alc_query.get_gates"],
    "M2": ["alc_query.get_skill_context"],
    "M3": ["alc_query.get_recommendations", "recommender_generators.GENERATORS"],
    "M4": ["alc_query.get_pending_patches"],
    "M5": ["alc_query"],
    "M6": ["alc_propose.propose_apply"],
    "M7": ["alc_propose.propose_gate"],
    "M8": ["alc_propose.report_outcome"],
    "M9": ["alc_propose.report_agent_event"],
    "M10": ["analyst_queries.QUERIES"],
    "M11": ["alc_next_action.next_action"],
    "M12": ["alc_query.get_apply_log"],
    "M13": ["alc_query.get_outcomes"],
    "M14": ["alc_query.get_event_dag"],
    "M15": ["alc_query.get_actor_summary"],
    "M16": ["alc_query.get_skill_invocation_history"],
    "M17": ["alc_query.get_skill_usage_summary"],
    "M18": ["alc_propose.mark_patch_status"],
}


def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


class CapabilityParityTests(unittest.TestCase):
    def test_every_mcp_tool_has_catalog_partner(self) -> None:
        available = {
            "alc_query": alc_query,
            "alc_propose": alc_propose,
        }
        for name, func in vars(alc_query).items():
            if callable(func) and not name.startswith("_"):
                available[f"alc_query.{name}"] = func
        for name, func in vars(alc_propose).items():
            if callable(func) and not name.startswith("_"):
                available[f"alc_propose.{name}"] = func
        available["recommender_generators.GENERATORS"] = recommender_generators.GENERATORS
        available["analyst_queries.QUERIES"] = analyst_queries.QUERIES
        available["alc_next_action"] = alc_next_action
        available["alc_next_action.next_action"] = alc_next_action.next_action

        for spec in MCP_TOOLS.values():
            partners = PARITY_PARTNERS.get(spec.id, [])
            self.assertTrue(partners, f"missing parity partners for {spec.id}")
            self.assertTrue(any(partner in available and available[partner] for partner in partners), spec)

    def test_capability_parity_document_covers_every_mid(self) -> None:
        text = PARITY.read_text(encoding="utf-8")
        for spec in MCP_TOOLS.values():
            self.assertIn(f"| {spec.id} |", text)

    def test_dashboard_does_not_bypass_read_catalog(self) -> None:
        imports = _imports(ROOT / "skills" / "alc-dashboard" / "server.py")
        forbidden = {"event_writer", "bin.event_writer", "state_paths", "bin.state_paths", "sqlite3"}
        self.assertFalse(imports & forbidden, imports & forbidden)
        text = (ROOT / "skills" / "alc-dashboard" / "server.py").read_text(encoding="utf-8")
        self.assertNotIn("events.sqlite", text)

    def test_mcp_server_does_not_bypass_query_propose_catalogs(self) -> None:
        imports = _imports(ROOT / "alc_mcp" / "server.py")
        forbidden = {"event_writer", "bin.event_writer", "state_paths", "bin.state_paths", "sqlite3"}
        self.assertFalse(imports & forbidden, imports & forbidden)
        text = (ROOT / "alc_mcp" / "server.py").read_text(encoding="utf-8")
        self.assertNotIn("events.sqlite", text)


if __name__ == "__main__":
    unittest.main()
