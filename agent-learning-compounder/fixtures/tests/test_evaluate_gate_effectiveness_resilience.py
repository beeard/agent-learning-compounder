"""Tests for C4, C5, C7 in bin/evaluate_gate_effectiveness.load_sessions.

C7 pre-fix: load_sessions did `row = json.loads(line)` with no try/except,
so a single torn JSONL line (easily produced by the pre-H4 LOCK_SH +
PIPE_BUF interaction in collect_hook_event) propagated as
JSONDecodeError. main() only caught ValueError, so the entire refresh
aborted -- a single bad line stopped the whole scoring pipeline.

C5 pre-fix: load_sessions had no schema_version check. v1 events that
carried a correlation_id but lacked gate_loaded_ids landed in the
absent cohort for every gate, silently inflating n_absent and biasing
delta toward correlated_with_failure during a v1->v2 migration window.

C4 pre-fix: load_sessions read only the live hook-events.jsonl. After
collect_hook_event.rotate_if_needed renamed the live file to a
timestamped .bak, the cohort window shrank to whatever fit in
DEFAULT_MAX_HOOK_EVENT_BYTES (5 MB). A gate with N=200 yesterday could
revert to needs_review overnight after a rotation, with no warning.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "bin"))
from evaluate_gate_effectiveness import load_sessions  # noqa: E402


def _v2(event: str, cid: str, **fields) -> str:
    row = {"schema_version": 2, "event": event, "correlation_id": cid}
    row.update(fields)
    return json.dumps(row, sort_keys=True)


class LoadSessionsSkipsMalformedLines(unittest.TestCase):
    def test_torn_jsonl_line_is_skipped_not_raised(self):
        with tempfile.TemporaryDirectory() as td:
            events = Path(td) / "hook-events.jsonl"
            lines = [
                _v2("instructions_loaded", "sess-1", gate_loaded_ids=["aaaaaaaaaaaa"]),
                # Torn line: open brace, missing close. JSON decoder would raise.
                '{"schema_version": 2, "event": "instructions_loaded", "correlat',
                _v2("session_end", "sess-1", outcome="ok"),
            ]
            events.write_text("\n".join(lines) + "\n")
            # Pre-C7 this raised JSONDecodeError. Post-C7 it returns the
            # one valid session and silently skips the torn line.
            sessions = load_sessions(events)
            self.assertIn("sess-1", sessions)
            self.assertEqual(sessions["sess-1"]["outcome"], "ok")
            self.assertEqual(sessions["sess-1"]["gates"], {"aaaaaaaaaaaa"})


class LoadSessionsIgnoresV1Schema(unittest.TestCase):
    def test_v1_event_with_correlation_id_does_not_inflate_absent_cohort(self):
        with tempfile.TemporaryDirectory() as td:
            events = Path(td) / "hook-events.jsonl"
            lines = [
                # v1 row: no schema_version, has correlation_id, no
                # gate_loaded_ids. Pre-C5 this landed in the absent cohort.
                json.dumps({"event": "session_end", "correlation_id": "v1-sess", "outcome": "correction"}),
                # v2 rows: real cohort contributors.
                _v2("instructions_loaded", "v2-sess", gate_loaded_ids=["aaaaaaaaaaaa"]),
                _v2("session_end", "v2-sess", outcome="ok"),
            ]
            events.write_text("\n".join(lines) + "\n")
            sessions = load_sessions(events)
            # v1 session must be filtered out entirely.
            self.assertNotIn("v1-sess", sessions)
            # v2 session is the only one that exists.
            self.assertIn("v2-sess", sessions)

    def test_explicit_schema_version_1_is_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            events = Path(td) / "hook-events.jsonl"
            row_v1 = json.dumps({
                "schema_version": 1,
                "event": "session_end",
                "correlation_id": "old-sess",
                "outcome": "ok",
            })
            events.write_text(row_v1 + "\n")
            sessions = load_sessions(events)
            self.assertNotIn("old-sess", sessions)


class LoadSessionsMergesRotatedBackups(unittest.TestCase):
    def test_session_split_across_rotation_pairs_via_correlation_id(self):
        with tempfile.TemporaryDirectory() as td:
            events_dir = Path(td)
            live = events_dir / "hook-events.jsonl"
            backup = events_dir / "hook-events.jsonl.20260101T120000Z.bak"

            # instructions_loaded landed before rotation; session_end
            # landed after, on the rotated-out file.
            backup.write_text(
                _v2("instructions_loaded", "sess-rotated", gate_loaded_ids=["gate-A"]) + "\n"
            )
            live.write_text(
                _v2("session_end", "sess-rotated", outcome="ok") + "\n"
            )

            sessions = load_sessions(live)
            self.assertIn(
                "sess-rotated", sessions,
                msg=(
                    "session split across rotation must still pair via "
                    "correlation_id. Pre-C4 the rotated .bak was ignored "
                    "and this session had no outcome attached."
                ),
            )
            self.assertEqual(sessions["sess-rotated"]["outcome"], "ok")
            self.assertEqual(sessions["sess-rotated"]["gates"], {"gate-A"})

    def test_include_rotated_false_reads_only_live(self):
        """Backward-compat path: callers can disable the glob if they only
        want the live file."""
        with tempfile.TemporaryDirectory() as td:
            events_dir = Path(td)
            live = events_dir / "hook-events.jsonl"
            backup = events_dir / "hook-events.jsonl.20260101T120000Z.bak"
            backup.write_text(
                _v2("instructions_loaded", "sess-backup-only", gate_loaded_ids=["gate-B"]) + "\n"
            )
            live.write_text("")  # live is empty
            sessions = load_sessions(live, include_rotated=False)
            self.assertNotIn("sess-backup-only", sessions)

    def test_multiple_backups_all_get_merged(self):
        with tempfile.TemporaryDirectory() as td:
            events_dir = Path(td)
            live = events_dir / "hook-events.jsonl"
            for i, cid in enumerate(["sess-a", "sess-b", "sess-c"]):
                stamp = f"2026010{i+1}T120000Z"
                (events_dir / f"hook-events.jsonl.{stamp}.bak").write_text(
                    _v2("instructions_loaded", cid, gate_loaded_ids=[f"gate-{cid}"]) + "\n"
                    + _v2("session_end", cid, outcome="ok") + "\n"
                )
            # live has one fresh session of its own
            live.write_text(
                _v2("instructions_loaded", "sess-live", gate_loaded_ids=["gate-live"]) + "\n"
                + _v2("session_end", "sess-live", outcome="ok") + "\n"
            )
            sessions = load_sessions(live)
            self.assertEqual(
                set(sessions.keys()),
                {"sess-a", "sess-b", "sess-c", "sess-live"},
            )


if __name__ == "__main__":
    unittest.main()
