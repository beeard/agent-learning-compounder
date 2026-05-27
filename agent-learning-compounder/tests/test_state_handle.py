from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN = REPO_ROOT / "bin"
INIT = BIN / "init_learning_system"

sys.path.insert(0, str(BIN))


def _run_init(*args, cwd=None):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BIN) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, str(INIT), *map(str, args)],
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


class StateHandleTests(unittest.TestCase):
    def setUp(self):
        self._saved_env = {
            "AGENT_LEARNING_STATE_DIR": os.environ.pop("AGENT_LEARNING_STATE_DIR", None),
            "AGENT_LEARNING_USER": os.environ.pop("AGENT_LEARNING_USER", None),
            "AGENT_LEARNING_PERSONAL": os.environ.pop("AGENT_LEARNING_PERSONAL", None),
            "XDG_STATE_HOME": os.environ.pop("XDG_STATE_HOME", None),
        }
        from state_handle import StateHandle  # noqa: E402
        
        self.StateHandle = StateHandle

    def tearDown(self):
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_for_repo_reads_state_dir_from_agent_learning_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "repo"
            repo.mkdir()
            override = tmp_path / "state"
            payload = {"state_dir": str(override)}
            (repo / ".agent-learning.json").write_text(json.dumps(payload), encoding="utf-8")

            # Ensure the fallback chain would have picked a different path,
            # so precedence to .agent-learning.json is verified.
            os.environ["AGENT_LEARNING_STATE_DIR"] = str(tmp_path / "env")

            handle = self.StateHandle.for_repo(repo)
            expected = override.resolve() / "repos" / self.StateHandle.repo_id(repo)
            self.assertEqual(handle.state_root, override.resolve())
            self.assertEqual(handle.repo_state_dir, expected)

    def test_for_repo_falls_back_to_resolution_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "repo"
            repo.mkdir()
            state_dir = tmp_path / "state-root"
            os.environ["AGENT_LEARNING_STATE_DIR"] = str(state_dir)

            handle = self.StateHandle.for_repo(repo)
            from state_handle import repo_state_dir

            self.assertEqual(handle.repo_state_dir, repo_state_dir(repo))
            self.assertEqual(handle.state_root, state_dir.resolve())

    def test_for_repo_accepts_explicit_state_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "repo"
            repo.mkdir()
            explicit = tmp_path / "state-override"
            handle = self.StateHandle.for_repo(repo, state_dir=explicit)
            self.assertEqual(handle.state_root, explicit.resolve())
            self.assertEqual(handle.repo_state_dir, explicit.resolve() / "repos" / self.StateHandle.repo_id(repo))
            self.assertEqual(handle.events_jsonl, handle.repo_state_dir / "events.jsonl")

    def test_project_state_helper_accepts_explicit_state_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "repo"
            repo.mkdir()
            explicit = tmp_path / "state-override"
            from state_handle import project_state

            handle = project_state(repo, state_dir=explicit)

            self.assertEqual(handle.state_root, explicit.resolve())
            self.assertEqual(handle.repo_state_dir, explicit.resolve() / "repos" / self.StateHandle.repo_id(repo))

    def test_alc_agents_dirs_has_all_4_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "repo"
            repo.mkdir()

            handle = self.StateHandle.for_repo(repo)
            self.assertEqual(
                set(handle.alc_agents_dirs.keys()),
                {"dev", "test", "evals", "personal"},
            )

    def test_project_event_write_target_from_state_handle(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            state_root = Path(tmp) / "state"
            handle = self.StateHandle.for_repo(repo, state_dir=state_root)

            target = self.StateHandle.event_write_target(state=handle)

            self.assertEqual(target.event_dir, handle.repo_state_dir)
            self.assertEqual(target.events_jsonl, handle.events_jsonl)
            self.assertEqual(target.write_scope, "project_state_handle")

    def test_user_scope_prefers_agent_learning_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "user-root"
            os.environ["AGENT_LEARNING_USER"] = str(root)

            scope = self.StateHandle.user_scope()

            self.assertEqual(scope.root, root.resolve())
            self.assertEqual(scope.reports_dir, root.resolve() / "reports" / "agent-learning")
            self.assertEqual(scope.tier, "env_user")

    def test_user_scope_compat_personal_alias_is_classified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "personal-root"
            os.environ["AGENT_LEARNING_PERSONAL"] = str(root)

            scope = self.StateHandle.user_scope()

            self.assertEqual(scope.root, root.resolve())
            self.assertEqual(scope.reports_dir, root.resolve() / "reports" / "agent-learning")
            self.assertEqual(scope.tier, "legacy_env_personal")

    def test_background_event_write_target_is_not_repo_scoped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "background"

            target = self.StateHandle.event_write_target(background_root=root)

            self.assertEqual(target.event_dir, root.resolve())
            self.assertEqual(target.events_jsonl, root.resolve() / "events.jsonl")
            self.assertEqual(target.write_scope, "background_explicit_root")

    def test_event_write_target_rejects_conflicting_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            state = self.StateHandle.for_repo(repo)

            with self.assertRaisesRegex(ValueError, "ambiguous event write target"):
                self.StateHandle.event_write_target(state=state, repo=repo)

    def test_all_paths_are_absolute(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            handle = self.StateHandle.for_repo(repo)
            paths = [
                handle.repo,
                handle.state_root,
                handle.repo_state_dir,
                handle.reports_dir,
                handle.dashboard_dir,
                handle.alc_apply_log,
                handle.outcomes_json,
                handle.events_jsonl,
                handle.events_sqlite,
            ] + list(handle.alc_agents_dirs.values())
            for path in paths:
                self.assertTrue(path.is_absolute(), f"path not absolute: {path}")

    def test_init_learning_system_writes_state_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "repo"
            repo.mkdir()
            state_root = tmp_path / "state"

            result = _run_init(
                "--repo",
                repo,
                "--state-dir",
                state_root,
                "--install-repo-integration",
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            payload = json.loads((repo / ".agent-learning.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["state_dir"], str(state_root.resolve()))

    def test_mcp_dashboard_orchestrator_converge(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "repo"
            repo.mkdir()

            sys.path.insert(0, str(REPO_ROOT))
            from collect_hook_event import default_output  # noqa: E402
            from state_handle import repo_state_dir  # noqa: E402

            sys.path.insert(0, str(REPO_ROOT / "alc_mcp"))
            from alc_mcp import server as mcp_server  # noqa: E402

            canonical = self.StateHandle.for_repo(repo).repo_state_dir
            callback = canonical / "improvement-queue.jsonl"
            callback.parent.mkdir(parents=True, exist_ok=True)
            callback.write_text("", encoding="utf-8")

            paths = {
                "state_handle": repo_state_dir(repo),
                "collect": default_output(repo, None, None).parent,
                "mcp": mcp_server._improvement_queue_path(repo).parent,
            }

            for value in paths.values():
                self.assertEqual(value, canonical)


if __name__ == "__main__":
    unittest.main()
