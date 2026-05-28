from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
INSTALL = ROOT / "install.sh"
SKILL_NAME = "agent-learning-compounder"


def _install_test_path(base: pathlib.Path) -> str:
    bin_dir = base / "bin"
    bin_dir.mkdir(exist_ok=True)
    python_link = bin_dir / "python3"
    if not python_link.exists():
        python_link.symlink_to(pathlib.Path(sys.executable))
    fake_pnpm = bin_dir / "pnpm"
    fake_pnpm.write_text("#!/bin/sh\nexit 127\n", encoding="utf-8")
    fake_pnpm.chmod(0o755)
    return f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"


def _run_install(
    args: list[str],
    *,
    base: pathlib.Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    home = base / "home"
    home.mkdir(exist_ok=True)
    run_env = {
        "HOME": str(home),
        "PATH": _install_test_path(base),
    }
    if env:
        run_env.update(env)
    return subprocess.run(
        [str(INSTALL), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        cwd=str(ROOT),
        env=run_env,
    )


def _assert_skill_installed(test: unittest.TestCase, dest: pathlib.Path) -> None:
    test.assertTrue((dest / "skills" / "alc-core" / "SKILL.md").exists(), f"{dest} was not installed")
    test.assertTrue((dest / "bin").is_dir(), f"{dest} has no bin directory")


class InstallTargetTests(unittest.TestCase):
    def test_codex_flag_installs_under_agents_home_skills(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            agents_home = base / "agents-home"

            result = _run_install(
                ["--codex"],
                base=base,
                env={"AGENTS_HOME": str(agents_home)},
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            dest = agents_home / "skills" / SKILL_NAME
            _assert_skill_installed(self, dest)
            self.assertIn(str(dest), result.stdout)

    def test_codex_home_flag_installs_under_codex_home_skills(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            codex_home = base / "codex-home"

            result = _run_install(
                ["--codex-home"],
                base=base,
                env={"CODEX_HOME": str(codex_home)},
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            dest = codex_home / "skills" / SKILL_NAME
            _assert_skill_installed(self, dest)
            self.assertIn(str(dest), result.stdout)

    def test_claude_flag_installs_under_claude_home_skills(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            claude_home = base / "claude-home"

            result = _run_install(
                ["--claude"],
                base=base,
                env={"CLAUDE_HOME": str(claude_home)},
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            dest = claude_home / "skills" / SKILL_NAME
            _assert_skill_installed(self, dest)
            self.assertIn(str(dest), result.stdout)

    def test_plugin_mode_installs_under_claude_plugins_and_rejects_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            claude_home = base / "claude-home"

            result = _run_install(
                ["--plugin"],
                base=base,
                env={"CLAUDE_HOME": str(claude_home)},
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            dest = claude_home / "plugins" / SKILL_NAME
            _assert_skill_installed(self, dest)
            self.assertIn(str(dest), result.stdout)

            repo = base / "repo"
            repo.mkdir()
            rejected = _run_install(
                ["--plugin", "--bootstrap-repo", str(repo)],
                base=base,
                env={"CLAUDE_HOME": str(claude_home)},
            )

            self.assertEqual(rejected.returncode, 2, rejected.stdout + rejected.stderr)
            self.assertIn("cannot be combined with --bootstrap-repo", rejected.stderr)

    def test_explicit_target_overrides_runtime_default_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            target = base / "explicit-target"
            agents_home = base / "agents-home"

            result = _run_install(
                ["--target", str(target), "--runtime", "claude"],
                base=base,
                env={"AGENTS_HOME": str(agents_home)},
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            dest = target / SKILL_NAME
            _assert_skill_installed(self, dest)
            self.assertIn(str(dest), result.stdout)
            self.assertFalse((agents_home / "skills" / SKILL_NAME).exists())

    def test_runtime_all_requires_bootstrap_or_explicit_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)

            result = _run_install(["--runtime", "all"], base=base)

            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("--runtime all requires --bootstrap-repo", result.stderr)

            target = base / "explicit-target"
            explicit = _run_install(["--runtime", "all", "--target", str(target)], base=base)

            self.assertEqual(explicit.returncode, 0, explicit.stdout + explicit.stderr)
            _assert_skill_installed(self, target / SKILL_NAME)

    def test_bootstrap_runtime_all_stages_both_repo_local_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            repo = base / "repo"
            repo.mkdir()

            result = _run_install(
                [
                    "--bootstrap-repo",
                    str(repo),
                    "--runtime",
                    "all",
                    "--no-first-run-index",
                ],
                base=base,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            _assert_skill_installed(self, repo / ".agents" / "skills" / SKILL_NAME)
            _assert_skill_installed(self, repo / ".claude" / "skills" / SKILL_NAME)

    def test_bootstrap_repo_runtime_hint_selects_claude(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            repo = base / "repo"
            repo.mkdir()
            (repo / "AGENTS.md").write_text("runtime: claude\n", encoding="utf-8")

            result = _run_install(
                [
                    "--bootstrap-repo",
                    str(repo),
                    "--no-first-run-index",
                ],
                base=base,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            _assert_skill_installed(self, repo / ".claude" / "skills" / SKILL_NAME)
            self.assertFalse((repo / ".agents" / "skills" / SKILL_NAME).exists())

    def test_environment_runtime_selects_claude_without_zero_config_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            claude_home = base / "claude-home"
            agents_home = base / "agents-home"

            result = _run_install(
                [],
                base=base,
                env={
                    "AGENT_LEARNING_RUNTIME": "claude",
                    "CLAUDE_HOME": str(claude_home),
                    "AGENTS_HOME": str(agents_home),
                },
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            dest = claude_home / "skills" / SKILL_NAME
            _assert_skill_installed(self, dest)
            self.assertIn(str(dest), result.stdout)
            self.assertNotIn("auto-detected runtime", result.stderr)
            self.assertFalse((agents_home / "skills" / SKILL_NAME).exists())

    def test_explicit_runtime_wins_over_environment_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            claude_home = base / "claude-home"
            agents_home = base / "agents-home"

            result = _run_install(
                ["--runtime", "codex"],
                base=base,
                env={
                    "AGENT_LEARNING_RUNTIME": "claude",
                    "CLAUDE_HOME": str(claude_home),
                    "AGENTS_HOME": str(agents_home),
                },
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            _assert_skill_installed(self, agents_home / "skills" / SKILL_NAME)
            self.assertFalse((claude_home / "skills" / SKILL_NAME).exists())

    def test_existing_destination_is_backed_up_and_symlink_root_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            target = base / "target"

            first = _run_install(["--target", str(target)], base=base)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            marker = target / SKILL_NAME / "local-marker.txt"
            marker.write_text("existing\n", encoding="utf-8")

            second = _run_install(["--target", str(target)], base=base)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            backups = sorted(target.glob(f"{SKILL_NAME}.bak-*"))
            self.assertEqual(len(backups), 1)
            self.assertTrue((backups[0] / "local-marker.txt").exists())

            symlink_root = base / "symlink-root"
            symlink_root.symlink_to(target)
            refused = _run_install(["--target", str(symlink_root)], base=base)
            self.assertEqual(refused.returncode, 1, refused.stdout + refused.stderr)
            self.assertIn("refusing to install into symlinked target root", refused.stderr)

    def test_wrappers_forward_arguments_to_install_sh(self) -> None:
        npm_wrapper = (ROOT / "scripts" / "alc-install.mjs").read_text(encoding="utf-8")
        bootstrap = (ROOT / "bootstrap.sh").read_text(encoding="utf-8")

        self.assertIn("const installSh = resolve(pkgRoot, 'install.sh');", npm_wrapper)
        self.assertIn("spawnSync(installSh, process.argv.slice(2)", npm_wrapper)
        self.assertIn('exec "$tmp/install.sh" "$@"', bootstrap)


if __name__ == "__main__":
    unittest.main()
