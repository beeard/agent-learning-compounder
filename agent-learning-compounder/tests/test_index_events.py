from __future__ import annotations

import io
import json
import pathlib
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from typing import Any

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

import index_events


class IndexEventsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state = pathlib.Path(self.tmp.name)
        self.events_jsonl = self.state / "events.jsonl"
        self.sqlite = self.state / "events.sqlite"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self, args: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = index_events.main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def _write_events(self, rows: list[dict[str, Any]], *, append: bool = False) -> None:
        mode = "a" if append else "w"
        with open(self.events_jsonl, mode, encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")

    def _event_row(self, event_id: str, *, kind: str = "hook", session_id: str | None = None) -> dict[str, Any]:
        row: dict[str, Any] = {
            "event_id": event_id,
            "ts": "2026-05-26T12:00:00+00:00",
            "event": "session_started",
            "schema_version": 4,
            "actor": {
                "kind": kind,
                "name": "worker",
            },
            "telemetry": {},
            "correlation_chain": [],
        }
        if session_id:
            row["session_id"] = session_id
        return row

    def _count(self, query: str, args: tuple[Any, ...] = ()) -> int:
        with sqlite3.connect(self.sqlite) as conn:
            cursor = conn.execute(query, args)
            return int(cursor.fetchone()[0])

    def test_index_fresh_state_creates_schema(self) -> None:
        code, stdout, stderr = self._run(["--state", str(self.state)])
        self.assertEqual(code, 0, f"stdout={stdout}, stderr={stderr}")
        with sqlite3.connect(self.sqlite) as conn:
            tables = set(row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='events'"
            ))
            self.assertIn("events", tables)

            table_sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='events'"
            ).fetchone()[0]
            self.assertIn("CREATE TABLE", table_sql)
            self.assertIn("actor_kind TEXT NOT NULL", table_sql)

            indices = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='events'"
            )}
            self.assertIn("idx_events_actor_kind", indices)
            self.assertIn("idx_events_event", indices)

    def test_index_incremental_adds_new_rows(self) -> None:
        self._write_events([self._event_row(f"evt-{idx}", session_id="session-alpha") for idx in range(10)])
        code, _, _ = self._run(["--state", str(self.state)])
        self.assertEqual(code, 0)
        self.assertEqual(self._count("SELECT COUNT(*) FROM events"), 10)
        first_cursor = int((self.state / "events.sqlite.cursor").read_text(encoding="utf-8"))

        self._write_events([self._event_row(f"evt-new-{idx}", session_id="session-beta") for idx in range(3)], append=True)
        code, _, _ = self._run(["--state", str(self.state)])
        self.assertEqual(code, 0)
        self.assertEqual(self._count("SELECT COUNT(*) FROM events"), 13)
        second_cursor = int((self.state / "events.sqlite.cursor").read_text(encoding="utf-8"))
        self.assertGreater(second_cursor, first_cursor)

    def test_index_idempotent_no_new_events(self) -> None:
        self._write_events([self._event_row(f"evt-{idx}", session_id="session-idempotent") for idx in range(5)])
        code, _, _ = self._run(["--state", str(self.state)])
        self.assertEqual(code, 0)
        cursor = int((self.state / "events.sqlite.cursor").read_text(encoding="utf-8"))
        self.assertEqual(self._count("SELECT COUNT(*) FROM events"), 5)

        code, _, _ = self._run(["--state", str(self.state)])
        self.assertEqual(code, 0)
        self.assertEqual(self._count("SELECT COUNT(*) FROM events"), 5)
        self.assertEqual(int((self.state / "events.sqlite.cursor").read_text(encoding="utf-8")), cursor)

    def test_corrupt_row_is_quarantined_not_wedge(self) -> None:
        # Locks the wedge-fix: a malformed line in events.jsonl must not
        # block all future indexing. Prior behavior re-raised ValueError on
        # bad rows, rolled back the txn, and never advanced the cursor.
        good_a = self._event_row("good-a", session_id="session-q")
        good_b = self._event_row("good-b", session_id="session-q")
        with open(self.events_jsonl, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(good_a, sort_keys=True) + "\n")
            handle.write("not-valid-json{}{}{\n")
            handle.write(json.dumps(good_b, sort_keys=True) + "\n")

        code, _stdout, stderr = self._run(["--state", str(self.state)])
        self.assertEqual(code, 0)
        # Both valid rows indexed; the bad row skipped, never wedges the indexer.
        self.assertEqual(self._count("SELECT COUNT(*) FROM events"), 2)
        self.assertIn("warn.index_events_skipped", stderr)
        # Cursor must have advanced past the bad line so re-run is a true no-op.
        cursor_after_first = int((self.state / "events.sqlite.cursor").read_text(encoding="utf-8"))
        code2, _, _ = self._run(["--state", str(self.state)])
        self.assertEqual(code2, 0)
        self.assertEqual(self._count("SELECT COUNT(*) FROM events"), 2)
        self.assertEqual(int((self.state / "events.sqlite.cursor").read_text(encoding="utf-8")), cursor_after_first)

    def test_query_by_session_id(self) -> None:
        self._write_events(
            [
                self._event_row("a-1", session_id="session-abc"),
                self._event_row("a-2", session_id="session-abc"),
                self._event_row("b-1", session_id="session-xyz"),
            ]
        )
        code, _, _ = self._run(["--state", str(self.state)])
        self.assertEqual(code, 0)
        self.assertEqual(self._count("SELECT COUNT(*) FROM events WHERE session_id = ?", ("session-abc",)), 2)

    def test_query_by_actor_kind(self) -> None:
        self._write_events(
            [
                self._event_row("a", kind="subagent"),
                self._event_row("b", kind="hook"),
                self._event_row("c", kind="subagent"),
            ]
        )
        code, _, _ = self._run(["--state", str(self.state)])
        self.assertEqual(code, 0)
        rows = list(sqlite3.connect(self.sqlite).execute("SELECT event_id FROM events WHERE actor_kind='subagent'"))
        self.assertEqual({row[0] for row in rows}, {"a", "c"})

    def test_schema_version_mismatch_refuses(self) -> None:
        with sqlite3.connect(self.sqlite) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT NOT NULL,
                    ts TEXT NOT NULL,
                    event TEXT NOT NULL,
                    schema_version INTEGER NOT NULL DEFAULT 4,
                    actor_kind TEXT NOT NULL,
                    actor_name TEXT NOT NULL,
                    actor_model TEXT,
                    actor_parent_actor_id TEXT,
                    telemetry_duration_ms INTEGER,
                    telemetry_tokens_in INTEGER,
                    telemetry_tokens_out INTEGER,
                    telemetry_cache_read_tokens INTEGER,
                    telemetry_cache_creation_tokens INTEGER,
                    telemetry_cost_usd REAL,
                    telemetry_interrupted INTEGER,
                    correlation_chain TEXT NOT NULL,
                    parent_event_id TEXT,
                    tool_server TEXT,
                    error_class TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_events_actor_kind ON events(actor_kind);
                CREATE INDEX IF NOT EXISTS idx_events_event ON events(event);
                CREATE TABLE events_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                """
            )
            conn.execute(
                "INSERT INTO events_meta(key, value) VALUES ('schema_version', '99')"
            )
            conn.commit()

        self._write_events([self._event_row("bad-mismatch")])
        code, _, stderr = self._run(["--state", str(self.state)])
        self.assertEqual(code, 1)
        self.assertIn("re-index", stderr.lower())


if __name__ == "__main__":
    unittest.main()
