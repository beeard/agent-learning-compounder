from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

from runtime_topology import (
    RuntimeTopology,
    adapter_command,
    build_runtime_drift_plan,
    build_runtime_topology,
    config_for_runtime,
    dev_hook_specs,
)


class RuntimeTopologyTests(unittest.TestCase):
    def test_build_runtime_topology_is_repo_rooted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp) / "repo"
            repo.mkdir()

            topology = build_runtime_topology(repo)
            self.assertEqual(topology.repo, repo.resolve())
            self.assertEqual(topology.source_skill_root, (repo / "agent-learning-compounder").resolve())
            self.assertIsInstance(topology, RuntimeTopology)
            self.assertEqual(topology.dev_state_user_root, (repo / ".runtime" / "agent-learning-user").resolve())
            self.assertEqual(topology.dev_state_root, (repo / ".runtime" / "agent-learning-state").resolve())

    def test_candidate_sets_are_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp)
            topology = build_runtime_topology(repo)
            self.assertEqual(len(topology.repo_runtime_candidates), len(set(topology.repo_runtime_candidates)))
            self.assertEqual(len(topology.user_runtime_candidates), len(set(topology.user_runtime_candidates)))

    def test_config_targets_for_runtime_and_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp)
            self.assertEqual(config_for_runtime(repo, "claude", "repo"), repo / ".claude" / "settings.local.json")
            self.assertEqual(config_for_runtime(repo, "codex", "repo"), repo / ".codex" / "hooks.json")
            self.assertEqual(config_for_runtime(repo, "claude", "user"), pathlib.Path.home() / ".claude" / "settings.json")
            self.assertEqual(config_for_runtime(repo, "codex", "user"), pathlib.Path.home() / ".codex" / "hooks.json")
            with self.assertRaises(ValueError):
                config_for_runtime(repo, "unknown", "repo")

    def test_dev_hook_specs_use_repo_local_targets_and_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp)
            specs = dev_hook_specs(repo)
            stop_commands = [entry for entry in specs if entry["match"] == "auto_distill_session"]
            self.assertEqual(len(stop_commands), 1)
            command = stop_commands[0]["command"]
            self.assertIn(str(repo / ".runtime" / "agent-learning-user"), command)
            self.assertIn(str(repo / ".runtime" / "agent-learning-state"), command)
            self.assertIn("AGENT_LEARNING_SKILL_DIR=", command)
            self.assertIn("AGENT_LEARNING_PERSONAL=", command)
            self.assertIn("AGENT_LEARNING_USER=", command)
            self.assertIn("auto_distill_session", command)

    def test_adapter_command_renders_install_runtime_hooks_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp)
            command = adapter_command(repo, "codex", "SessionStart")

            self.assertIn("install_runtime_hooks", command)
            self.assertIn("--adapter", command)
            self.assertIn("--runtime codex", command)
            self.assertIn("--event SessionStart", command)
            self.assertNotIn("runtime_topology.py --adapter", command)

    def test_drift_plans_are_mode_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp)
            topology = build_runtime_topology(repo)

            repo_only = build_runtime_drift_plan(repo)
            self.assertEqual(repo_only.mode, "repo-only")
            self.assertIsNone(repo_only.write_target)
            self.assertEqual(tuple(topology.repo_runtime_candidates), repo_only.read_targets)

            user_audit = build_runtime_drift_plan(repo, include_user_runtimes=True)
            self.assertEqual(user_audit.mode, "user-audit")
            self.assertTrue(len(user_audit.read_targets) >= len(topology.repo_runtime_candidates))
            self.assertIn(pathlib.Path.home() / ".agents" / "skills" / "agent-learning-compounder", user_audit.read_targets)

            explicit = pathlib.Path(repo) / "explicit-runtime"
            explicit.mkdir()
            explicit_only = build_runtime_drift_plan(repo, explicit_runtimes=[explicit])
            self.assertEqual(explicit_only.mode, "explicit")
            self.assertEqual(explicit_only.read_targets, (explicit.resolve(),))

            explicit_user_audit = build_runtime_drift_plan(
                repo,
                explicit_runtimes=[explicit],
                include_user_runtimes=True,
            )
            self.assertEqual(explicit_user_audit.mode, "explicit+user-audit")
            self.assertIn(explicit.resolve(), explicit_user_audit.read_targets)


if __name__ == "__main__":
    unittest.main()
