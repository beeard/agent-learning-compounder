from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class McpStdioServerSmoke(unittest.TestCase):
    def test_stdio_server_initializes_and_lists_tools(self):
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as error:
            self.skipTest(f"mcp SDK not installed: {error}")

        async def run():
            params = StdioServerParameters(
                command=sys.executable,
                args=[str(REPO_ROOT / "alc_mcp" / "server.py")],
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    initialized = await asyncio.wait_for(session.initialize(), timeout=5)
                    tools = await asyncio.wait_for(session.list_tools(), timeout=5)
                    return initialized.serverInfo.name, {tool.name for tool in tools.tools}

        name, tools = asyncio.run(run())
        self.assertEqual(name, "agent-learning-compounder")
        self.assertIn("get_gates", tools)
        self.assertIn("report_agent_event", tools)

    def test_stdio_server_accepts_content_length_framing(self):
        payload = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "smoke", "version": "0"},
            },
        })
        framed = f"Content-Length: {len(payload.encode('utf-8'))}\r\n\r\n{payload}"

        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "alc_mcp" / "server.py")],
            input=framed,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(proc.stdout.startswith("Content-Length:"), proc.stdout)
        separator = "\r\n\r\n" if "\r\n\r\n" in proc.stdout else "\n\n"
        response = proc.stdout.split(separator, 1)[1]
        self.assertEqual(json.loads(response)["result"]["serverInfo"]["name"], "agent-learning-compounder")


if __name__ == "__main__":
    unittest.main()
