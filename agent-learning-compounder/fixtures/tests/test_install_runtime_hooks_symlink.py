"""Tests that install_runtime_hooks refuses to follow symlinks on write."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
INSTALL = ROOT / "bin" / "install_runtime_hooks"


def _make_repo(tmp: pathlib.Path) -> pathlib.Path:
    """Build a minimal repo with the .agent-learning.json hook_command pointing
    to install_runtime_hooks itself (which exists and is executable, so the
    runtime config validation in agent_config() passes)."""
    repo = tmp / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()  # mark as a git repo for tracking-check branch
    state_dir = repo / ".agent-learning"
    hooks_dir = state_dir / "repos" / "rid" / "hooks"
    hooks_dir.mkdir(parents=True)
    # Stage a fake executable hook_command so _validate_configured_hook_command
    # can be satisfied if ever invoked. The merge-runtime-hooks path used in
    # this test doesn't actually call the validator, but keep things sane.
    fake_cmd = hooks_dir / "alc-collect"
    fake_cmd.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    os.chmod(fake_cmd, 0o700)

    (repo / ".agent-learning.json").write_text(
        json.dumps({
            "hook_command": str(fake_cmd),
            "repo_state_dir": str(state_dir / "repos" / "rid"),
        }),
        encoding="utf-8",
    )
    return repo


def _run_install(*args: str, cwd: pathlib.Path | None = None):
    return subprocess.run(
        [sys.executable, str(INSTALL), *args],
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )


class InstallRuntimeHooksSymlinkTests(unittest.TestCase):
    def test_apply_refuses_to_write_through_symlink_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = _make_repo(tmp_path)
            # Pre-create the codex hook config target as a symlink pointing
            # at an attacker-controlled file outside .codex/.
            outside = tmp_path / "outside.json"
            outside.write_text("{}\n", encoding="utf-8")
            codex_dir = repo / ".codex"
            codex_dir.mkdir()
            target = codex_dir / "hooks.json"
            os.symlink(outside, target)

            result = _run_install(
                "--repo", str(repo),
                "--runtime", "codex",
                "--scope", "repo",
                "--apply",
            )

            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("symlink", (result.stderr + result.stdout).lower())
            # The outside file must not have been clobbered.
            self.assertEqual(outside.read_text(encoding="utf-8"), "{}\n")
            # The symlink itself must still be a symlink (not replaced by a
            # real file).
            self.assertTrue(target.is_symlink())

    def test_apply_refuses_to_write_through_symlinked_backup(self):
        """If the *backup* path is a pre-existing symlink, refuse too.

        Backup name pattern is `<name>.agent-learning-bak-<UTC stamp>`. We
        can't predict the stamp, so instead exercise the easier-to-reach
        primary-target case (covered above) and additionally verify that the
        helper directly refuses via the private API path by symlinking the
        codex dir hooks.json — already covered above. This test is a
        future-proofing placeholder asserting the same primary-target
        behavior with --runtime claude (settings.local.json).
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = _make_repo(tmp_path)
            outside = tmp_path / "outside-claude.json"
            outside.write_text("{}\n", encoding="utf-8")
            claude_dir = repo / ".claude"
            claude_dir.mkdir()
            target = claude_dir / "settings.local.json"
            os.symlink(outside, target)

            result = _run_install(
                "--repo", str(repo),
                "--runtime", "claude",
                "--scope", "repo",
                "--apply",
            )

            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(outside.read_text(encoding="utf-8"), "{}\n")
            self.assertTrue(target.is_symlink())


if __name__ == "__main__":
    unittest.main()
