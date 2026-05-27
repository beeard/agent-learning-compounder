"""Tests for P5B: dashboard FastAPI + HTMX panels.

These tests SKIP cleanly when the optional fastapi/jinja2/httpx deps are missing.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class Dashboard(unittest.TestCase):
    def setUp(self):
        try:
            import fastapi  # noqa: F401
            import jinja2  # noqa: F401
            from fastapi.testclient import TestClient  # noqa: F401
        except ImportError:
            self.skipTest("fastapi/jinja2 not installed")

        sys.path.insert(0, str(REPO_ROOT))
        sys.path.insert(0, str(REPO_ROOT / "bin"))
        from dashboard import build_app
        import state_paths

        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        fixture_src = REPO_ROOT / "fixtures" / "eval-fixtures" / "mini-repo"
        shutil.copytree(fixture_src, self.repo, ignore=shutil.ignore_patterns("seed"))

        rid = state_paths.repo_id(self.repo)
        state_dir = self.repo / ".agent-learning" / "repos" / rid
        state_dir.mkdir(parents=True, exist_ok=True)
        seed = fixture_src / "seed"
        for name in ("config.json", "baseline.json", "domain-rules.active.json", "skill-map.json"):
            shutil.copy(seed / name, state_dir / name)
        (state_dir / "improvement-queue.jsonl").write_text("", encoding="utf-8")

        reports = state_dir / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        (reports / "latest-approved-gates.md").write_text(
            "# Approved Agent Gates\n\n"
            "- domain: tests\n"
            "  gate_id: abcdef012345\n"
            "  gate_category: validation-check\n"
            "  gate: Run pytest before claiming done.\n",
            encoding="utf-8",
        )
        (reports / "latest-skill-context.md").write_text(
            "# Active Skill Context\n",
            encoding="utf-8",
        )
        (self.repo / ".agent-learning.json").write_text(json.dumps({
            "latest_approved_gates": str(reports / "latest-approved-gates.md"),
            "latest_skill_context": str(reports / "latest-skill-context.md"),
        }), encoding="utf-8")

        self.app = build_app(repo=self.repo)
        self.client = TestClient(self.app)

    def tearDown(self):
        if hasattr(self, "tmp"):
            self.tmp.cleanup()

    def test_index_renders(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Agent Learning Compounder", r.content)

    def test_gates_partial_returns_table(self):
        r = self.client.get("/_gates")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"<table", r.content)
        self.assertIn(b"abcdef012345", r.content)

    def test_queue_partial_returns_empty_state(self):
        r = self.client.get("/_queue")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Empty queue", r.content)

    def test_probes_partial_returns_empty_state(self):
        r = self.client.get("/_probes")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"No active probes", r.content)

    def test_api_data_includes_scoped_gates(self):
        # PR 3: /api/data must return scoped_gates with rows tagged _source_scope.
        r = self.client.get("/api/data")
        self.assertEqual(r.status_code, 200)
        payload = r.json()
        self.assertIn("scoped_gates", payload)
        scoped = payload["scoped_gates"]
        self.assertIn("rows", scoped)
        self.assertIn("summary", scoped)
        self.assertIn("skill_context_md", scoped)
        for key in ("total", "user", "project"):
            self.assertIn(key, scoped["summary"])
        # The setUp seed writes a project-scope gate (abcdef012345); the row
        # should carry _source_scope == "project".
        project_rows = [row for row in scoped["rows"] if row.get("_source_scope") == "project"]
        self.assertTrue(
            any(row.get("gate_id") == "abcdef012345" for row in project_rows),
            f"expected seeded project gate to surface; got rows={scoped['rows']}",
        )


if __name__ == "__main__":
    unittest.main()
