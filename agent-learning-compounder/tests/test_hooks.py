from __future__ import annotations

import json
import os
import pathlib
import stat
import subprocess
import tempfile
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
HOOKS_JSON = REPO_ROOT / "hooks" / "hooks.json"
SESSION_START = REPO_ROOT / "hooks" / "session-start"
REFRESH_DASHBOARD = REPO_ROOT / "hooks" / "refresh_dashboard.py"


class HookTests(unittest.TestCase):
    def test_hooks_json_is_valid(self) -> None:
        payload = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        self.assertIn("hooks", payload)
        self.assertIn("SessionStart", payload["hooks"])
        self.assertIn("Stop", payload["hooks"])

    def test_session_start_is_executable_bash(self) -> None:
        mode = SESSION_START.stat().st_mode
        self.assertTrue(mode & stat.S_IXUSR)
        self.assertEqual(SESSION_START.read_text(encoding="utf-8").splitlines()[0], "#!/usr/bin/env bash")

    def test_refresh_dashboard_is_executable_python(self) -> None:
        mode = REFRESH_DASHBOARD.stat().st_mode
        self.assertTrue(mode & stat.S_IXUSR)
        self.assertEqual(REFRESH_DASHBOARD.read_text(encoding="utf-8").splitlines()[0], "#!/usr/bin/env python3")

    def test_refresh_dashboard_writes_static_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            repo = root / "repo"
            state = root / "state"
            repo.mkdir()
            env = os.environ.copy()
            env["ALC_PLUGIN_ROOT"] = str(REPO_ROOT)
            result = subprocess.run(
                [str(REFRESH_DASHBOARD), "--repo", str(repo), "--state", str(state)],
                cwd=repo,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            dashboards = list((state / "repos").glob("*/dashboard"))
            self.assertEqual(len(dashboards), 1)
            data = json.loads((dashboards[0] / "data.json").read_text(encoding="utf-8"))
            self.assertIn("generated_at", data)
            self.assertEqual(data["recommendations"], [])
            html = (dashboards[0] / "dashboard.html").read_text(encoding="utf-8")
            self.assertIn("Agent Learning Dashboard", html)
            self.assertIn('"recommendations"', html)

    def test_hooks_json_uses_claude_plugin_root(self) -> None:
        # hooks.json is the Claude Code plugin manifest. Claude Code substitutes
        # ${CLAUDE_PLUGIN_ROOT} at hook-fire time; ALC_PLUGIN_ROOT is the Codex
        # fallback used inside the hook scripts themselves, never in this file.
        text = HOOKS_JSON.read_text(encoding="utf-8")
        self.assertIn("${CLAUDE_PLUGIN_ROOT}", text)
        self.assertNotIn("${ALC_PLUGIN_ROOT}", text)

    def test_session_start_empty_state_does_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            state = root / "state"
            repo = root / "repo"
            state.mkdir()
            repo.mkdir()
            env = os.environ.copy()
            env["ALC_PLUGIN_ROOT"] = str(REPO_ROOT)
            env["AGENT_LEARNING_STATE_DIR"] = str(state)
            result = subprocess.run(
                [str(SESSION_START)],
                cwd=repo,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIsInstance(result.stdout, str)


if __name__ == "__main__":
    unittest.main()
