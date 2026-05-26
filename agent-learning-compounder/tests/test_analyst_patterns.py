from __future__ import annotations

import pathlib
import sqlite3
import sys
import tempfile
import unittest

import datetime as dt

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

import analyst_patterns


class _State:
    pass


def _build_state_with_sqlite(root: pathlib.Path) -> _State:
    state = _State()
    state.events_sqlite = root / "events.sqlite"
    conn = sqlite3.connect(state.events_sqlite)
    conn.executescript(
        """
        CREATE TABLE events (
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
            error_class TEXT,
            session_id TEXT
        );
        CREATE INDEX idx_events_actor_kind ON events(actor_kind);
        CREATE INDEX idx_events_event ON events(event);
        CREATE TABLE events_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO events_meta(key, value) VALUES ('schema_version', '4');
        """
    )

    now = dt.datetime(2026, 5, 26, 12, 0, 0, tzinfo=dt.timezone.utc)
    rows = [
        (
            "s1", now.isoformat(), "session_start", 4, "main_agent", "gate_alpha", "gpt-4o", None, 20, 0, 0, 0, 0, 0.02, 0,
            '[]', None, None, None, "session-a"
        ),
        (
            "t1", (now + dt.timedelta(seconds=4)).isoformat(), "post_tool_use", 4, "subagent", "git", "gpt-4o", None, 90, 12, 8, 4, 2, 0.3, 0,
            '[{"id":"s1","role":"parent"}]', "s1", "bash", None, "session-a"
        ),
        (
            "t2", (now + dt.timedelta(seconds=10)).isoformat(), "post_tool_use", 4, "subagent", "git", "gpt-4o", None, 110, 12, 8, 4, 2, 0.4, 0,
            '[{"id":"s1","role":"parent"}]', "s1", "bash", "tool_error", "session-a"
        ),
        (
            "t3", (now + dt.timedelta(seconds=20)).isoformat(), "post_tool_use", 4, "background_agent", "bg", "gpt-small", None, 150, 6, 5, 0, 1, 0.1, 1,
            '[]', None, "background", None, "session-a"
        ),
        (
            "d1", (now + dt.timedelta(days=-2)).isoformat(), "session_start", 4, "main_agent", "drifty", "gpt-4o", None, 10, 0, 0, 0, 0, 0.0, 0,
            '[]', None, None, None, "session-d"
        ),
        (
            "d2", (now + dt.timedelta(days=-34)).isoformat(), "session_start", 4, "main_agent", "drifty", "gpt-4o", None, 10, 0, 0, 0, 0, 0.0, 0,
            '[]', None, None, None, "session-d"
        ),
    ]

    conn.executemany(
        """
        INSERT INTO events (
            event_id, ts, event, schema_version, actor_kind, actor_name, actor_model,
            actor_parent_actor_id, telemetry_duration_ms, telemetry_tokens_in, telemetry_tokens_out,
            telemetry_cache_read_tokens, telemetry_cache_creation_tokens, telemetry_cost_usd,
            telemetry_interrupted, correlation_chain, parent_event_id, tool_server, error_class, session_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    conn.close()
    return state


def _state_with_samples(root: pathlib.Path) -> _State:
    state = _State()
    state.events_sqlite = root / "missing.sqlite"
    state.repo_state_dir = root
    (root / "samples.json").write_text(
        '[{"id":"a","value":1}]', encoding="utf-8"
    )
    return state


class AnalystPatternsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.state = _build_state_with_sqlite(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_frequency_by_skill_shape(self) -> None:
        payload = analyst_patterns.run(self.state)
        rows = payload["frequency_by_skill"]
        self.assertTrue(rows)
        first = rows[0]
        self.assertIn("skill", first)
        self.assertIn("actor_kind", first)
        self.assertIn("evidence", first)
        self.assertIn("sample_count", first)

    def test_co_occurrence_pairs(self) -> None:
        payload = analyst_patterns.run(self.state)
        pairs = payload["co_occurrence_pairs"]
        self.assertTrue(pairs)
        self.assertEqual(pairs[0]["parent_actor"], "gate_alpha")
        self.assertEqual(pairs[0]["child_actor"], "git")
        self.assertIsInstance(pairs[0]["evidence"].get("event_ids"), list)

    def test_fallback_if_sqlite_absent(self) -> None:
        sample_state = _state_with_samples(self.root)
        payload = analyst_patterns.run(sample_state)
        self.assertTrue(payload["fallback_mode"])
        self.assertEqual(payload["frequency_by_skill"], [])


if __name__ == "__main__":
    unittest.main()
