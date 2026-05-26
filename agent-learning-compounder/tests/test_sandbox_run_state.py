"""Unit tests for sandbox_run_state.RunStateTracker."""

from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

import state_handle as state_handle_mod
from sandbox_run_state import RunStateTracker, _pid_alive


def _make_handle(tmp: pathlib.Path) -> state_handle_mod.StateHandle:
    """Build a minimal StateHandle backed by *tmp*."""
    repo = tmp / "repo"
    repo.mkdir(exist_ok=True)
    state_root = tmp / "state"
    repo_state = state_root / "repos" / "test-repo-abc123"
    return state_handle_mod.StateHandle(
        repo=repo,
        state_root=state_root,
        repo_state_dir=repo_state,
        reports_dir=repo_state / "reports",
        dashboard_dir=repo_state / "dashboard",
        alc_agents_dirs={
            "dev": repo_state / "alc-agents" / "dev",
            "test": repo_state / "alc-agents" / "test",
            "evals": repo_state / "alc-agents" / "evals",
            "personal": state_root / "alc-agents" / "personal",
        },
        alc_apply_log=repo_state / "apply-log.jsonl",
        outcomes_json=repo_state / "outcomes.json",
        events_jsonl=repo_state / "events.jsonl",
        events_sqlite=repo_state / "events.sqlite",
    )


class TestRunStateTrackerRoundTrip(unittest.TestCase):
    """set_status / read_status round-trip."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._td.name)
        self.handle = _make_handle(self.tmp)
        self.tracker = RunStateTracker(self.handle)

    def tearDown(self) -> None:
        self.tracker.close()
        self._td.cleanup()

    def test_set_and_read_status(self) -> None:
        wdir = self.tmp / "wt" / "abc"
        self.tracker.set_status("exec-1", status="running", worktree_dir=wdir, pid=12345)
        result = self.tracker.read_status("exec-1")
        self.assertEqual(result["status"], "running")
        self.assertEqual(result["worktree_dir"], str(wdir))
        self.assertEqual(result["pid"], "12345")

    def test_read_missing_returns_nones(self) -> None:
        result = self.tracker.read_status("does-not-exist")
        self.assertIsNone(result["status"])
        self.assertIsNone(result["worktree_dir"])
        self.assertIsNone(result["pid"])

    def test_upsert_overwrites_previous_row(self) -> None:
        wdir = self.tmp / "wt" / "abc"
        self.tracker.set_status("exec-2", status="running", worktree_dir=wdir, pid=1)
        self.tracker.set_status("exec-2", status="finished", worktree_dir=wdir, pid=0)
        result = self.tracker.read_status("exec-2")
        self.assertEqual(result["status"], "finished")
        self.assertEqual(result["pid"], "0")

    def test_set_status_without_optional_fields(self) -> None:
        # worktree_dir and pid can be omitted (default to empty string / 0)
        self.tracker.set_status("exec-3", status="initialising")
        result = self.tracker.read_status("exec-3")
        self.assertEqual(result["status"], "initialising")


class TestRunStateTrackerDelete(unittest.TestCase):
    """delete_status removes the row."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._td.name)
        self.handle = _make_handle(self.tmp)
        self.tracker = RunStateTracker(self.handle)

    def tearDown(self) -> None:
        self.tracker.close()
        self._td.cleanup()

    def test_delete_removes_row(self) -> None:
        wdir = self.tmp / "wt" / "del"
        self.tracker.set_status("exec-del", status="running", worktree_dir=wdir, pid=999)
        self.tracker.delete_status("exec-del")
        result = self.tracker.read_status("exec-del")
        self.assertIsNone(result["status"])

    def test_delete_nonexistent_is_noop(self) -> None:
        # Should not raise
        self.tracker.delete_status("never-existed")


class TestRunStateTrackerMissingDb(unittest.TestCase):
    """Constructor creates the table when the db file doesn't exist yet."""

    def test_creates_table_on_init(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            handle = _make_handle(pathlib.Path(td))
            self.assertFalse(handle.events_sqlite.exists())
            tracker = RunStateTracker(handle)
            try:
                # Basic operation works immediately — table was created
                tracker.set_status("probe", status="running")
                self.assertEqual(tracker.read_status("probe")["status"], "running")
            finally:
                tracker.close()
            self.assertTrue(handle.events_sqlite.exists())


class TestRunStateTrackerRecoverStale(unittest.TestCase):
    """recover_stale cleans up dead-pid worktrees and leaves live ones alone."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._td.name)
        self.handle = _make_handle(self.tmp)
        self.tracker = RunStateTracker(self.handle)

        # Set up the sandbox-worktrees directory structure
        self.wt_root = self.handle.repo_state_dir / "sandbox-worktrees"
        self.wt_root.mkdir(parents=True, exist_ok=True)

        # Patch write_event so we can capture recovery events without a real state dir
        import sandbox_run_state
        self._events: list[dict] = []
        self._orig_write_event = sandbox_run_state.write_event

        def _fake_write_event(payload: dict, **kwargs: object) -> str:
            self._events.append(payload)
            return "fake-event-id"

        sandbox_run_state.write_event = _fake_write_event

    def tearDown(self) -> None:
        import sandbox_run_state
        sandbox_run_state.write_event = self._orig_write_event
        self.tracker.close()
        self._td.cleanup()

    def _make_stale_dir(self, name: str, *, status: str = "running", pid: int = 0) -> pathlib.Path:
        """Create a worktree dir and register it in the tracker."""
        wdir = self.wt_root / name
        wdir.mkdir()
        self.tracker.set_status(name, status=status, worktree_dir=wdir, pid=pid)
        return wdir

    def test_recover_stale_pid_dead(self) -> None:
        # Use PID 1 which is always alive, but override with a bogus dead PID.
        # Find a PID that definitely isn't alive.
        dead_pid = 9_999_999  # Extremely unlikely to exist
        wdir = self._make_stale_dir("stale-dead", status="running", pid=dead_pid)
        self.assertTrue(wdir.exists())

        self.tracker.recover_stale()

        self.assertFalse(wdir.exists(), "stale worktree should have been removed")
        self.assertIsNone(self.tracker.read_status("stale-dead")["status"])
        recovered = [e for e in self._events if e.get("event") == "exec_sandbox_recovered"]
        self.assertEqual(len(recovered), 1)
        self.assertIn("stale-dead", recovered[0]["payload"]["exec_id"])

    def test_recover_stale_status_not_running(self) -> None:
        wdir = self._make_stale_dir("stale-finished", status="finished", pid=0)
        self.assertTrue(wdir.exists())

        self.tracker.recover_stale()

        self.assertFalse(wdir.exists())
        recovered = [e for e in self._events if e.get("event") == "exec_sandbox_recovered"]
        self.assertEqual(len(recovered), 1)

    def test_recover_stale_leaves_live_pid_alone(self) -> None:
        live_pid = os.getpid()
        wdir = self._make_stale_dir("live-run", status="running", pid=live_pid)
        self.assertTrue(wdir.exists())

        self.tracker.recover_stale()

        # Directory should still exist — PID is alive
        self.assertTrue(wdir.exists(), "live worktree must not be removed")
        recovered = [e for e in self._events if e.get("event") == "exec_sandbox_recovered"]
        self.assertEqual(len(recovered), 0)

    def test_recover_stale_no_dir_is_noop(self) -> None:
        # If sandbox-worktrees doesn't exist, recover_stale returns immediately.
        import shutil
        shutil.rmtree(self.wt_root)
        # Should not raise
        self.tracker.recover_stale()

    def test_recover_stale_emits_actor_in_event(self) -> None:
        dead_pid = 9_999_999
        self._make_stale_dir("stale-actor", status="running", pid=dead_pid)

        actor = {"kind": "operator", "name": "test-runner"}
        self.tracker.recover_stale(actor=actor)

        recovered = [e for e in self._events if e.get("event") == "exec_sandbox_recovered"]
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]["actor"], actor)


class TestPidAlive(unittest.TestCase):
    """Module-level _pid_alive helper."""

    def test_current_pid_is_alive(self) -> None:
        self.assertTrue(_pid_alive(os.getpid()))

    def test_bogus_pid_is_not_alive(self) -> None:
        self.assertFalse(_pid_alive(9_999_999))


if __name__ == "__main__":
    unittest.main()
