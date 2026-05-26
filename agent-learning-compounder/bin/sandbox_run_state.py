#!/usr/bin/env python3
"""SQLite-backed run-state tracker for exec_sandbox.

`RunStateTracker` is a thin wrapper over the ``exec_sandbox_runs`` table.
It encapsulates the db-path initialisation, connection lifecycle, and all
mutation / query helpers so that ``exec_sandbox`` can delegate the entire
persistence concern to this class.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import sqlite3
import subprocess
import time
from typing import TYPE_CHECKING

from event_writer import write_event

try:
    from state_handle import StateHandle
except ImportError:
    from bin.state_handle import StateHandle


class RunStateTracker:
    """Tracks per-execution run state in SQLite for exec_sandbox.

    Parameters
    ----------
    state:
        The resolved `StateHandle` for the current repo.  The tracker uses
        ``state.events_sqlite`` as the db path and ``state.repo`` for
        worktree git operations.
    """

    def __init__(self, state: StateHandle) -> None:
        self._state = state
        self._conn = self._open_conn()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_status(
        self,
        exec_id: str,
        *,
        status: str,
        worktree_dir: pathlib.Path | None = None,
        pid: int | None = None,
    ) -> None:
        """Upsert the status row for *exec_id*."""
        wdir = str(worktree_dir) if worktree_dir is not None else ""
        ppid = pid if pid is not None else 0
        self._conn.execute(
            """
            INSERT INTO exec_sandbox_runs (exec_id, status, worktree_dir, pid, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(exec_id) DO UPDATE SET
                status = excluded.status,
                worktree_dir = excluded.worktree_dir,
                pid = excluded.pid,
                updated_at = excluded.updated_at
            """,
            (exec_id, status, wdir, ppid, int(time.time())),
        )
        self._conn.commit()

    def read_status(self, exec_id: str) -> dict[str, str | None]:
        """Return status, worktree_dir, and pid for *exec_id*, or Nones."""
        row = self._conn.execute(
            """
            SELECT status, worktree_dir, pid
            FROM exec_sandbox_runs
            WHERE exec_id = ?
            """,
            (exec_id,),
        ).fetchone()
        if row is None:
            return {"status": None, "worktree_dir": None, "pid": None}
        return {
            "status": str(row[0]),
            "worktree_dir": str(row[1]),
            "pid": str(row[2]) if row[2] is not None else None,
        }

    def delete_status(self, exec_id: str) -> None:
        """Remove the row for *exec_id* if present."""
        self._conn.execute(
            "DELETE FROM exec_sandbox_runs WHERE exec_id = ?", (exec_id,)
        )
        self._conn.commit()

    def recover_stale(self, actor: dict[str, str] | None = None) -> None:
        """Clean up worktree directories whose owning process is no longer alive.

        Iterates over all subdirectories of the ``sandbox-worktrees`` dir,
        checks each against the run-state table, and removes those that are
        either not recorded as *running* or whose recorded PID is dead.
        A ``exec_sandbox_recovered`` event is emitted for each cleaned entry.
        """
        sandbox_root = self._state.repo_state_dir / "sandbox-worktrees"
        if not sandbox_root.is_dir():
            return

        for candidate in sandbox_root.iterdir():
            if not candidate.is_dir():
                continue
            exec_id = candidate.name
            status = self.read_status(exec_id)
            stale = False
            if status["status"] != "running":
                stale = True
            else:
                raw_pid = status["pid"]
                pid = int(raw_pid) if raw_pid and raw_pid.isdigit() else None
                if pid is None or not _pid_alive(pid):
                    stale = True
            if not stale:
                continue
            _cleanup_worktree(self._state.repo, candidate)
            self.delete_status(exec_id)
            _emit_recovered_event(exec_id=exec_id, worktree_dir=candidate, actor=actor)

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()

    def ensure_worktree_dir(self, run_id: str) -> pathlib.Path:
        """Return (and guarantee existence of the parent of) the worktree path."""
        base = self._state.repo_state_dir / "sandbox-worktrees" / run_id
        base.parent.mkdir(parents=True, exist_ok=True)
        return base

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _open_conn(self) -> sqlite3.Connection:
        self._state.events_sqlite.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._state.events_sqlite)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS exec_sandbox_runs (
                exec_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                worktree_dir TEXT NOT NULL,
                pid INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        return conn


# ------------------------------------------------------------------
# Module-level helpers (no state, usable standalone)
# ------------------------------------------------------------------


def _pid_alive(pid: int) -> bool:
    """Return True if *pid* is a running process."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _cleanup_worktree(repo: pathlib.Path, worktree: pathlib.Path) -> None:
    """Remove a git worktree directory and deregister it from git."""
    try:
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "remove", "--force", str(worktree)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    finally:
        shutil.rmtree(worktree, ignore_errors=True)


def _emit_recovered_event(
    *,
    exec_id: str,
    worktree_dir: pathlib.Path,
    actor: dict[str, str] | None = None,
) -> None:
    """Emit an ``exec_sandbox_recovered`` event for a cleaned-up worktree."""
    payload = {
        "exec_id": exec_id,
        "worktree_dir": str(worktree_dir),
        "reason": "recovered",
    }
    write_event(
        {
            "event": "exec_sandbox_recovered",
            "actor": actor or {"kind": "eval_judge", "name": "recovery"},
            "payload": payload,
            "correlation_chain": [],
        },
        source="eval",
        auto_id_fallback=True,
    )
