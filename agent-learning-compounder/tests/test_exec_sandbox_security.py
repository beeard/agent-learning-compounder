from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import textwrap
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

import state_handle


class ExecSandboxSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state_root = pathlib.Path(self.tmp.name) / "state"
        self.repo = pathlib.Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "-C", str(self.repo), "init"], check=True, text=True, stdout=subprocess.DEVNULL)
        (self.repo / "seed.txt").write_text("seed\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "seed.txt"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-m", "seed", "--no-gpg-sign"],
                       input="\n", text=True, check=True, stdout=subprocess.DEVNULL)

        self.env = os.environ.copy()
        self.env["AGENT_LEARNING_STATE_DIR"] = str(self.state_root)
        self.env["PYTHONPATH"] = str(BIN_DIR) + os.pathsep + self.env.get("PYTHONPATH", "")
        self.env["HTTP_PROXY"] = "http://bad.example"
        self.env["NO_PROXY"] = "bad"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @property
    def events_jsonl(self) -> pathlib.Path:
        return self.state_root / "events.jsonl"

    @property
    def _repo_state_dir(self) -> pathlib.Path:
        return self.state_root / "repos" / state_handle.StateHandle.repo_id(self.repo)

    def _run(self, *, scope: str, cmd: str) -> subprocess.CompletedProcess[str]:
        args = [
            sys.executable,
            str(BIN_DIR / "exec_sandbox"),
            "--scope",
            scope,
            "--cmd",
            cmd,
            "--repo",
            str(self.repo),
        ]
        return subprocess.run(args, check=False, env=self.env, text=True, capture_output=True)

    def _read_events(self) -> list[dict]:
        if not self.events_jsonl.exists():
            return []
        rows: list[dict] = []
        for line in self.events_jsonl.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def test_read_sanitizes_network_env_and_enables_no_network(self) -> None:
        test_module = self.repo / "network_env.py"
        test_module.write_text(
            textwrap.dedent(
                """
                import os
                import unittest

                class NetworkEnv(unittest.TestCase):
                    def test_flags(self):
                        self.assertIsNone(os.environ.get("HTTP_PROXY"))
                        self.assertIsNone(os.environ.get("NO_PROXY"))
                        self.assertEqual(os.environ.get("NO_NETWORK"), "1")
                """
            ),
            encoding="utf-8",
        )
        subprocess.run(["git", "-C", str(self.repo), "add", "network_env.py"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-m", "network env", "--no-gpg-sign"],
                       input="\n", text=True, check=True, stdout=subprocess.DEVNULL)

        proc = self._run(scope="read", cmd="python3 -m unittest network_env")
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_read_blocks_write_outside_repo_scope(self) -> None:
        proc = self._run(scope="read", cmd="touch /tmp/alc_exec_sandbox_forbidden")
        self.assertEqual(proc.returncode, 3)
        row = self._read_events()[-1]
        self.assertEqual(row["payload"]["scope"], "read")
        self.assertEqual(row["payload"]["exit_code"], 3)

    def test_read_path_traversal_is_blocked(self) -> None:
        proc = self._run(scope="read", cmd="cat ../../etc/passwd")
        self.assertEqual(proc.returncode, 3)
        row = self._read_events()[-1]
        self.assertEqual(row["payload"]["exit_code"], 3)

    def test_secret_is_scrubbed_in_event_payload_command(self) -> None:
        secret = "sk-ant-00000000000000000000"
        (self.repo / secret).write_text("secret\n", encoding="utf-8")
        proc = self._run(
            scope="read",
            cmd=f"cat {secret}",
        )
        self.assertEqual(proc.returncode, 0)
        row = self._read_events()[-1]
        self.assertNotIn(secret, row["payload"]["command"])
        self.assertIn("[REDACTED]", row["payload"]["command"])

    def test_stdout_payload_truncated_to_100kb(self) -> None:
        proc = self._run(
            scope="eval",
            cmd="python3 -c 'print(\"x\" * 120000, end=\"\")'",
        )
        self.assertEqual(proc.returncode, 0)
        row = self._read_events()[-1]
        self.assertEqual(row["event"], "exec_sandbox_run")
        self.assertIn("stdout_excerpt", row["payload"])
        self.assertLessEqual(len(row["payload"]["stdout_excerpt"].encode("utf-8")), 200)

        run_id = row["payload"]["run_id"]
        run_root = self._repo_state_dir / "sandbox-runs" / run_id
        stdout_path = run_root / "stdout"
        self.assertTrue(stdout_path.exists())
        size = stdout_path.stat().st_size
        self.assertGreater(size, 1024 * 100)
        self.assertGreater(row["payload"]["stdout_bytes"], len(row["payload"]["stdout_excerpt"].encode("utf-8")))


if __name__ == "__main__":
    unittest.main()
