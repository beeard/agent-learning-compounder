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
        # as a skip, not a hard import failure at module load. Handlers now
        # live in TOOL_HANDLERS rather than as module-level *_handler symbols.
        sys.path.insert(0, str(REPO_ROOT))
        try:
            from alc_mcp.server import TOOL_HANDLERS  # noqa: F401
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
        from alc_mcp.server import TOOL_HANDLERS
        get_gates_handler = TOOL_HANDLERS["get_gates"]
        result = asyncio.run(get_gates_handler({"repo": str(self.repo)}))
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["gate_id"], "abcdef012345")
        self.assertEqual(result[0]["domain"], "tests")

    def test_get_skill_context_returns_string(self):
        from alc_mcp.server import TOOL_HANDLERS
        get_skill_context_handler = TOOL_HANDLERS["get_skill_context"]
        result = asyncio.run(get_skill_context_handler({"repo": str(self.repo)}))
        self.assertIsInstance(result, str)
        self.assertIn("required_at_session_start", result)

    def test_propose_gate_appends_queue_row(self):
        from alc_mcp.server import TOOL_HANDLERS
        propose_gate_handler = TOOL_HANDLERS["propose_gate"]
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
        from alc_mcp.server import TOOL_HANDLERS
        report_outcome_handler = TOOL_HANDLERS["report_outcome"]

        events_log = next((self.repo / ".agent-learning" / "repos").iterdir()) / "events.jsonl"

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
        self.assertEqual(rows[0]["event"], "outcome_reported")
        self.assertEqual(rows[0]["payload"]["verdict"], "loaded_helpful")

    def test_report_agent_event_appends_bounded_dispatch_event(self):
        from alc_mcp.server import TOOL_HANDLERS
        report_agent_event_handler = TOOL_HANDLERS["report_agent_event"]

        events_log = next((self.repo / ".agent-learning" / "repos").iterdir()) / "events.jsonl"

        payload = {
            "repo": str(self.repo),
            "event": "AgentDispatchComplete",
            "runtime": "codex",
            "agent_role": "builder",
            "agent_backend": "codex-exec",
            "agent_model": "gpt-5.3-codex-spark",
            "agent_effort": "low",
            "agent_write_scope": ["src/app.ts", "/etc/passwd"],
            "dispatch_id": "d-1",
            "outcome": "success",
            "label": "completed",
        }
        result = asyncio.run(report_agent_event_handler(payload))
        self.assertEqual(result.get("recorded"), True)
        self.assertEqual(result.get("event"), "agent_dispatch_complete")

        rows = [json.loads(ln) for ln in events_log.read_text().splitlines() if ln]
        self.assertEqual(rows[0]["event"], "agent_dispatch_complete")
        self.assertEqual(rows[0]["actor"]["kind"], "mcp_server")


class McpServerHandlerHardening(unittest.TestCase):
    """Bug-fix coverage for multi-repo selection, scrubbing, and error clarity.

    These tests exercise the handler functions directly. Per the README, the
    handlers are import-safe without the `mcp` SDK, so we don't gate on it —
    that lets the suite catch regressions even on a bare CI image. If the
    server module can't be imported for any other reason, we still skip
    cleanly so this file stays useful in degraded environments.
    """

    def setUp(self):
        sys.path.insert(0, str(REPO_ROOT))
        sys.path.insert(0, str(REPO_ROOT / "bin"))
        try:
            from alc_mcp.server import TOOL_HANDLERS  # noqa: F401
        except ImportError as e:
            self.skipTest(f"alc_mcp.server not importable: {e}")
        import state_paths  # type: ignore
        self._state_paths = state_paths

        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        if hasattr(self, "tmp"):
            self.tmp.cleanup()

    def _make_repo(self, name: str) -> Path:
        """Build a minimal initialized repo with its repo_state_dir populated."""
        repo = self.root / name
        repo.mkdir(parents=True)
        # repo_state_dir resolves via resolve_state_dir(None, None, repo) which
        # returns <repo>/.agent-learning, then appends /repos/<repo_id>.
        rsd = self._state_paths.repo_state_dir(repo)
        rsd.mkdir(parents=True, exist_ok=True)
        (rsd / "improvement-queue.jsonl").write_text("", encoding="utf-8")
        (rsd / "hook-events.jsonl").write_text("", encoding="utf-8")
        return repo

    def test_multi_repo_state_root_selects_correct_repo(self):
        """When the same state root contains multiple repos, handlers must
        operate on the repo identified by the call args — not the lexicographic
        first one found via rglob/iterdir."""
        from alc_mcp.server import TOOL_HANDLERS
        propose_gate_handler = TOOL_HANDLERS["propose_gate"]
        report_outcome_handler = TOOL_HANDLERS["report_outcome"]

        repo_a = self._make_repo("alpha")
        repo_b = self._make_repo("bravo")

        # Sanity: distinct state dirs.
        rsd_a = self._state_paths.repo_state_dir(repo_a)
        rsd_b = self._state_paths.repo_state_dir(repo_b)
        self.assertNotEqual(rsd_a, rsd_b)

        # propose_gate should land in repo_b's queue only.
        result = asyncio.run(propose_gate_handler({
            "repo": str(repo_b),
            "domain": "tests",
            "category": "validation-check",
            "gate": "Run pytest before claiming done.",
            "evidence": "multi-repo selection test",
        }))
        queue_id = result["queue_id"]

        queue_a = (rsd_a / "improvement-queue.jsonl").read_text()
        queue_b = (rsd_b / "improvement-queue.jsonl").read_text()
        self.assertNotIn(queue_id, queue_a, "row leaked into wrong repo's queue")
        self.assertIn(queue_id, queue_b)

        # report_outcome should land in repo_a's events log only.
        asyncio.run(report_outcome_handler({
            "repo": str(repo_a),
            "gate_id": "abc123",
            "outcome": "loaded_helpful",
            "correlation_id": "session-multi",
        }))
        log_a = (rsd_a / "events.jsonl").read_text()
        log_b = (rsd_b / "events.jsonl").read_text() if (rsd_b / "events.jsonl").exists() else ""
        self.assertIn("loaded_helpful", log_a)
        self.assertNotIn("loaded_helpful", log_b)

    def test_report_outcome_newline_in_outcome_keeps_jsonl_parseable(self):
        """A newline in outcome must not break the line-per-event invariant —
        either the row is rejected or the newline is sanitized away."""
        from alc_mcp.server import TOOL_HANDLERS
        report_outcome_handler = TOOL_HANDLERS["report_outcome"]

        repo = self._make_repo("nlrepo")
        rsd = self._state_paths.repo_state_dir(repo)
        log = rsd / "events.jsonl"

        payload = {
            "repo": str(repo),
            "gate_id": "abc123",
            "outcome": "loaded_helpful\nFAKE_ROW_INJECTED=true",
            "correlation_id": "session-nl",
        }

        try:
            asyncio.run(report_outcome_handler(payload))
        except ValueError:
            # Rejection is an acceptable outcome.
            pass

        body = log.read_text(encoding="utf-8")
        non_empty = [ln for ln in body.splitlines() if ln]
        # The core invariant: a newline in user input must not split one
        # logical event across multiple JSONL lines. Either zero rows
        # (rejected) or exactly one parseable row (sanitized).
        self.assertLessEqual(len(non_empty), 1)
        for line in non_empty:
            row = json.loads(line)  # must parse — invariant under test
            self.assertNotIn("\n", row.get("outcome", ""))

    def test_propose_gate_uninitialized_repo_returns_descriptive_error(self):
        """When .agent-learning/repos/ doesn't exist, the handler must raise
        a descriptive error rather than yielding an empty error string."""
        from alc_mcp.server import TOOL_HANDLERS
        propose_gate_handler = TOOL_HANDLERS["propose_gate"]

        repo = self.root / "uninit"
        repo.mkdir()
        # Intentionally do NOT create .agent-learning/repos/.

        with self.assertRaises(Exception) as ctx:
            asyncio.run(propose_gate_handler({
                "repo": str(repo),
                "domain": "tests",
                "category": "validation-check",
                "gate": "Some gate",
            }))
        message = str(ctx.exception)
        self.assertTrue(message.strip(), "error message must not be empty")
        self.assertIn("init_learning_system", message)


if __name__ == "__main__":
    unittest.main()
