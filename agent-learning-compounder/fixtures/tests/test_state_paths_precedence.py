"""Lock the documented precedence chain of resolve_state_dir.

Precedence (highest wins):
  1. --state-dir
  2. AGENT_LEARNING_STATE_DIR env var
  3. --personal
  4. <repo>/.agent-learning
  5. $XDG_STATE_HOME/agent-learning
  6. ~/.local/state/agent-learning
"""

import os
import pathlib
import sys
import tempfile
import unittest


BIN = pathlib.Path(__file__).resolve().parents[2] / "bin"
sys.path.insert(0, str(BIN))

from state_handle import resolve_state_dir  # noqa: E402


class StatePathsPrecedenceTests(unittest.TestCase):
    def setUp(self):
        # Snapshot env vars we mutate; restore in tearDown so tests don't leak.
        self._saved_env = {
            "AGENT_LEARNING_STATE_DIR": os.environ.pop("AGENT_LEARNING_STATE_DIR", None),
            "XDG_STATE_HOME": os.environ.pop("XDG_STATE_HOME", None),
            "HOME": os.environ.get("HOME"),
        }

    def tearDown(self):
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_explicit_state_dir_wins_over_all_other_tiers(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            explicit = tmp_path / "explicit"
            os.environ["AGENT_LEARNING_STATE_DIR"] = str(tmp_path / "env")
            os.environ["XDG_STATE_HOME"] = str(tmp_path / "xdg")
            personal = tmp_path / "personal"
            repo = tmp_path / "repo"
            repo.mkdir()
            result = resolve_state_dir(
                state_dir=explicit, personal=personal, repo=repo
            )
            self.assertEqual(result, explicit.resolve())

    def test_env_var_wins_when_state_dir_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            env_target = tmp_path / "env"
            os.environ["AGENT_LEARNING_STATE_DIR"] = str(env_target)
            os.environ["XDG_STATE_HOME"] = str(tmp_path / "xdg")
            personal = tmp_path / "personal"
            repo = tmp_path / "repo"
            repo.mkdir()
            result = resolve_state_dir(state_dir=None, personal=personal, repo=repo)
            self.assertEqual(result, env_target.resolve())

    def test_personal_wins_over_repo_and_xdg(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            os.environ["XDG_STATE_HOME"] = str(tmp_path / "xdg")
            personal = tmp_path / "personal"
            repo = tmp_path / "repo"
            repo.mkdir()
            result = resolve_state_dir(state_dir=None, personal=personal, repo=repo)
            self.assertEqual(
                result,
                (personal.resolve() / "reports" / "agent-learning"),
            )

    def test_repo_wins_over_xdg_when_personal_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            os.environ["XDG_STATE_HOME"] = str(tmp_path / "xdg")
            repo = tmp_path / "repo"
            repo.mkdir()
            result = resolve_state_dir(state_dir=None, personal=None, repo=repo)
            self.assertEqual(result, repo.resolve() / ".agent-learning")

    def test_xdg_wins_over_home_when_repo_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            xdg = tmp_path / "xdg"
            os.environ["XDG_STATE_HOME"] = str(xdg)
            result = resolve_state_dir(state_dir=None, personal=None, repo=None)
            self.assertEqual(result, (xdg.resolve() / "agent-learning"))

    def test_home_fallback_when_nothing_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            os.environ["HOME"] = str(tmp_path)
            result = resolve_state_dir(state_dir=None, personal=None, repo=None)
            self.assertEqual(
                result,
                pathlib.Path(tmp_path) / ".local" / "state" / "agent-learning",
            )

    def test_lower_tier_does_not_override_higher_tier(self):
        # Repeats the chain in a single test so future drift trips one case.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            repo.mkdir()
            personal = tmp_path / "personal"
            os.environ["XDG_STATE_HOME"] = str(tmp_path / "xdg")
            # repo set -> XDG must NOT win.
            self.assertEqual(
                resolve_state_dir(state_dir=None, personal=None, repo=repo),
                repo.resolve() / ".agent-learning",
            )
            # personal set -> repo must NOT win.
            self.assertEqual(
                resolve_state_dir(state_dir=None, personal=personal, repo=repo),
                personal.resolve() / "reports" / "agent-learning",
            )
            # env set -> personal must NOT win.
            os.environ["AGENT_LEARNING_STATE_DIR"] = str(tmp_path / "env")
            self.assertEqual(
                resolve_state_dir(state_dir=None, personal=personal, repo=repo),
                (tmp_path / "env").resolve(),
            )
            # explicit state_dir set -> env must NOT win.
            self.assertEqual(
                resolve_state_dir(
                    state_dir=tmp_path / "explicit", personal=personal, repo=repo
                ),
                (tmp_path / "explicit").resolve(),
            )


if __name__ == "__main__":
    unittest.main()
