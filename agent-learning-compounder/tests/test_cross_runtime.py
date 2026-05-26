import json
import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


def _extract_core_commands(text):
    return set(re.findall(r"(/alc-report|\binit_learning_system\b|\brender_unified_report\b)", text))


def _extract_mcp_tools(text):
    match = re.search(
        r"^##\s+MCP tools\s*$\n(.*?)(?=^##\s+|\Z)",
        text,
        flags=re.M | re.S,
    )
    section = match.group(1) if match else ""
    return set(re.findall(r"`([^`]+)`", section))


def _extract_operating_rule_headers(text):
    return set(
        line.strip().lstrip("#").strip()
        for line in re.findall(r"^##\s*[^\n]*$", text, flags=re.M)
        if "operating rules" in line.lower()
    )


class TestCrossRuntimeEntryFiles(unittest.TestCase):
    def test_claude_plugin_manifest_valid(self):
        manifest_path = ROOT / ".claude-plugin" / "plugin.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        for key in ("name", "version", "description"):
            self.assertIn(key, manifest)

        # Component-path arrays (skills/agents/commands/hooks) are NOT required:
        # Claude Code auto-discovers them from the conventional directories at
        # plugin root. They only need to be declared when overriding defaults.
        # See plugin-dev:plugin-structure (Component Path Configuration).

    def test_claude_plugin_components_auto_discoverable(self):
        # Verify the canonical auto-discovery surfaces exist at plugin root.
        self.assertTrue((ROOT / "agents").is_dir())
        self.assertTrue((ROOT / "commands").is_dir())
        self.assertTrue((ROOT / "hooks" / "hooks.json").is_file())
        self.assertTrue((ROOT / "skills").is_dir())
        self.assertTrue((ROOT / ".mcp.json").is_file())

    def test_claude_md_references_core_commands(self):
        claude_text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        commands = _extract_core_commands(claude_text)

        self.assertIn("/alc-report", commands)
        self.assertIn("init_learning_system", commands)
        self.assertIn("render_unified_report", commands)

    def test_agents_md_content_parity_with_claude(self):
        claude_text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        agents_text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

        claude_commands = _extract_core_commands(claude_text)
        agents_commands = _extract_core_commands(agents_text)
        self.assertEqual(claude_commands, agents_commands)

        claude_tools = _extract_mcp_tools(claude_text)
        agents_tools = _extract_mcp_tools(agents_text)
        self.assertEqual(claude_tools, agents_tools)

        claude_rules = _extract_operating_rule_headers(claude_text)
        agents_rules = _extract_operating_rule_headers(agents_text)
        self.assertEqual(claude_rules, agents_rules)

    def test_no_codex_plugin_manifest_yet(self):
        self.assertFalse((ROOT / ".codex-plugin" / "plugin.json").exists())
