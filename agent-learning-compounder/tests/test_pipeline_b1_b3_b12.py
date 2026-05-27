"""End-to-end regression for PR 4 — B1 (boundary), B3 (events path), B12 (cursor).

Round-trips a single event through the full project-scope pipeline:

  event_writer.write_event(..., repo=R)
    → events.jsonl lands at <R>/.agent-learning/repos/<repo-id>/events.jsonl  (B3)
  index_events.run(repo_state)
    → upgrades the row past _enforce_boundary, populates events.sqlite       (B1)
  alc_query.get_actor_summary(StateHandle.for_repo(R))
    → returns the inserted event                                              (read-surface gate)

B12 is exercised via a separate path that writes a row known to quarantine,
verifies the cursor stays at 0, then writes a good row and confirms the
indexer picks it up on the next run.
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

import alc_query
import event_writer
import index_events
from state_handle import StateHandle


class PipelineRoundTripTests(unittest.TestCase):
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

    def test_event_writer_repo_arg_lands_in_repo_state_dir(self) -> None:
        state = self._state()
        event_id = event_writer.write_event(
            {
                "event": "pr4_round_trip",
                "schema_version": 4,
                "actor": {"kind": "operator", "name": "test"},
            },
            source="hook",
            repo=self.repo,
        )
        self.assertTrue(event_id.startswith("evt_"))
        self.assertTrue(state.events_jsonl.is_file(), state.events_jsonl)
        line = state.events_jsonl.read_text(encoding="utf-8").strip()
        self.assertIn(event_id, line)

    def test_b1_b3_round_trip_event_visible_via_alc_query(self) -> None:
        state = self._state()
        event_writer.write_event(
            {
                "event": "pr4_round_trip",
                "schema_version": 4,
                "actor": {"kind": "operator", "name": "alc_test_actor"},
            },
            source="hook",
            repo=self.repo,
        )
        added = index_events.run(state.repo_state_dir)
        self.assertEqual(added, 1)
        summary = alc_query.get_actor_summary(state, since="30d")
        self.assertEqual(summary["total"], 1)
        kinds = {row["actor_kind"] for row in summary["by_actor_kind"]}
        self.assertIn("operator", kinds)

    def test_b1_hashed_repo_field_passes_upgrade_from(self) -> None:
        # Simulates a v4-collected hook row whose `repo` field is the hashed
        # token (not /home/...). The boundary check used to reject this; the
        # fix moved the enforce to a copy of the row that drops `repo`.
        from event_schema import EventV4
        from state_paths import repo_id

        row = {
            "ts": "2026-05-27T12:00:00+00:00",
            "event": "session_start",
            "runtime": "claude",
            "schema_version": 4,
            "repo": repo_id(self.repo),
            "session_id": "test-session",
        }
        event = EventV4.upgrade_from(row)
        self.assertEqual(event.event, "session_start")

    def test_b1_legacy_v3_row_with_abs_repo_now_upgrades(self) -> None:
        # The 4309 rows already on disk pre-PR4 carry schema_version=3 and
        # repo="/home/...". Upgrading them must no longer raise.
        from event_schema import EventV4

        row = {
            "ts": "2026-05-20T08:00:00+00:00",
            "event": "session_start",
            "runtime": "claude",
            "schema_version": 3,
            "repo": "/home/tth/work/some/repo",
            "session_id": "legacy-session",
        }
        event = EventV4.upgrade_from(row)
        self.assertEqual(event.schema_version, 4)

    def test_b12_cursor_does_not_advance_on_all_quarantined_run(self) -> None:
        state = self._state()
        state.repo_state_dir.mkdir(parents=True, exist_ok=True)
        # Write a row that fails upgrade: actor.kind is invalid + an
        # absolute path lives in a mapped field. Both paths fail.
        bad_row = {
            "ts": "2026-05-20T08:00:00+00:00",
            "event": "bad",
            "schema_version": 3,
            "command_class": "/home/tth/secrets",
        }
        state.events_jsonl.write_text(
            json.dumps(bad_row) + "\n",
            encoding="utf-8",
        )
        added = index_events.run(state.repo_state_dir)
        self.assertEqual(added, 0)
        cursor_path = state.repo_state_dir / "events.sqlite.cursor"
        self.assertFalse(
            cursor_path.exists(),
            f"cursor advanced past quarantined run: {cursor_path.read_text() if cursor_path.exists() else ''}",
        )

        # Append a good row -- next run should pick BOTH lines back up, skip
        # the bad one again, and insert the good one.
        good_row = {
            "event_id": "evt_good_1",
            "ts": "2026-05-20T08:00:01+00:00",
            "event": "ok",
            "schema_version": 4,
            "actor": {"kind": "operator", "name": "ok"},
            "telemetry": {},
            "correlation_chain": [],
        }
        with state.events_jsonl.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(good_row) + "\n")
        added = index_events.run(state.repo_state_dir)
        self.assertEqual(added, 1)


if __name__ == "__main__":
    unittest.main()
