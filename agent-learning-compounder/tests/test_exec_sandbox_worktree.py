from __future__ import annotations

import concurrent.futures
import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

import state_handle


class ExecSandboxWorktreeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state_root = pathlib.Path(self.tmp.name) / "state"
        self.repo = pathlib.Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "-C", str(self.repo), "init"], check=True, text=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "alc-test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "ALC Test"], check=True)
        (self.repo / "seed.txt").write_text("seed\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "seed.txt"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-m", "seed", "--no-gpg-sign"],
                       input="\n", text=True, check=True, stdout=subprocess.DEVNULL)
        self.env = os.environ.copy()
        self.env["AGENT_LEARNING_STATE_DIR"] = str(self.state_root)
        self.env["PYTHONPATH"] = str(BIN_DIR) + os.pathsep + self.env.get("PYTHONPATH", "")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @property
    def events_jsonl(self) -> pathlib.Path:
        # PR4/B3: writes land in <state_root>/repos/<repo-id>/events.jsonl.
        return self._repo_state_dir / "events.jsonl"

    @property
    def events_sqlite(self) -> pathlib.Path:
        return state_handle.StateHandle.for_repo(self.repo).events_sqlite

    @property
    def _repo_state_dir(self) -> pathlib.Path:
        return self.state_root / "repos" / state_handle.StateHandle.repo_id(self.repo)

    def _run(self, command: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(BIN_DIR / "exec_sandbox"),
                "--scope",
                "worktree",
                "--base-ref",
                "HEAD",
                "--cmd",
                command,
                "--repo",
                str(self.repo),
            ],
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
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def _state_handle(self) -> state_handle.StateHandle:
        return state_handle.StateHandle(
            repo=self.repo.resolve(),
            state_root=self.state_root.resolve(),
            repo_state_dir=self._repo_state_dir,
            reports_dir=self._repo_state_dir / "reports",
            dashboard_dir=self._repo_state_dir / "dashboard",
            alc_agents_dirs={
                "dev": self._repo_state_dir / "alc-agents" / "dev",
                "test": self._repo_state_dir / "alc-agents" / "test",
                "evals": self._repo_state_dir / "alc-agents" / "evals",
                "personal": self.state_root / "alc-agents" / "personal",
            },
            alc_apply_log=self._repo_state_dir / "apply-log.jsonl",
            outcomes_json=self._repo_state_dir / "outcomes.json",
            events_jsonl=self._repo_state_dir / "events.jsonl",
            events_sqlite=self._repo_state_dir / "events.sqlite",
        )

    def test_worktree_command_writes_and_cleans(self) -> None:
        proc = self._run("touch x.tmp && ls x.tmp")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        info = json.loads(proc.stdout)
        events = self._read_events()
        row = events[-1]
        self.assertEqual(row["event"], "exec_sandbox_run")
        self.assertEqual(row["payload"]["scope"], "worktree")
        run_root = pathlib.Path(row["payload"]["worktree_dir"])
        self.assertEqual(run_root.parent, self._repo_state_dir / "sandbox-worktrees")
        self.assertEqual(run_root.name, row["payload"]["run_id"])
        self.assertEqual(row["payload"]["run_id"], info["worktree_dir"].rsplit("/", 1)[-1])
        self.assertFalse(run_root.exists(), proc.stderr)

        list_output = subprocess.run([
            "git",
            "-C",
            str(self.repo),
            "worktree",
            "list",
        ], capture_output=True, text=True, check=True)
        self.assertNotIn(str(run_root), list_output.stdout)

    def test_concurrent_worktree_runs_are_isolated(self) -> None:
        def worker(_: int) -> tuple[int, str | None]:
            proc = self._run("touch x.tmp && ls x.tmp")
            payload = json.loads(proc.stdout)
            return proc.returncode, payload.get("worktree_dir")

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, range(2)))

        exit_codes = [code for code, _ in results]
        roots = [root for _, root in results]
        self.assertEqual(exit_codes, [0, 0])
        self.assertEqual(len(set(roots)), 2)
        for root in roots:
            self.assertIsNotNone(root)
            self.assertFalse(pathlib.Path(root).exists())

    def test_timeout_command_still_cleans_worktree(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                str(BIN_DIR / "exec_sandbox"),
                "--scope",
                "worktree",
                "--base-ref",
                "HEAD",
                "--cmd",
                "python3 -c 'import time; time.sleep(4)'",
                "--timeout",
                "1",
                "--repo",
                str(self.repo),
            ],
            env=self.env,
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertEqual(proc.returncode, 124)
        row = self._read_events()[-1]
        self.assertTrue(row["payload"].get("timeout"))
        run_root = pathlib.Path(row["payload"]["worktree_dir"])
        self.assertFalse(run_root.exists())

    def test_worktree_scope_cleans_stale_recovery_run(self) -> None:
        handle = self._state_handle()
        stale_root = handle.repo_state_dir / "sandbox-worktrees" / "stale-recovery"
        stale_root.mkdir(parents=True)

        recover = subprocess.run(
            [
                sys.executable,
                str(BIN_DIR / "exec_sandbox"),
                "--scope",
                "read",
                "--cmd",
                "ls",
                "--repo",
                str(self.repo),
            ],
            env=self.env,
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertEqual(recover.returncode, 0)
        recovered_rows = [row for row in self._read_events() if row["event"] == "exec_sandbox_recovered"]
        self.assertEqual(len(recovered_rows), 1)
        recovered_payload = recovered_rows[-1]["payload"]
        self.assertIn(stale_root.name, pathlib.Path(recovered_payload["worktree_dir"]).name)
        self.assertFalse(stale_root.exists())


if __name__ == "__main__":
    unittest.main()
