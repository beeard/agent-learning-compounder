"""Self-test exit-code + diagnostic coverage for init_learning_system.

Exercises the failure mode where .agent-learning.json exists but is missing
required keys (e.g. someone hand-edited it or an earlier install crashed
mid-write). The self-test must exit non-zero with a stderr message that
names the missing key.
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
    # Make sure the bin/ dir is importable as the script does sibling imports.
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


class InitSelfTestFailureModeTests(unittest.TestCase):
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

    def test_self_test_fails_when_hook_command_present_but_hook_manifest_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = self._make_repo(tmp_path)
            state_dir = tmp_path / "state"

            ok = _run_init(
                "--repo", repo,
                "--state-dir", state_dir,
                "--install-repo-integration",
                "--install-hooks",
                "--self-test",
            )
            self.assertEqual(ok.returncode, 0, f"first init failed: {ok.stderr}\n{ok.stdout}")

            config_path = repo / ".agent-learning.json"
            self.assertTrue(config_path.exists())
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            # Sanity: full hook trio was written.
            self.assertIn("hook_command", payload)
            self.assertIn("hook_manifest", payload)
            self.assertIn("hook_event_log", payload)

            # Mutate: drop hook_manifest while keeping hook_command. The self-test
            # must complain about the missing key.
            del payload["hook_manifest"]
            config_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            fail = _run_init(
                "--repo", repo,
                "--state-dir", state_dir,
                "--install-repo-integration",
                "--install-hooks",
                "--self-test",
            )
            # init rewrites the config, but we want to test the self-test
            # diagnostic path on a pre-mutated file. So run a self-test on
            # a freshly-mutated file by re-mutating after install.
            # The above re-init will have re-written hook_manifest, so mutate
            # again and run self-test only.
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            del payload["hook_manifest"]
            config_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            self_test_only = _run_init(
                "--repo", repo,
                "--state-dir", state_dir,
                "--self-test",
            )
            self.assertNotEqual(
                self_test_only.returncode, 0,
                f"self-test should fail; stdout={self_test_only.stdout!r} stderr={self_test_only.stderr!r}",
            )
            self.assertIn("hook_manifest", self_test_only.stderr)

    def test_self_test_fails_when_integration_key_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = self._make_repo(tmp_path)
            state_dir = tmp_path / "state"

            ok = _run_init(
                "--repo", repo,
                "--state-dir", state_dir,
                "--install-repo-integration",
            )
            self.assertEqual(ok.returncode, 0, f"init failed: {ok.stderr}\n{ok.stdout}")

            config_path = repo / ".agent-learning.json"
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertIn("refresh_manifest", payload)

            # Drop refresh_manifest, then run self-test only.
            del payload["refresh_manifest"]
            config_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            fail = _run_init(
                "--repo", repo,
                "--state-dir", state_dir,
                "--self-test",
            )
            self.assertNotEqual(fail.returncode, 0)
            self.assertIn("refresh_manifest", fail.stderr)


if __name__ == "__main__":
    unittest.main()
