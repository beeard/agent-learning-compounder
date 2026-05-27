from __future__ import annotations

import json
import os
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
CHECK = ROOT / "bin" / "check_runtime_drift"
MERGE_DEV_HOOKS = ROOT.parent / "scripts" / "merge_dev_hooks.py"


class RuntimeBoundaryTests(unittest.TestCase):
    def test_drift_checker_reports_repo_local_runtime_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            source = base / "source"
            runtime = base / ".runtime" / "codex" / "skills" / "agent-learning-compounder"
            (source / "bin").mkdir(parents=True)
            (runtime / "bin").mkdir(parents=True)
            (source / "bin" / "tool").write_text("source\n", encoding="utf-8")
            (runtime / "bin" / "tool").write_text("runtime\n", encoding="utf-8")

            result = subprocess.run(
                [
                    str(CHECK),
                    "--repo",
                    str(base),
                    "--source",
                    str(source),
                    "--runtime",
                    str(runtime),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("[DRIFT]", result.stdout)
            self.assertIn("changed: bin/tool", result.stdout)

    def test_drift_checker_is_ok_when_no_repo_local_runtime_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            source = base / "source"
            source.mkdir()
            (source / "file.txt").write_text("ok\n", encoding="utf-8")

            result = subprocess.run(
                [str(CHECK), "--repo", str(base), "--source", str(source)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("runtime artifacts: none found", result.stdout)

    def test_merge_dev_hooks_keeps_auto_distill_outputs_repo_local(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp)
            plugin = repo / "agent-learning-compounder"
            (plugin / "bin").mkdir(parents=True)
            (plugin / "hooks").mkdir(parents=True)
            for rel in (
                "bin/alc_bootstrap_pipeline",
                "hooks/refresh_dashboard.py",
                "bin/render_state_surface",
                "bin/auto_distill_session",
            ):
                path = plugin / rel
                path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                path.chmod(0o755)

            result = subprocess.run(
                [str(MERGE_DEV_HOOKS), "--repo", str(repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            settings = json.loads(
                (repo / ".claude" / "settings.local.json").read_text(encoding="utf-8")
            )
            stop_commands = [
                hook["command"]
                for row in settings["hooks"]["Stop"]
                for hook in row.get("hooks", [])
            ]
            auto_commands = [cmd for cmd in stop_commands if "auto_distill_session" in cmd]
            self.assertEqual(len(auto_commands), 1)
            command = auto_commands[0]
            self.assertIn(str(repo / ".runtime" / "agent-learning-user"), command)
            self.assertIn(str(repo / ".runtime" / "agent-learning-state"), command)
            self.assertIn("AGENT_LEARNING_SKILL_DIR=", command)
            self.assertNotIn(str(pathlib.Path.home() / ".agent-learning"), command)

    def test_merge_dev_hooks_replaces_stale_and_prunes_user_scope_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp)
            plugin = repo / "agent-learning-compounder"
            (plugin / "bin").mkdir(parents=True)
            (plugin / "hooks").mkdir(parents=True)
            for rel in (
                "bin/alc_bootstrap_pipeline",
                "hooks/refresh_dashboard.py",
                "bin/render_state_surface",
                "bin/auto_distill_session",
            ):
                path = plugin / rel
                path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                path.chmod(0o755)
            settings = repo / ".claude" / "settings.local.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "Stop": [
                                {
                                    "matcher": "",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": f"{plugin}/bin/auto_distill_session",
                                        }
                                    ],
                                }
                            ],
                            "PostToolUse": [
                                {
                                    "matcher": "Bash",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": "/home/tth/.claude/plugins/cache/understand-anything/x/hooks/auto-update",
                                        }
                                    ],
                                }
                            ],
                        }
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [str(MERGE_DEV_HOOKS), "--repo", str(repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(settings.read_text(encoding="utf-8"))
            commands = [
                hook["command"]
                for rows in payload["hooks"].values()
                for row in rows
                for hook in row.get("hooks", [])
            ]
            auto_commands = [cmd for cmd in commands if "auto_distill_session" in cmd]
            self.assertEqual(len(auto_commands), 1)
            self.assertIn("AGENT_LEARNING_USER=", auto_commands[0])
            self.assertFalse(any("understand-anything" in cmd for cmd in commands))

    def test_drift_checker_user_audit_mode_includes_user_runtime_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            source = base / "source"
            source.mkdir()
            (source / "file.txt").write_text("ok\n", encoding="utf-8")

            home = base / "home"
            user_runtime = home / ".claude" / "skills" / "agent-learning-compounder"
            (user_runtime / "sub").mkdir(parents=True)
            (user_runtime / "file.txt").write_text("ok\n", encoding="utf-8")

            run_env = os.environ.copy()
            run_env["HOME"] = str(home)

            result = subprocess.run(
                [
                    str(CHECK),
                    "--repo",
                    str(base),
                    "--source",
                    str(source),
                    "--include-user-runtimes",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                env=run_env,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("profile: user-audit", result.stdout)
            self.assertIn(str(user_runtime), result.stdout)


if __name__ == "__main__":
    unittest.main()
