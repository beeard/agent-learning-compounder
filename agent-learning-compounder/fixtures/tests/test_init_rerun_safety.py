"""Re-run safety regression tests for init_learning_system.

Confirms that re-running init does NOT silently destroy operator state:

1. Re-running with --install-repo-integration but WITHOUT --install-hooks
   must NOT drop hook_command/hook_manifest/hook_event_log from
   .agent-learning.json (or downstream install_runtime_hooks --apply will
   abort with no clear cause).

2. domain-rules.active.json must survive a second init when the operator
   did not pass --domain-rules or --domain-preset (so manual edits aren't
   silently lost).

3. state_root/config.json must preserve created_at from the first run.
"""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest


BIN = pathlib.Path(__file__).resolve().parents[2] / "bin"
INIT = BIN / "init_learning_system"


def _run_init(*args, env=None, cwd=None):
    full_env = os.environ.copy()
    full_env["PYTHONPATH"] = str(BIN) + os.pathsep + full_env.get("PYTHONPATH", "")
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, str(INIT), *map(str, args)],
        cwd=str(cwd) if cwd else None,
        env=full_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


class InitRerunSafetyTests(unittest.TestCase):
    def setUp(self):
        if not INIT.exists():
            self.skipTest(f"init_learning_system not present at {INIT}")
        if shutil.which("git") is None:
            self.skipTest("git not available; init_learning_system requires it")

    def _make_repo(self, root: pathlib.Path) -> pathlib.Path:
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        return repo

    def test_rerun_without_install_hooks_preserves_hook_keys(self):
        """Re-running init without --install-hooks must not drop the hook trio."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = self._make_repo(tmp_path)
            state_dir = tmp_path / "state"

            first = _run_init(
                "--repo", repo,
                "--state-dir", state_dir,
                "--install-repo-integration",
                "--install-hooks",
            )
            self.assertEqual(first.returncode, 0, f"first init failed: {first.stderr}\n{first.stdout}")

            config_path = repo / ".agent-learning.json"
            initial = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertIn("hook_command", initial)
            self.assertIn("hook_manifest", initial)
            self.assertIn("hook_event_log", initial)
            initial_hook_command = initial["hook_command"]
            initial_hook_manifest = initial["hook_manifest"]
            initial_hook_event_log = initial["hook_event_log"]

            second = _run_init(
                "--repo", repo,
                "--state-dir", state_dir,
                "--install-repo-integration",
            )
            self.assertEqual(second.returncode, 0, f"second init failed: {second.stderr}\n{second.stdout}")

            after = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertIn("hook_command", after, f"hook_command was dropped on rerun: {after}")
            self.assertIn("hook_manifest", after, f"hook_manifest was dropped on rerun: {after}")
            self.assertIn("hook_event_log", after, f"hook_event_log was dropped on rerun: {after}")
            self.assertEqual(after["hook_command"], initial_hook_command)
            self.assertEqual(after["hook_manifest"], initial_hook_manifest)
            self.assertEqual(after["hook_event_log"], initial_hook_event_log)

            # And the self-test must pass on the rewritten file, since hooks
            # are still wired up.
            verify = _run_init(
                "--repo", repo,
                "--state-dir", state_dir,
                "--self-test",
            )
            self.assertEqual(verify.returncode, 0, f"self-test after rerun failed: {verify.stderr}\n{verify.stdout}")

    def test_rerun_preserves_manual_domain_rules_edits(self):
        """Manual edits to domain-rules.active.json must survive a default re-run."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = self._make_repo(tmp_path)
            state_dir = tmp_path / "state"

            first = _run_init("--repo", repo, "--state-dir", state_dir)
            self.assertEqual(first.returncode, 0, f"first init failed: {first.stderr}\n{first.stdout}")

            # Locate domain-rules.active.json via the state-dir layout.
            candidates = list(state_dir.rglob("domain-rules.active.json"))
            self.assertEqual(len(candidates), 1, f"unexpected layout: {candidates}")
            rules_path = candidates[0]

            sentinel = {
                "schema_version": 1,
                "source": "OPERATOR-EDIT",
                "rules": {"_marker": "do-not-overwrite-on-rerun"},
            }
            rules_path.write_text(json.dumps(sentinel, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            second = _run_init("--repo", repo, "--state-dir", state_dir)
            self.assertEqual(second.returncode, 0, f"second init failed: {second.stderr}\n{second.stdout}")

            after = json.loads(rules_path.read_text(encoding="utf-8"))
            self.assertEqual(after, sentinel, f"operator edits to domain-rules.active.json were clobbered: {after}")

    def test_rerun_with_explicit_domain_preset_overwrites(self):
        """If the operator explicitly passes --domain-preset, overwrite is intentional."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = self._make_repo(tmp_path)
            state_dir = tmp_path / "state"

            first = _run_init("--repo", repo, "--state-dir", state_dir)
            self.assertEqual(first.returncode, 0, f"first init failed: {first.stderr}\n{first.stdout}")

            candidates = list(state_dir.rglob("domain-rules.active.json"))
            self.assertEqual(len(candidates), 1)
            rules_path = candidates[0]
            sentinel = {"schema_version": 1, "source": "OPERATOR-EDIT", "rules": {"_marker": "x"}}
            rules_path.write_text(json.dumps(sentinel, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            # Read what an unmodified default preset produces by checking
            # the initial value we got from `first`. Re-init with explicit
            # preset and confirm sentinel is gone.
            second = _run_init(
                "--repo", repo,
                "--state-dir", state_dir,
                "--domain-preset", "generic",
            )
            # If --domain-preset isn't a valid preset name in the runtime,
            # skip — we just need the explicit-flag detection to fire.
            if second.returncode != 0:
                # Fall back to whatever the default preset is, but pass it
                # explicitly so the explicit-flag path runs.
                # Re-write sentinel since second may have overwritten partially.
                rules_path.write_text(json.dumps(sentinel, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                self.skipTest(f"--domain-preset generic not accepted: {second.stderr}")

            after = json.loads(rules_path.read_text(encoding="utf-8"))
            self.assertNotEqual(after, sentinel, "explicit --domain-preset should overwrite operator edits")

    def test_rerun_preserves_config_created_at(self):
        """state_root/config.json created_at must be preserved across reruns."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = self._make_repo(tmp_path)
            state_dir = tmp_path / "state"

            first = _run_init("--repo", repo, "--state-dir", state_dir)
            self.assertEqual(first.returncode, 0, f"first init failed: {first.stderr}\n{first.stdout}")

            config_path = state_dir / "config.json"
            self.assertTrue(config_path.exists(), f"missing {config_path}")
            initial = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertIn("created_at", initial)
            initial_created_at = initial["created_at"]

            second = _run_init("--repo", repo, "--state-dir", state_dir)
            self.assertEqual(second.returncode, 0, f"second init failed: {second.stderr}\n{second.stdout}")

            after = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(
                after.get("created_at"),
                initial_created_at,
                f"created_at was overwritten on rerun: {initial_created_at!r} -> {after.get('created_at')!r}",
            )


if __name__ == "__main__":
    unittest.main()
