"""End-to-end regression for PR 5 — install-time warm loop.

Proves that ``alc_bootstrap_pipeline`` (the seam install.sh and the Stop
hook both call) closes the gap between ``hook-events.jsonl`` (collector
output) and ``events.sqlite`` (alc_query/dashboard/MCP read surface) in
both the legacy and fresh row shapes.

Pre-PR4 the indexer quarantined hashed-repo rows; pre-PR5 the bootstrap
required a manual ``replay_hook_events → index_events`` chain. This test
is the gate that would have caught either gap on a fresh install.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

import alc_bootstrap_pipeline
import alc_query
import collect_hook_event
from state_handle import StateHandle


class WarmLoopBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self._tmp.name) / "repo"
        self.repo.mkdir()
        # Clear env so StateHandle.for_repo lands at <repo>/.agent-learning.
        self._saved_env = {
            k: os.environ.pop(k, None)
            for k in (
                "AGENT_LEARNING_STATE_DIR",
                "AGENT_LEARNING_USER",
                "AGENT_LEARNING_PERSONAL",
            )
        }

    def tearDown(self) -> None:
        for key, value in self._saved_env.items():
            if value is not None:
                os.environ[key] = value
        self._tmp.cleanup()

    def _state(self) -> StateHandle:
        return StateHandle.for_repo(self.repo)

    def test_orchestrator_no_op_on_empty_state(self) -> None:
        # Fresh install: no hook-events.jsonl, no events.jsonl.
        # Orchestrator must exit 0 and produce no events.sqlite rows.
        rc = alc_bootstrap_pipeline.run(self.repo, quiet=True)
        self.assertEqual(rc, 0)
        state = self._state()
        # repo_state_dir is created by the orchestrator even on empty state.
        self.assertTrue(state.repo_state_dir.is_dir())

    def test_dual_path_legacy_and_fresh_row_both_indexed(self) -> None:
        # This is the regression that would have caught PR 4's P1 (schema
        # mismatch quarantining live collector rows) at install time, and
        # PR 5's own gap (manual replay step never wired into bootstrap or
        # Stop). Both row shapes flow into hook-events.jsonl — the
        # orchestrator's input. The replay step normalizes both into
        # events.jsonl; the indexer then upgrades them through
        # EventV4.upgrade_from into events.sqlite.
        state = self._state()
        state.repo_state_dir.mkdir(parents=True, exist_ok=True)

        # Shape A: legacy hook row carrying `repo` as an absolute /home/...
        # path (the pre-PR4 collector shape that previously quarantined at
        # the upgrade boundary). Replay's `normalize_event` re-hashes this
        # into the canonical repo_id token; the indexer's upgrade-from then
        # drops the field before boundary check.
        legacy_row = {
            "ts": "2026-05-20T08:00:00+00:00",
            "event": "legacy_event_pr5",
            "runtime": "claude",
            "schema_version": 3,
            "repo": "/home/tth/work/active/some-old-repo",
            "session_id": "legacy-session",
        }

        # Shape B: fresh collector row from the live normalize_event path
        # (the shape PR 4's P1 regression confirmed makes it through).
        fresh_row = collect_hook_event.normalize_event(
            {"event": "PreToolUse", "tool": "Bash", "session_id": "fresh-session"},
            self.repo,
        )
        self.assertEqual(fresh_row["schema_version"], 3)
        self.assertNotIn("/", fresh_row["repo"], "collector must hash repo")

        hook_events_path = state.repo_state_dir / "hook-events.jsonl"
        hook_events_path.write_text(
            json.dumps(legacy_row) + "\n" + json.dumps(fresh_row) + "\n",
            encoding="utf-8",
        )

        # One orchestrator call mimics the install.sh and Stop-hook surface.
        rc = alc_bootstrap_pipeline.run(self.repo, quiet=True)
        self.assertEqual(rc, 0)

        # Both rows visible via the canonical read API.
        summary = alc_query.get_actor_summary(self._state(), since="30d")
        self.assertGreaterEqual(
            summary["total"], 2,
            f"expected both legacy and fresh rows indexed, summary={summary}",
        )

    def test_idempotent_rerun_does_not_duplicate(self) -> None:
        # Stop hook fires once per session. If two sessions Stop without
        # any new hook events in between, the second run must be a no-op
        # for the indexer — replay regenerates identical bytes, cursor
        # already at EOF, no new rows inserted.
        state = self._state()
        state.repo_state_dir.mkdir(parents=True, exist_ok=True)
        fresh_row = collect_hook_event.normalize_event(
            {"event": "PreToolUse", "tool": "Bash", "session_id": "sess-idem"},
            self.repo,
        )
        hook_events_path = state.repo_state_dir / "hook-events.jsonl"
        hook_events_path.write_text(json.dumps(fresh_row) + "\n", encoding="utf-8")

        self.assertEqual(alc_bootstrap_pipeline.run(self.repo, quiet=True), 0)
        first = alc_query.get_actor_summary(self._state(), since="30d")["total"]
        self.assertEqual(alc_bootstrap_pipeline.run(self.repo, quiet=True), 0)
        second = alc_query.get_actor_summary(self._state(), since="30d")["total"]
        self.assertEqual(first, second, "second run must not duplicate rows")

    def test_skip_replay_indexes_existing_events_jsonl_only(self) -> None:
        # --skip-replay is the operator escape hatch (e.g. for the
        # incremental-cursor follow-up). Confirms the indexer still runs
        # against whatever events.jsonl already holds, ignoring
        # hook-events.jsonl entirely.
        state = self._state()
        state.repo_state_dir.mkdir(parents=True, exist_ok=True)
        legacy_row = {
            "ts": "2026-05-20T08:00:00+00:00",
            "event": "skip_replay_check",
            "runtime": "claude",
            "schema_version": 3,
            "session_id": "skip-replay-session",
        }
        state.events_jsonl.write_text(json.dumps(legacy_row) + "\n", encoding="utf-8")
        # Hook events that should NOT reach events.sqlite when --skip-replay.
        # Use a unique session marker so we can verify absence.
        hook_only_row = collect_hook_event.normalize_event(
            {"event": "PreToolUse", "tool": "Bash", "session_id": "hooks-only-sess"},
            self.repo,
        )
        (state.repo_state_dir / "hook-events.jsonl").write_text(
            json.dumps(hook_only_row) + "\n", encoding="utf-8",
        )

        self.assertEqual(
            alc_bootstrap_pipeline.run(self.repo, skip_replay=True, quiet=True),
            0,
        )
        # events.jsonl should be untouched (replay skipped → no overwrite).
        self.assertEqual(
            state.events_jsonl.read_text(encoding="utf-8").strip(),
            json.dumps(legacy_row),
        )
        # The indexer must still have run against the existing events.jsonl:
        # one row in sqlite, and it's the legacy row — never the hook-only one.
        # Asserting events-jsonl unchanged on its own would also pass if
        # skip_replay accidentally short-circuited the indexer too.
        summary = self._state()
        import sqlite3
        with sqlite3.connect(summary.events_sqlite) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT session_id, event FROM events ORDER BY ts"
            ).fetchall()
        self.assertEqual(len(rows), 1, f"indexer didn't run under skip_replay: {rows}")
        self.assertEqual(rows[0]["session_id"], "skip-replay-session")
        self.assertEqual(rows[0]["event"], "skip_replay_check")
        sessions = {r["session_id"] for r in rows}
        self.assertNotIn(
            "hooks-only-sess", sessions,
            "hook-events.jsonl row leaked into sqlite under skip_replay",
        )


if __name__ == "__main__":
    unittest.main()
