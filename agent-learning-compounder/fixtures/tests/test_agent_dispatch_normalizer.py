import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "bin"))

from agent_dispatch import DEFAULT_TELEMETRY_CONFIG, normalize_agent_dispatch  # noqa: E402


class AgentDispatchNormalizerTests(unittest.TestCase):
    def test_nested_agent_and_task_payload_normalizes_to_canonical_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            raw = {
                "agent": {
                    "role": "builder",
                    "backend": "codex-exec",
                    "id": "agent-1",
                    "mode": "background",
                    "model": "gpt-5.3-codex-spark",
                    "effort": "low",
                    "sandbox": "workspace-write",
                },
                "task": {
                    "id": "dispatch-1",
                    "write_scope": ["src/app.ts", "/etc/passwd"],
                    "worktree": str(repo / ".worktrees" / "dispatch-1"),
                    "branch": "wt/dispatch-1",
                },
                "parent_correlation_id": "parent-1",
            }

            row = normalize_agent_dispatch(raw, repo, DEFAULT_TELEMETRY_CONFIG)

            self.assertEqual(row["agent_role"], "builder")
            self.assertEqual(row["agent_backend"], "codex-exec")
            self.assertEqual(row["agent_id"], "agent-1")
            self.assertEqual(row["dispatch_id"], "dispatch-1")
            self.assertEqual(row["agent_mode"], "background")
            self.assertEqual(row["agent_model"], "gpt-5.3-codex-spark")
            self.assertEqual(row["agent_effort"], "low")
            self.assertEqual(row["agent_sandbox"], "workspace-write")
            self.assertEqual(row["agent_write_scope"][0], "src/app.ts")
            self.assertTrue(row["agent_write_scope"][1].startswith("<outside_repo:"))
            self.assertEqual(row["agent_worktree"], ".worktrees/dispatch-1")
            self.assertEqual(row["agent_branch"], "wt/dispatch-1")
            self.assertEqual(row["parent_correlation_id"], "parent-1")

    def test_model_and_scope_flags_drop_only_their_field_groups(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            row = normalize_agent_dispatch(
                {
                    "agent_role": "builder",
                    "agent_model": "gpt-5.3-codex-spark",
                    "agent_effort": "low",
                    "agent_sandbox": "workspace-write",
                    "agent_write_scope": ["src/app.ts"],
                    "agent_worktree": str(repo / ".worktrees" / "dispatch-1"),
                    "agent_branch": "wt/dispatch-1",
                },
                repo,
                {
                    "agent_dispatch": True,
                    "agent_dispatch_model": False,
                    "agent_dispatch_scope": False,
                },
            )

            self.assertEqual(row, {"agent_role": "builder"})

    def test_dispatch_flag_disables_all_dispatch_fields(self):
        row = normalize_agent_dispatch(
            {
                "agent_role": "builder",
                "agent_model": "gpt-5.3-codex-spark",
                "agent_write_scope": ["src/app.ts"],
            },
            None,
            {
                "agent_dispatch": False,
                "agent_dispatch_model": True,
                "agent_dispatch_scope": True,
            },
        )

        self.assertEqual(row, {})


if __name__ == "__main__":
    unittest.main()
