from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

import state_handle


def _write_file(path: pathlib.Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class ExecSandboxEvalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state_root = pathlib.Path(self.tmp.name) / "state"
        self.repo = pathlib.Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        self.env = os.environ.copy()
        self.env["AGENT_LEARNING_STATE_DIR"] = str(self.state_root)
        self.env["PYTHONPATH"] = str(BIN_DIR) + os.pathsep + self.env.get("PYTHONPATH", "")

        subprocess.run(["git", "-C", str(self.repo), "init"], check=True, text=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "alc-test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "ALC Test"], check=True)
        _write_file(self.repo / "seed.txt", "seed\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "seed.txt"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-m", "seed", "--no-gpg-sign"],
                       input="\n", text=True, check=True, stdout=subprocess.DEVNULL)

        self.probe_path = self.repo / "exec-sandbox-eval-probe.json"
        self.stub_bin = pathlib.Path(self.tmp.name) / "mock-bin"
        self.stub_bin.mkdir()
        self.alc_invoke = self.stub_bin / "alc_invoke"
        _write_file(
            self.alc_invoke,
            "\n".join(
                [
                    "#!/usr/bin/env python3",
                    "import json",
                    "import pathlib",
                    "import sys",
                    "",
                    f'pathlib.Path(r"{self.probe_path.as_posix()}").write_text(json.dumps({{"argv": sys.argv[1:]}}), encoding="utf-8")',
                ]
            ),
        )
        self.alc_invoke.chmod(0o755)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self, *, cmd: str, depth: int = 0, parent_event_id: str | None = None) -> subprocess.CompletedProcess[str]:
        args = [
            sys.executable,
            str(BIN_DIR / "exec_sandbox"),
            "--scope",
            "eval",
            "--base-ref",
            "HEAD",
            "--cmd",
            cmd,
            "--repo",
            str(self.repo),
            "--depth",
            str(depth),
        ]
        if parent_event_id:
            args.extend(["--parent-event-id", parent_event_id])
        return subprocess.run(args, check=False, env=self.env, text=True, capture_output=True)

    def _read_events(self) -> list[dict]:
        # PR4/B3: writes land in <state_root>/repos/<repo-id>/events.jsonl.
        events_path = (
            self.state_root
            / "repos"
            / state_handle.StateHandle.repo_id(self.repo)
            / "events.jsonl"
        )
        if not events_path.exists():
            return []
        rows: list[dict] = []
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def test_eval_scope_runs_with_mocked_alc_invoke(self) -> None:
        cmd = f"{self.alc_invoke} --agent evals/rec-quality-judge --task sample.patch"
        proc = self._run(cmd=cmd)
        self.assertEqual(proc.returncode, 0, proc.stderr)

        rows = self._read_events()
        self.assertTrue(rows)
        row = rows[-1]
        self.assertEqual(row["event"], "exec_sandbox_run")
        self.assertEqual(row["payload"]["scope"], "eval")

        payload = json.loads(self.probe_path.read_text(encoding="utf-8"))
        self.assertIn("--agent", payload["argv"])

        worktree_dir = pathlib.Path(row["payload"]["worktree_dir"])
        self.assertFalse(worktree_dir.exists(), row["payload"]["worktree_dir"])

    def test_eval_supports_parent_event_chain(self) -> None:
        cmd = f"{self.alc_invoke} --agent evals/rec-quality-judge --task sample.patch"
        proc = self._run(cmd=cmd, parent_event_id="evt_parent_1")
        self.assertEqual(proc.returncode, 0)

        row = self._read_events()[-1]
        self.assertEqual(row["correlation_chain"], [{"role": "triggered_by", "id": "evt_parent_1"}])

    def test_eval_disallows_recursive_depth_guard(self) -> None:
        cmd = f"{self.alc_invoke} --agent evals/rec-quality-judge --task sample.patch"
        proc = self._run(cmd=cmd, depth=2)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("max sandbox depth", proc.stderr)


if __name__ == "__main__":
    unittest.main()
