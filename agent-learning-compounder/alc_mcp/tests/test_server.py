"""Tests for P5A: MCP server exposing agent-learning state.

These tests SKIP cleanly when the optional `mcp` SDK is not installed.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class McpServerTools(unittest.TestCase):
    """Test the tool handlers directly (transport-independent)."""

    def setUp(self):
        try:
            import mcp  # noqa: F401
        except ImportError:
            self.skipTest("mcp SDK not installed")

        # Import alc_mcp.server lazily so the import error from mcp surfaces
        # as a skip, not a hard import failure at module load.
        sys.path.insert(0, str(REPO_ROOT))
        try:
            from alc_mcp.server import (  # noqa: F401
                get_gates_handler, propose_gate_handler,
                report_outcome_handler, get_skill_context_handler,
            )
        except ImportError as e:
            self.skipTest(f"alc_mcp.server not importable: {e}")

        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        fixture_src = REPO_ROOT / "fixtures" / "eval-fixtures" / "mini-repo"
        shutil.copytree(fixture_src, self.repo, ignore=shutil.ignore_patterns("seed"))

        # Build a minimal valid .agent-learning state
        sys.path.insert(0, str(REPO_ROOT / "bin"))
        import state_paths  # type: ignore
        rid = state_paths.repo_id(self.repo)
        state_dir = self.repo / ".agent-learning" / "repos" / rid
        state_dir.mkdir(parents=True, exist_ok=True)
        seed = fixture_src / "seed"
        for name in ("config.json", "baseline.json", "domain-rules.active.json", "skill-map.json"):
            shutil.copy(seed / name, state_dir / name)
        (state_dir / "improvement-queue.jsonl").write_text("", encoding="utf-8")

        # Reports needed by the server
        reports_dir = state_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        (reports_dir / "latest-approved-gates.md").write_text(
            "# Approved Agent Gates\n\n"
            "- domain: tests\n"
            "  gate_id: abcdef012345\n"
            "  gate_category: validation-check\n"
            "  gate: Run pytest before claiming done.\n",
            encoding="utf-8",
        )
        (reports_dir / "latest-skill-context.md").write_text(
            "# Active Skill Context\n\n## required_at_session_start\n- latest-approved-gates.md\n",
            encoding="utf-8",
        )

        # Build the .agent-learning.json pointer file
        (self.repo / ".agent-learning.json").write_text(json.dumps({
            "latest_approved_gates": str(reports_dir / "latest-approved-gates.md"),
            "latest_skill_context": str(reports_dir / "latest-skill-context.md"),
        }), encoding="utf-8")

    def tearDown(self):
        if hasattr(self, "tmp"):
            self.tmp.cleanup()

    def test_get_gates_returns_list(self):
        from alc_mcp.server import get_gates_handler
        result = asyncio.run(get_gates_handler({"repo": str(self.repo)}))
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["gate_id"], "abcdef012345")
        self.assertEqual(result[0]["domain"], "tests")

    def test_get_skill_context_returns_string(self):
        from alc_mcp.server import get_skill_context_handler
        result = asyncio.run(get_skill_context_handler({"repo": str(self.repo)}))
        self.assertIsInstance(result, str)
        self.assertIn("required_at_session_start", result)

    def test_propose_gate_appends_queue_row(self):
        from alc_mcp.server import propose_gate_handler
        payload = {
            "repo": str(self.repo),
            "domain": "tests",
            "category": "validation-check",
            "gate": "Always run pytest -x before claiming done.",
            "evidence": "Two corrections in current session after skipping validation.",
        }
        result = asyncio.run(propose_gate_handler(payload))
        self.assertIn("queue_id", result)

        queue = next((self.repo / ".agent-learning" / "repos").rglob("improvement-queue.jsonl"))
        rows = [json.loads(ln) for ln in queue.read_text().splitlines() if ln]
        self.assertTrue(any(r.get("id") == result["queue_id"] for r in rows))

    def test_report_outcome_appends_event(self):
        from alc_mcp.server import report_outcome_handler

        # Ensure the events log exists
        events_log = next((self.repo / ".agent-learning" / "repos").iterdir()) / "hook-events.jsonl"
        events_log.write_text("", encoding="utf-8")

        payload = {
            "repo": str(self.repo),
            "gate_id": "abcdef012345",
            "outcome": "loaded_helpful",
            "correlation_id": "session-1",
        }
        result = asyncio.run(report_outcome_handler(payload))
        self.assertEqual(result.get("recorded"), True)

        rows = [json.loads(ln) for ln in events_log.read_text().splitlines() if ln]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["outcome"], "loaded_helpful")


if __name__ == "__main__":
    unittest.main()
