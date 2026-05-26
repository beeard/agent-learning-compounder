from __future__ import annotations

import asyncio
import inspect
import unittest
from pathlib import Path

from alc_mcp import MCP_TOOLS, MCPToolSpec
from alc_mcp import server


class McpCatalogTests(unittest.TestCase):
    def test_catalog_ids_are_unique_sequential_and_complete(self):
        ids = [spec.id for spec in MCP_TOOLS.values()]
        self.assertEqual(ids, [f"M{i}" for i in range(1, 11)])
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

    def test_list_capabilities_returns_m1_to_m10_metadata(self):
        rows = asyncio.run(server.list_capabilities_handler({"repo": "/tmp/repo"}))
        self.assertEqual([row["id"] for row in rows], [f"M{i}" for i in range(1, 11)])
        self.assertNotIn("handler", rows[0])
        self.assertIn("parameters_schema", rows[0])

    def test_no_handle_apply_patch_function_exists(self):
        source = Path(server.__file__).read_text(encoding="utf-8")
        self.assertNotIn("def handle_apply_patch", source)
        self.assertNotIn("handle_apply_patch", source)

    def test_tool_handlers_are_thin_wrappers(self):
        for name, handler in server.TOOL_HANDLERS.items():
            if name == "list_capabilities":
                continue
            body = inspect.getsource(handler).splitlines()[1:]
            executable = [line for line in body if line.strip() and not line.strip().startswith("#")]
            self.assertLessEqual(len(executable), 5, name)


if __name__ == "__main__":
    unittest.main()
