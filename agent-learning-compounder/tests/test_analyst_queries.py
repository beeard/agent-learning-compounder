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

import analyst_queries


class _State:
    pass


def _sqlite_path(root: pathlib.Path) -> pathlib.Path:
    return root / "events.sqlite"


def _create_schema(conn: sqlite3.Connection) -> None:
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


def _seed_events(conn: sqlite3.Connection) -> None:
    base = dt.datetime(2026, 5, 26, 12, 0, 0, tzinfo=dt.timezone.utc)

    events = [
        {
            "event_id": "e1",
            "ts": base.isoformat(),
            "event": "session_start",
            "schema_version": 4,
            "actor_kind": "main_agent",
            "actor_name": "gate_alpha",
            "actor_model": "gpt-4",
            "actor_parent_actor_id": None,
            "telemetry_duration_ms": 40,
            "telemetry_tokens_in": 0,
            "telemetry_tokens_out": 0,
            "telemetry_cache_read_tokens": 0,
            "telemetry_cache_creation_tokens": 0,
            "telemetry_cost_usd": 0.01,
            "telemetry_interrupted": 0,
            "correlation_chain": "[]",
            "parent_event_id": None,
            "tool_server": None,
            "error_class": None,
            "session_id": "sess-1",
        },
        {
            "event_id": "e2",
            "ts": (base + dt.timedelta(seconds=1)).isoformat(),
            "event": "post_tool_use",
            "schema_version": 4,
            "actor_kind": "subagent",
            "actor_name": "git",
            "actor_model": "gpt-4",
            "actor_parent_actor_id": None,
            "telemetry_duration_ms": 500,
            "telemetry_tokens_in": 100,
            "telemetry_tokens_out": 120,
            "telemetry_cache_read_tokens": 10,
            "telemetry_cache_creation_tokens": 8,
            "telemetry_cost_usd": 0.40,
            "telemetry_interrupted": 0,
            "correlation_chain": '[{"role":"parent", "id":"e1"}]',
            "parent_event_id": "e1",
            "tool_server": "bash",
            "error_class": None,
            "session_id": "sess-1",
        },
        {
            "event_id": "e3",
            "ts": (base + dt.timedelta(seconds=2)).isoformat(),
            "event": "post_tool_use",
            "schema_version": 4,
            "actor_kind": "subagent",
            "actor_name": "git",
            "actor_model": "gpt-4",
            "actor_parent_actor_id": None,
            "telemetry_duration_ms": 480,
            "telemetry_tokens_in": 95,
            "telemetry_tokens_out": 110,
            "telemetry_cache_read_tokens": 9,
            "telemetry_cache_creation_tokens": 7,
            "telemetry_cost_usd": 1.20,
            "telemetry_interrupted": 0,
            "correlation_chain": '[{"role":"parent", "id":"e1"}]',
            "parent_event_id": "e1",
            "tool_server": "bash",
            "error_class": None,
            "session_id": "sess-1",
        },
        {
            "event_id": "e4",
            "ts": (base + dt.timedelta(seconds=4)).isoformat(),
            "event": "post_tool_use",
            "schema_version": 4,
            "actor_kind": "main_agent",
            "actor_name": "search",
            "actor_model": "gpt-4o",
            "actor_parent_actor_id": None,
            "telemetry_duration_ms": 90,
            "telemetry_tokens_in": 40,
            "telemetry_tokens_out": 80,
            "telemetry_cache_read_tokens": 5,
            "telemetry_cache_creation_tokens": 5,
            "telemetry_cost_usd": 0.35,
            "telemetry_interrupted": 0,
            "correlation_chain": '[{"role":"parent", "id":"e1"}]',
            "parent_event_id": "e1",
            "tool_server": "net",
            "error_class": None,
            "session_id": "sess-1",
        },
        {
            "event_id": "e5",
            "ts": (base + dt.timedelta(seconds=12)).isoformat(),
            "event": "post_tool_use",
            "schema_version": 4,
            "actor_kind": "subagent",
            "actor_name": "search",
            "actor_model": "gpt-4o",
            "actor_parent_actor_id": None,
            "telemetry_duration_ms": 85,
            "telemetry_tokens_in": 70,
            "telemetry_tokens_out": 90,
            "telemetry_cache_read_tokens": 0,
            "telemetry_cache_creation_tokens": 0,
            "telemetry_cost_usd": 0.45,
            "telemetry_interrupted": 1,
            "correlation_chain": '[{"role":"parent", "id":"e1"}]',
            "parent_event_id": "e1",
            "tool_server": "net",
            "error_class": "tool_error",
            "session_id": "sess-1",
        },
        {
            "event_id": "e6",
            "ts": (base + dt.timedelta(seconds=16)).isoformat(),
            "event": "stop",
            "schema_version": 4,
            "actor_kind": "main_agent",
            "actor_name": "session_watchdog",
            "actor_model": "gpt-4o",
            "actor_parent_actor_id": None,
            "telemetry_duration_ms": 10,
            "telemetry_tokens_in": 0,
            "telemetry_tokens_out": 2,
            "telemetry_cache_read_tokens": 0,
            "telemetry_cache_creation_tokens": 0,
            "telemetry_cost_usd": 0.0,
            "telemetry_interrupted": 0,
            "correlation_chain": "[]",
            "parent_event_id": None,
            "tool_server": None,
            "error_class": None,
            "session_id": "sess-1",
        },
        {
            "event_id": "e7",
            "ts": (base + dt.timedelta(seconds=18)).isoformat(),
            "event": "post_tool_use",
            "schema_version": 4,
            "actor_kind": "background_agent",
            "actor_name": "bg_tasker",
            "actor_model": "gpt-small",
            "actor_parent_actor_id": None,
            "telemetry_duration_ms": 350,
            "telemetry_tokens_in": 14,
            "telemetry_tokens_out": 22,
            "telemetry_cache_read_tokens": 6,
            "telemetry_cache_creation_tokens": 4,
            "telemetry_cost_usd": 2.3,
            "telemetry_interrupted": 1,
            "correlation_chain": "[]",
            "parent_event_id": None,
            "tool_server": "background",
            "error_class": None,
            "session_id": "sess-1",
        },
        {
            "event_id": "e8",
            "ts": (base + dt.timedelta(days=-6)).isoformat(),
            "event": "session_start",
            "schema_version": 4,
            "actor_kind": "main_agent",
            "actor_name": "drifty",
            "actor_model": "gpt-4",
            "actor_parent_actor_id": None,
            "telemetry_duration_ms": 40,
            "telemetry_tokens_in": 0,
            "telemetry_tokens_out": 0,
            "telemetry_cache_read_tokens": 0,
            "telemetry_cache_creation_tokens": 0,
            "telemetry_cost_usd": 0.02,
            "telemetry_interrupted": 0,
            "correlation_chain": "[]",
            "parent_event_id": None,
            "tool_server": None,
            "error_class": None,
            "session_id": "sess-drift",
        },
        {
            "event_id": "e9",
            "ts": (base + dt.timedelta(days=-1)).isoformat(),
            "event": "session_start",
            "schema_version": 4,
            "actor_kind": "main_agent",
            "actor_name": "drifty",
            "actor_model": "gpt-4",
            "actor_parent_actor_id": None,
            "telemetry_duration_ms": 45,
            "telemetry_tokens_in": 0,
            "telemetry_tokens_out": 0,
            "telemetry_cache_read_tokens": 0,
            "telemetry_cache_creation_tokens": 0,
            "telemetry_cost_usd": 0.02,
            "telemetry_interrupted": 0,
            "correlation_chain": "[]",
            "parent_event_id": None,
            "tool_server": None,
            "error_class": None,
            "session_id": "sess-drift",
        },
        {
            "event_id": "e10",
            "ts": (base + dt.timedelta(days=-46)).isoformat(),
            "event": "session_start",
            "schema_version": 4,
            "actor_kind": "main_agent",
            "actor_name": "drifty",
            "actor_model": "gpt-4",
            "actor_parent_actor_id": None,
            "telemetry_duration_ms": 42,
            "telemetry_tokens_in": 0,
            "telemetry_tokens_out": 0,
            "telemetry_cache_read_tokens": 0,
            "telemetry_cache_creation_tokens": 0,
            "telemetry_cost_usd": 0.02,
            "telemetry_interrupted": 0,
            "correlation_chain": "[]",
            "parent_event_id": None,
            "tool_server": None,
            "error_class": None,
            "session_id": "sess-drift",
        },
        {
            "event_id": "e11",
            "ts": (base + dt.timedelta(days=-41)).isoformat(),
            "event": "session_start",
            "schema_version": 4,
            "actor_kind": "main_agent",
            "actor_name": "drifty",
            "actor_model": "gpt-4",
            "actor_parent_actor_id": None,
            "telemetry_duration_ms": 43,
            "telemetry_tokens_in": 0,
            "telemetry_tokens_out": 0,
            "telemetry_cache_read_tokens": 0,
            "telemetry_cache_creation_tokens": 0,
            "telemetry_cost_usd": 0.02,
            "telemetry_interrupted": 0,
            "correlation_chain": "[]",
            "parent_event_id": None,
            "tool_server": None,
            "error_class": None,
            "session_id": "sess-drift",
        },
        {
            "event_id": "e12",
            "ts": (base + dt.timedelta(days=-37)).isoformat(),
            "event": "session_start",
            "schema_version": 4,
            "actor_kind": "main_agent",
            "actor_name": "drifty",
            "actor_model": "gpt-4",
            "actor_parent_actor_id": None,
            "telemetry_duration_ms": 45,
            "telemetry_tokens_in": 0,
            "telemetry_tokens_out": 0,
            "telemetry_cache_read_tokens": 0,
            "telemetry_cache_creation_tokens": 0,
            "telemetry_cost_usd": 0.02,
            "telemetry_interrupted": 0,
            "correlation_chain": "[]",
            "parent_event_id": None,
            "tool_server": None,
            "error_class": None,
            "session_id": "sess-drift",
        },
        {
            "event_id": "e13",
            "ts": (base + dt.timedelta(hours=-2)).isoformat(),
            "event": "session_start",
            "schema_version": 4,
            "actor_kind": "main_agent",
            "actor_name": "gate_beta",
            "actor_model": "gpt-4o",
            "actor_parent_actor_id": None,
            "telemetry_duration_ms": 28,
            "telemetry_tokens_in": 0,
            "telemetry_tokens_out": 0,
            "telemetry_cache_read_tokens": 0,
            "telemetry_cache_creation_tokens": 0,
            "telemetry_cost_usd": 0.01,
            "telemetry_interrupted": 0,
            "correlation_chain": "[]",
            "parent_event_id": None,
            "tool_server": None,
            "error_class": None,
            "session_id": "sess-2",
        },
        {
            "event_id": "e14",
            "ts": (base + dt.timedelta(hours=-2, seconds=3)).isoformat(),
            "event": "post_tool_use",
            "schema_version": 4,
            "actor_kind": "subagent",
            "actor_name": "git",
            "actor_model": "gpt-4o",
            "actor_parent_actor_id": None,
            "telemetry_duration_ms": 420,
            "telemetry_tokens_in": 90,
            "telemetry_tokens_out": 110,
            "telemetry_cache_read_tokens": 8,
            "telemetry_cache_creation_tokens": 4,
            "telemetry_cost_usd": 1.40,
            "telemetry_interrupted": 0,
            "correlation_chain": '[{"role":"parent", "id":"e13"}]',
            "parent_event_id": "e13",
            "tool_server": "bash",
            "error_class": None,
            "session_id": "sess-2",
        },
        {
            "event_id": "e15",
            "ts": (base + dt.timedelta(hours=-2, seconds=7)).isoformat(),
            "event": "eval_verdict",
            "schema_version": 4,
            "actor_kind": "eval_judge",
            "actor_name": "judge",
            "actor_model": "gpt-eval",
            "actor_parent_actor_id": None,
            "telemetry_duration_ms": 40,
            "telemetry_tokens_in": 20,
            "telemetry_tokens_out": 5,
            "telemetry_cache_read_tokens": 2,
            "telemetry_cache_creation_tokens": 1,
            "telemetry_cost_usd": 0.9,
            "telemetry_interrupted": 0,
            "correlation_chain": "[]",
            "parent_event_id": None,
            "tool_server": None,
            "error_class": None,
            "session_id": "sess-eval",
        },
    ]

    insert_sql = """
        INSERT INTO events (
            event_id, ts, event, schema_version, actor_kind, actor_name, actor_model,
            actor_parent_actor_id, telemetry_duration_ms, telemetry_tokens_in, telemetry_tokens_out,
            telemetry_cache_read_tokens, telemetry_cache_creation_tokens, telemetry_cost_usd,
            telemetry_interrupted, correlation_chain, parent_event_id, tool_server, error_class, session_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    conn.executemany(
        insert_sql,
        [
            (
                row["event_id"],
                row["ts"],
                row["event"],
                row["schema_version"],
                row["actor_kind"],
                row["actor_name"],
                row["actor_model"],
                row["actor_parent_actor_id"],
                row["telemetry_duration_ms"],
                row["telemetry_tokens_in"],
                row["telemetry_tokens_out"],
                row["telemetry_cache_read_tokens"],
                row["telemetry_cache_creation_tokens"],
                row["telemetry_cost_usd"],
                row["telemetry_interrupted"],
                row["correlation_chain"],
                row["parent_event_id"],
                row["tool_server"],
                row["error_class"],
                row["session_id"],
            )
            for row in events
        ],
    )


def _build_fixture(path: pathlib.Path) -> _State:
    state = _State()
    state.events_sqlite = _sqlite_path(path)
    with sqlite3.connect(state.events_sqlite) as conn:
        conn.row_factory = sqlite3.Row
        _create_schema(conn)
        _seed_events(conn)
        conn.commit()
    return state


class AnalystQueriesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.state = _build_fixture(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_open_events_db_read_only(self) -> None:
        conn = analyst_queries.open_events_db(self.state)
        with self.assertRaises(sqlite3.OperationalError):
            conn.execute("CREATE TABLE bad_table(x INT)")
        conn.close()

    def test_open_events_db_schema_version_mismatch(self) -> None:
        mismatch_root = pathlib.Path(tempfile.mkdtemp())
        target = mismatch_root / "events.sqlite"
        with sqlite3.connect(target) as conn:
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
                CREATE TABLE events_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT INTO events_meta(key, value) VALUES ('schema_version', '3');
                """
            )
            conn.commit()

        mismatch_state = _State()
        mismatch_state.events_sqlite = target
        with self.assertRaisesRegex(RuntimeError, "schema_version"):
            analyst_queries.open_events_db(mismatch_state)

    def test_q_shapes_match_catalog(self) -> None:
        with sqlite3.connect(self.state.events_sqlite) as conn:
            conn.row_factory = sqlite3.Row
            for query in analyst_queries.QUERIES:
                query_id = str(query["id"])
                kwargs = {"now": "2026-05-26T12:00:00+00:00"} if query_id == "Q9" else {}
                rows = analyst_queries.query_by_id(conn, query_id, **kwargs)
                self.assertTrue(rows, f"query {query_id} should return at least one row")
                shape = set(query["shape"])
                self.assertTrue(shape.issubset(set(rows[0].keys())), f"query {query_id} shape mismatch")


if __name__ == "__main__":
    unittest.main()
