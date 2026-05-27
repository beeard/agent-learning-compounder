from __future__ import annotations

import asyncio
import inspect
import unittest
from pathlib import Path

from alc_mcp import MCP_TOOLS, MCPToolSpec
from alc_mcp import server


# Handlers that intentionally exceed the thin-wrapper budget because they need
# arg-aliasing or payload normalisation. Keep this list short and documented —
# adding here is the explicit decision point for "this handler has a reason to
# carry logic." See the "Explicit overrides" block in alc_mcp/server.py.
EXPLICIT_OVERRIDES = {
    "report_outcome": "aliases recommendation_id/gate_id and verdict/outcome",
    "report_agent_event": "normalises agent kind and constructs telemetry sub-object",
    "exec_sandbox": "coerces repo to Path, injects default actor, reshapes ExecResult",
}


class McpCatalogTests(unittest.TestCase):
    def test_catalog_ids_are_unique_sequential_and_complete(self):
        ids = [spec.id for spec in MCP_TOOLS.values()]
        expected = [f"M{i}" for i in range(1, len(MCP_TOOLS) + 1)]
        self.assertEqual(ids, expected)
        self.assertEqual(len(ids), len(set(ids)))
        for spec in MCP_TOOLS.values():
            self.assertIsInstance(spec, MCPToolSpec)
            self.assertIn(spec.kind, {"read", "propose", "observe", "exec"})
            self.assertTrue(spec.summary)
            self.assertTrue(spec.backing)
            self.assertTrue(spec.parameters_schema)
            self.assertTrue(spec.returns_schema)
            self.assertTrue(spec.examples)
            self.assertGreaterEqual(spec.version, spec.min_compatible_version)

    def test_registered_tools_match_catalog_plus_list_capabilities(self):
        registered = set(server.TOOL_HANDLERS)
        schemas = {tool["name"] for tool in server.TOOL_SCHEMAS}
        self.assertEqual(registered, set(MCP_TOOLS) | {"list_capabilities"})
        self.assertEqual(schemas, registered)

    def test_list_capabilities_returns_full_catalog_metadata(self):
        handler = server.TOOL_HANDLERS["list_capabilities"]
        rows = asyncio.run(handler({"repo": "/tmp/repo"}))
        expected = [f"M{i}" for i in range(1, len(MCP_TOOLS) + 1)]
        self.assertEqual([row["id"] for row in rows], expected)
        self.assertNotIn("handler", rows[0])
        self.assertIn("parameters_schema", rows[0])

    def test_no_handle_apply_patch_function_exists(self):
        source = Path(server.__file__).read_text(encoding="utf-8")
        self.assertNotIn("def handle_apply_patch", source)
        self.assertNotIn("handle_apply_patch", source)

    def test_tool_handlers_are_thin_wrappers(self):
        # Auto-wired handlers must be ≤5 executable lines (pure delegation).
        # Explicit overrides may exceed but are bounded to ≤15 lines.
        for name, handler in server.TOOL_HANDLERS.items():
            if name == "list_capabilities":
                continue
            body = inspect.getsource(handler).splitlines()[1:]
            executable = [line for line in body if line.strip() and not line.strip().startswith("#")]
            budget = 15 if name in EXPLICIT_OVERRIDES else 5
            self.assertLessEqual(
                len(executable),
                budget,
                f"{name}: {len(executable)} executable lines (budget {budget}). "
                + (
                    f"Override reason: {EXPLICIT_OVERRIDES[name]}"
                    if name in EXPLICIT_OVERRIDES
                    else "Add to EXPLICIT_OVERRIDES with a one-line reason if intentional."
                ),
            )


if __name__ == "__main__":
    unittest.main()
