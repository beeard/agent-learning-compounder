from __future__ import annotations

import json
import os
import pathlib
import shlex
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

import state_handle


class ExecSandboxReadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state_root = pathlib.Path(self.tmp.name) / "state"
        self.repo = pathlib.Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "-C", str(self.repo), "init"], check=True, text=True, stdout=subprocess.DEVNULL)
        (self.repo / "README.md").write_text("hello\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-m", "seed", "--no-gpg-sign"],
                       input="\n", text=True, check=True, stdout=subprocess.DEVNULL)

        self.env = os.environ.copy()
        self.env["AGENT_LEARNING_STATE_DIR"] = str(self.state_root)
        self.env["PYTHONPATH"] = str(BIN_DIR) + os.pathsep + self.env.get("PYTHONPATH", "")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @property
    def events_jsonl(self) -> pathlib.Path:
        return pathlib.Path(self.state_root) / "events.jsonl"

    def _run(self, command: str, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
        args = [
            sys.executable,
            str(BIN_DIR / "exec_sandbox"),
            "--scope",
            "read",
            "--cmd",
            command,
            "--repo",
            str(self.repo),
        ]
        if timeout is not None:
            args.extend(["--timeout", str(timeout)])
        return subprocess.run(
            args,
            check=False,
            env=self.env,
            text=True,
            capture_output=True,
        )

    def _read_events(self) -> list[dict]:
        if not self.events_jsonl.exists():
            return []
        rows: list[dict] = []
        for line in self.events_jsonl.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
        return rows

    def test_allowlisted_read_command_executes_and_emits_event(self) -> None:
        proc = self._run("ls -la")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        events = self._read_events()
        self.assertTrue(events)
        row = events[-1]
        self.assertEqual(row["event"], "exec_sandbox_run")
        self.assertEqual(row["payload"]["scope"], "read")
        self.assertEqual(row["payload"]["exit_code"], 0)

    def test_forbidden_read_command_returns_3_and_is_blocked(self) -> None:
        proc = self._run("rm -rf .")
        self.assertEqual(proc.returncode, 3)
        events = self._read_events()
        self.assertEqual(events[-1]["payload"]["exit_code"], 3)

    def test_timeout_exit_code_124(self) -> None:
        test_module = self.repo / "slow.py"
        test_module.write_text(
            textwrap.dedent(
                """
                import time
                import unittest

                class Slow(unittest.TestCase):
                    def test_sleep(self):
                        time.sleep(2)
                """
            ),
            encoding="utf-8",
        )
        (self.repo / "__init__.py").write_text("", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "slow.py", "__init__.py"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-m", "slow", "--no-gpg-sign"],
                       input="\n", text=True, check=True, stdout=subprocess.DEVNULL)

        proc = self._run("python3 -m unittest slow", timeout=1)
        self.assertEqual(proc.returncode, 124)
        events = self._read_events()
        row = events[-1]
        self.assertTrue(row["payload"]["timeout"])

    def test_network_flag_is_present_for_allowed_python_command(self) -> None:
        test_module = self.repo / "no_network.py"
        test_module.write_text(
            textwrap.dedent(
                """
                import os
                import unittest

                class NoNetwork(unittest.TestCase):
                    def test_has_flag(self):
                        assert os.environ.get("NO_NETWORK") == "1"
                """
            ),
            encoding="utf-8",
        )
        subprocess.run(["git", "-C", str(self.repo), "add", "no_network.py"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-m", "no-network", "--no-gpg-sign"],
                       input="\n", text=True, check=True, stdout=subprocess.DEVNULL)

        proc = self._run("python3 -m unittest no_network")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # Command text is scrubbed in emitted payload and must be present.
        events = self._read_events()
        row = events[-1]
        self.assertIn("python3 -m unittest", row["payload"]["command"])


if __name__ == "__main__":
    unittest.main()
