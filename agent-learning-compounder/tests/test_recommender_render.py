from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

from recommender_render import run


class RecommenderRenderTests(unittest.TestCase):
    def _make_state(self, repo_dir: pathlib.Path) -> "state_handle.StateHandle":
        import state_handle

        return state_handle.StateHandle.for_repo(repo_dir)

    def _write_file(self, path: pathlib.Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_run_writes_patch_bundles_and_suggestions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            repo.mkdir()
            state = self._make_state(repo)
            state.reports_dir.mkdir(parents=True, exist_ok=True)
            state.repo_state_dir.mkdir(parents=True, exist_ok=True)

            anomaly_target = repo / "notes" / "anomaly.md"
            routing_target = repo / "notes" / "routing.md"
            agent_target = repo / "agents" / "model-swap.md"
            self._write_file(anomaly_target, "anomaly notes\n")
            self._write_file(routing_target, "routing notes\n")
            self._write_file(agent_target, "name: model-swap\nmodel: inherit\n")

            recommendations = [
                {"kind": "anomaly_investigate", "recommendation_id": "a-1", "target": str(anomaly_target)},
                {"kind": "skill_routing_review", "recommendation_id": "r-1", "target": str(routing_target)},
                {
                    "kind": "model_swap_candidate",
                    "recommendation_id": "m-1",
                    "agent": str(agent_target),
                    "from_model": "inherit",
                    "to_model": "opus",
                },
                {"kind": "agent_spawn_suggestion", "recommendation_id": "s-1", "agent_name": "new-agent"},
                {"kind": "workflow_chain", "recommendation_id": "w-1", "title": "Suggested workflow", "steps": ["step-1", "step-2"]},
            ]
            self._write_file(state.reports_dir / "recommendations.json", json.dumps(recommendations, indent=2))

            written, suggestions, skipped = run(state)

            self.assertEqual(written, 4)
            self.assertEqual(len(skipped), 0)
            self.assertEqual(len(suggestions), 1)
            self.assertEqual(suggestions[0]["recommendation_id"], "w-1")
            self.assertEqual(suggestions[0]["kind"], "workflow_chain")

            patch_dir = state.repo_state_dir / "patches"
            patch_files = sorted(path.name for path in patch_dir.glob("*.json"))
            self.assertEqual(len(patch_files), 4)
            for name in patch_files:
                payload = json.loads((patch_dir / name).read_text(encoding="utf-8"))
                self.assertIn("skill_manage_op", payload)
                self.assertIn("preflight", payload)
                self.assertIn("revert_op", payload)
                self.assertIn("recommendation_id", payload)
                self.assertEqual(payload["lifecycle"]["proposal_kind"], "patch")
                self.assertEqual(payload["lifecycle"]["status"], "pending")
                self.assertEqual(payload["lifecycle"]["artifact_id"], payload["patch_id"])
                self.assertNotIn("copy_to_clipboard", json.dumps(payload))

            suggestions_path = state.repo_state_dir / "suggestions.json"
            self.assertTrue(suggestions_path.exists())
            suggestion_payload = json.loads(suggestions_path.read_text(encoding="utf-8"))
            self.assertEqual(len(suggestion_payload["suggestions"]), 1)
            self.assertEqual(suggestion_payload["suggestions"][0]["title"], "Suggested workflow")
            self.assertEqual(suggestion_payload["suggestions"][0]["kind"], "workflow_chain")
            self.assertEqual(suggestion_payload["suggestions"][0]["lifecycle"]["proposal_kind"], "workflow_chain")
            self.assertEqual(suggestion_payload["suggestions"][0]["lifecycle"]["status"], "suggested")

            # workflow_chain must never land in patches/
            self.assertFalse(any(name.startswith("workflow_chain") for name in patch_files))

    def test_prevalidate_skips_failed_recommendations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            repo = tmp / "repo"
            repo.mkdir()
            state = self._make_state(repo)
            state.reports_dir.mkdir(parents=True, exist_ok=True)

            rec_path = state.reports_dir / "recommendations.json"
            rec_path.write_text(
                json.dumps(
                    [
                        {
                            "kind": "anomaly_investigate",
                            "recommendation_id": "bad-1",
                            "target": str(repo / "notes.md"),
                            "validation_command": "python3 -c 'print(\"bad\")'",
                        },
                        {
                            "kind": "anomaly_investigate",
                            "recommendation_id": "good-1",
                            "target": str(repo / "notes2.md"),
                            "validation_command": "python3 -c 'print(\"good\")'",
                        },
                    ],
                    indent=2,
                ),
                encoding="utf-8",
            )
            self._write_file(repo / "notes.md", "base\n")
            self._write_file(repo / "notes2.md", "base2\n")

            class FakeResult:
                def __init__(self, code: int, cmd: str) -> None:
                    self.exit_code = code
                    self.command = cmd

            def fake_run(*args, **kwargs):
                command = kwargs.get("command", "")
                if "good" in command:
                    return FakeResult(0, command)
                return FakeResult(1, command)

            with mock.patch("recommender_render.run_in_sandbox", side_effect=fake_run):
                written, suggestions, skipped = run(state, prevalidate=True)

            self.assertEqual(written, 1)
            self.assertEqual(len(skipped), 1)
            self.assertEqual(len(suggestions), 0)
            self.assertIn("bad-1", skipped[0]["recommendation_id"])
            self.assertEqual(len(list(state.repo_state_dir.glob("patches/*.json"))), 1)


if __name__ == "__main__":
    unittest.main()
