import json
import os
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
INSTALL = None
if (ROOT / "install.sh").exists():
    INSTALL = ROOT / "install.sh"
elif (ROOT.parent / "install.sh").exists():
    INSTALL = ROOT.parent / "install.sh"


def run_install(*args, env=None, cwd=None):
    return subprocess.run(
        [str(INSTALL), *map(str, args)],
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


class InstallBootstrapTests(unittest.TestCase):
    def setUp(self):
        if INSTALL is None:
            self.skipTest("Install script is not available in this runtime (package-only bootstrap copy)")

    def test_bootstrap_repo_runtime_hint_is_parsed_portably(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            repo.mkdir()
            (repo / "AGENTS.md").write_text("# AGENTS\nruntime: codex\n", encoding="utf-8")

            result = run_install("--bootstrap-repo", repo, "--runtime", "auto")

            self.assertEqual(result.returncode, 0, f"{result.stderr}\n{result.stdout}")
            self.assertNotIn("awk: line 2: syntax error", result.stderr)
            self.assertIn("bootstrapped agent-learning-compounder into:", result.stdout)
            self.assertTrue((repo / ".agents" / "skills" / "agent-learning-compounder").is_dir())
            self.assertTrue((repo / ".agent-learning.json").exists())
            config = json.loads((repo / ".agent-learning.json").read_text(encoding="utf-8"))
            self.assertEqual(config["state_dir"], str((repo / ".agent-learning").resolve()))
            self.assertFalse((repo / ".codex" / "hooks.json").exists())

    def test_bootstrap_repo_runtime_hint_is_case_insensitive(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            repo.mkdir()
            (repo / "AGENTS.md").write_text("# AGENTS\nRuntime: Claude\n", encoding="utf-8")

            result = run_install("--bootstrap-repo", repo, "--runtime", "auto")

            self.assertEqual(result.returncode, 0, f"{result.stderr}\n{result.stdout}")
            self.assertTrue((repo / ".claude" / "skills" / "agent-learning-compounder").is_dir())
            self.assertFalse((repo / ".agents" / "skills" / "agent-learning-compounder").exists())
            config = json.loads((repo / ".agent-learning" / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["runtime"], "claude")

    def test_bootstrap_repo_does_not_apply_runtime_hooks_without_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            repo.mkdir()
            (repo / "AGENTS.md").write_text("# AGENTS\nruntime: codex\n", encoding="utf-8")

            result = run_install("--bootstrap-repo", repo, "--runtime", "codex")
            self.assertEqual(result.returncode, 0, f"{result.stderr}\n{result.stdout}")
            self.assertFalse((repo / ".codex" / "hooks.json").exists())

    def test_bootstrap_repo_creates_private_hook_event_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            repo.mkdir()

            previous_umask = os.umask(0o002)
            try:
                result = run_install("--bootstrap-repo", repo, "--runtime", "codex")
            finally:
                os.umask(previous_umask)

            self.assertEqual(result.returncode, 0, f"{result.stderr}\n{result.stdout}")
            config = json.loads((repo / ".agent-learning.json").read_text(encoding="utf-8"))
            hook_log = pathlib.Path(config["hook_event_log"])
            self.assertTrue(hook_log.exists())
            self.assertEqual(hook_log.stat().st_mode & 0o777, 0o600)

    def test_bootstrap_repo_ships_renderable_dashboard_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            repo.mkdir()

            result = run_install("--bootstrap-repo", repo, "--runtime", "codex")
            self.assertEqual(result.returncode, 0, f"{result.stderr}\n{result.stdout}")

            skill_root = repo / ".agents" / "skills" / "agent-learning-compounder"
            bundle = skill_root / "dashboard" / "web" / "dist" / "index.html"
            self.assertTrue(bundle.exists())

            render = subprocess.run(
                [
                    "python3",
                    str(skill_root / "bin" / "render_dashboard"),
                    "--personal",
                    str(repo / ".agent-learning"),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(render.returncode, 0, f"{render.stderr}\n{render.stdout}")
            rendered = repo / ".agent-learning" / "reports" / "agent-learning" / "latest-dashboard.html"
            self.assertTrue(rendered.exists())
            self.assertIn('"personal_root"', rendered.read_text(encoding="utf-8"))

    def test_bootstrap_repo_apply_runtime_hooks_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            repo.mkdir()
            (repo / "AGENTS.md").write_text("# AGENTS\nruntime: codex\n", encoding="utf-8")

            dry = run_install("--bootstrap-repo", repo, "--runtime", "codex")
            self.assertEqual(dry.returncode, 0, f"{dry.stderr}\n{dry.stdout}")
            self.assertFalse((repo / ".codex" / "hooks.json").exists())

            applied = run_install("--bootstrap-repo", repo, "--runtime", "codex", "--apply-runtime-hooks")
            self.assertEqual(applied.returncode, 0, f"{applied.stderr}\n{applied.stdout}")
            self.assertTrue((repo / ".codex" / "hooks.json").exists())
