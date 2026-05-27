from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from alc_mcp import server
from bin.state_handle import StateHandle


class RecommenderToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        self.state = StateHandle.for_repo(self.repo)
        self.state.reports_dir.mkdir(parents=True)
        self.state.repo_state_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_get_recommendations_returns_empty_without_file(self):
        result = asyncio.run(server.TOOL_HANDLERS["get_recommendations"]({"repo": str(self.repo)}))
        self.assertEqual(result, [])

    def test_list_pending_patches_filters_rejected_and_deferred(self):
        patch_dir = self.state.repo_state_dir / "patches"
        patch_dir.mkdir()
        (patch_dir / "a.json").write_text(json.dumps({"patch_id": "a", "status": "pending"}), encoding="utf-8")
        (patch_dir / "b.json").write_text(json.dumps({"patch_id": "b", "status": "rejected"}), encoding="utf-8")
        (patch_dir / "c.json").write_text(json.dumps({"patch_id": "c", "status": "deferred"}), encoding="utf-8")
        result = asyncio.run(server.TOOL_HANDLERS["list_pending_patches"]({"repo": str(self.repo)}))
        self.assertEqual([row["patch_id"] for row in result], ["a"])

    def test_propose_apply_returns_command_without_mutating_patch(self):
        patch_dir = self.state.repo_state_dir / "patches"
        patch_dir.mkdir()
        patch = patch_dir / "p1.json"
        patch.write_text(json.dumps({"patch_id": "p1", "status": "pending"}), encoding="utf-8")
        before = patch.read_text(encoding="utf-8")
        result = asyncio.run(server.TOOL_HANDLERS["propose_apply"]({"repo": str(self.repo), "patch_id": "p1"}))
        self.assertIn("alc_apply", result["command"])
        self.assertIn("p1", result["command"])
        self.assertEqual(patch.read_text(encoding="utf-8"), before)

    def test_get_dashboard_url_prefers_http_marker_then_file_fallback(self):
        self.state.dashboard_dir.mkdir(parents=True)
        (self.state.dashboard_dir / "server.json").write_text(json.dumps({"url": "http://127.0.0.1:8765/"}), encoding="utf-8")
        self.assertEqual(asyncio.run(server.TOOL_HANDLERS["get_dashboard_url"]({"repo": str(self.repo)})), "http://127.0.0.1:8765/")
        (self.state.dashboard_dir / "server.json").unlink()
        (self.state.dashboard_dir / "index.html").write_text("<html></html>", encoding="utf-8")
        self.assertTrue(asyncio.run(server.TOOL_HANDLERS["get_dashboard_url"]({"repo": str(self.repo)})).startswith("file://"))

    def test_report_outcome_delegates_to_alc_propose(self):
        with mock.patch.object(server.alc_propose, "report_outcome", return_value="evt-1") as write:
            result = asyncio.run(server.TOOL_HANDLERS["report_outcome"]({"repo": str(self.repo), "recommendation_id": "rec1", "verdict": "accepted", "reason": "works"}))
        self.assertEqual(result, {"recorded": True, "event_id": "evt-1"})
        self.assertEqual(write.call_args.args[1:], ("rec1", "accepted", "works"))

    def test_get_proposal_queue_reads_improvement_queue(self):
        queue = self.state.repo_state_dir / "improvement-queue.jsonl"
        queue.write_text(
            json.dumps({"id": "q1", "kind": "operator_proposed_gate", "status": "open", "ts": "1"}) + "\n",
            encoding="utf-8",
        )

        result = asyncio.run(server.TOOL_HANDLERS["get_proposal_queue"]({"repo": str(self.repo)}))
        self.assertEqual([row["queue_id"] for row in result], ["q1"])

    def test_get_proposal_lifecycle_reads_existing_artifacts(self):
        patch_dir = self.state.repo_state_dir / "patches"
        patch_dir.mkdir()
        (patch_dir / "p1.json").write_text(json.dumps({"patch_id": "p1", "status": "pending"}), encoding="utf-8")

        result = asyncio.run(server.TOOL_HANDLERS["get_proposal_lifecycle"]({"repo": str(self.repo)}))
        self.assertEqual([(row["proposal_kind"], row["artifact_id"]) for row in result], [("patch", "p1")])


if __name__ == "__main__":
    unittest.main()
