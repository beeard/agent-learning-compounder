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

import analyst_correlations


class _State:
    pass


def _create_fixture(path: pathlib.Path) -> _State:
    state = _State()
    state.events_sqlite = path / "events.sqlite"
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
            "g1",
            (now).isoformat(),
            "session_start",
            4,
            "main_agent",
            "gate_alpha",
            "gpt-4o",
            None,
            20,
            4,
            1,
            0,
            0,
            0.01,
            0,
            '[]',
            None,
            None,
            None,
            "session-a",
        ),
        (
            "t1",
            (now + dt.timedelta(seconds=1)).isoformat(),
            "post_tool_use",
            4,
            "subagent",
            "git",
            "gpt-4o",
            None,
            120,
            10,
            10,
            4,
            2,
            0.6,
            0,
            '[{"role": "parent", "id": "g1"}]',
            "g1",
            "bash",
            None,
            "session-a",
        ),
        (
            "t2",
            (now + dt.timedelta(seconds=2)).isoformat(),
            "post_tool_use",
            4,
            "subagent",
            "git",
            "gpt-4o",
            None,
            200,
            11,
            9,
            8,
            4,
            0.9,
            1,
            '[{"role": "parent", "id": "g1"}]',
            "g1",
            "bash",
            "tool_error",
            "session-a",
        ),
        (
            "st1",
            (now + dt.timedelta(seconds=20)).isoformat(),
            "stop",
            4,
            "main_agent",
            "watchdog",
            "gpt-4o",
            None,
            8,
            4,
            1,
            0,
            0,
            0.02,
            0,
            '[]',
            None,
            None,
            None,
            "session-a",
        ),
        (
            "p1",
            (now + dt.timedelta(hours=1)).isoformat(),
            "tool_use_pair",
            4,
            "subagent",
            "search",
            "gpt-4o-mini",
            None,
            700,
            13,
            12,
            1,
            1,
            1.2,
            0,
            '[]',
            None,
            "search",
            None,
            "session-b",
        ),
        (
            "p2",
            (now + dt.timedelta(hours=1, seconds=5)).isoformat(),
            "tool_use_pair",
            4,
            "subagent",
            "search",
            "gpt-4o-mini",
            None,
            680,
            12,
            15,
            1,
            1,
            1.1,
            0,
            '[]',
            None,
            "search",
            None,
            "session-b",
        ),
        (
            "eval1",
            (now + dt.timedelta(hours=2)).isoformat(),
            "eval_verdict",
            4,
            "eval_judge",
            "eval",
            "gpt-small",
            None,
            4,
            2,
            2,
            0,
            0,
            0.03,
            0,
            '[]',
            None,
            None,
            None,
            "session-a",
        ),
    ]

    insert_sql = """
        INSERT INTO events (
            event_id, ts, event, schema_version, actor_kind, actor_name, actor_model,
            actor_parent_actor_id, telemetry_duration_ms, telemetry_tokens_in, telemetry_tokens_out,
            telemetry_cache_read_tokens, telemetry_cache_creation_tokens, telemetry_cost_usd,
            telemetry_interrupted, correlation_chain, parent_event_id, tool_server, error_class, session_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    conn.executemany(insert_sql, rows)
    conn.commit()
    conn.close()
    return state


class AnalystCorrelationsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state = _create_fixture(pathlib.Path(self.tmp.name))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_gates_and_dag_tables_present(self) -> None:
        payload = analyst_correlations.run(self.state)
        self.assertFalse(payload["fallback_mode"])

        gate_rows = payload["gate_effectiveness"]
        self.assertTrue(gate_rows)
        self.assertIn("gate_id", gate_rows[0])
        self.assertIn("evidence", gate_rows[0])
        self.assertIsInstance(gate_rows[0]["evidence"].get("event_ids"), list)

        dag_rows = payload["dag_cost_attribution"]
        self.assertTrue(dag_rows)
        self.assertIn("parent_actor", dag_rows[0])
        self.assertIn("evidence", dag_rows[0])
        self.assertIsInstance(dag_rows[0]["evidence"].get("event_ids"), list)

    def test_fallback_if_sqlite_missing(self) -> None:
        missing = _State()
        missing.events_sqlite = pathlib.Path(tempfile.mkdtemp()) / "missing.sqlite"
        payload = analyst_correlations.run(missing)
        self.assertTrue(payload["fallback_mode"])
        self.assertEqual(payload["gate_effectiveness"], [])


if __name__ == "__main__":
    unittest.main()
