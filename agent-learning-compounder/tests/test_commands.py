from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMMANDS = ROOT / "commands"
ALC_REPORT = COMMANDS / "alc-report.md"
RENDER_SCRIPT = ROOT / "scripts" / "render_unified_report.py"


def _read_command() -> str:
    return ALC_REPORT.read_text(encoding="utf-8")


def _frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"\A---\n(?P<body>.*?)\n---\n", text, re.DOTALL)
    if not match:
        return {}
    fields: dict[str, str] = {}
    for line in match.group("body").splitlines():
        key, separator, value = line.partition(":")
        if separator:
            fields[key.strip()] = value.strip()
    return fields


def _bash_blocks(text: str) -> list[str]:
    return re.findall(r"```bash\n(.*?)\n```", text, re.DOTALL)


def _renderer_help_flags() -> set[str]:
    result = subprocess.run(
        ["python3", str(RENDER_SCRIPT), "--help"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return set(re.findall(r"(?<!\w)--[a-zA-Z0-9][a-zA-Z0-9_-]*", result.stdout))


class AlcReportCommandTests(unittest.TestCase):
    def test_command_file_parses_with_required_frontmatter(self) -> None:
        fields = _frontmatter(_read_command())
        self.assertEqual(fields.get("name"), "alc-report")
        self.assertTrue(fields.get("description"))

    def test_command_body_contains_exactly_one_bash_code_block(self) -> None:
        self.assertEqual(len(_bash_blocks(_read_command())), 1)

    def test_bash_block_uses_claude_plugin_root_with_alc_fallback(self) -> None:
        # Slash commands run only in Claude Code. We expand to CLAUDE_PLUGIN_ROOT
        # with an ALC_PLUGIN_ROOT fallback so the command is also safe to run from
        # a Codex shell that has wired ALC_PLUGIN_ROOT manually.
        block = _bash_blocks(_read_command())[0]
        self.assertIn("${CLAUDE_PLUGIN_ROOT", block)
        self.assertIn("ALC_PLUGIN_ROOT", block)

    def test_description_mentions_all_renderer_help_flags(self) -> None:
        description = _frontmatter(_read_command())["description"]
        missing = sorted(flag for flag in _renderer_help_flags() if flag not in description)
        self.assertEqual(missing, [])

    def test_subsumed_v1_commands_do_not_exist(self) -> None:
        for name in ("alc-analyze.md", "alc-recommend.md", "alc-apply.md"):
            self.assertFalse((COMMANDS / name).exists(), name)


if __name__ == "__main__":
    unittest.main()
