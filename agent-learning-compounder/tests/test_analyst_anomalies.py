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

import analyst_anomalies


class _State:
    pass


def _seed_zscore_events(conn: sqlite3.Connection) -> None:
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

    base = dt.datetime(2026, 5, 26, 12, 0, 0, tzinfo=dt.timezone.utc)
    rows = []

    def _row(event_id: str, dt_value: dt.datetime, duration: int, actor_name: str, *, interrupted: int = 0, err: str | None = None) -> tuple:
        return (
            event_id,
            dt_value.isoformat(),
            "post_tool_use",
            4,
            "subagent",
            actor_name,
            "gpt-4o",
            None,
            duration,
            10,
            8,
            2,
            1,
            0.0,
            interrupted,
            "[]",
            None,
            "bash",
            err,
            f"sess-{actor_name}",
        )

    for i in range(19):
        rows.append(_row(f"shell-ok-{i}", base + dt.timedelta(seconds=i), 100, "shell"))
    rows.append((
        _row(
            "shell-outlier",
            base + dt.timedelta(seconds=20),
            3000,
            "shell",
            interrupted=0,
        )
    ))

    # small bucket intentionally below min_n
    for i in range(3):
        rows.append(_row(f"tiny-{i}", base + dt.timedelta(seconds=40 + i), 120, "tiny"))

    insert_sql = """
        INSERT INTO events (
            event_id, ts, event, schema_version, actor_kind, actor_name, actor_model,
            actor_parent_actor_id, telemetry_duration_ms, telemetry_tokens_in, telemetry_tokens_out,
            telemetry_cache_read_tokens, telemetry_cache_creation_tokens, telemetry_cost_usd,
            telemetry_interrupted, correlation_chain, parent_event_id, tool_server, error_class, session_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    conn.executemany(insert_sql, rows)


def _with_sqlite(tmp_dir: pathlib.Path) -> _State:
    state = _State()
    state.events_sqlite = tmp_dir / "events.sqlite"
    with sqlite3.connect(state.events_sqlite) as conn:
        conn.row_factory = sqlite3.Row
        _seed_zscore_events(conn)
        conn.commit()
    return state


class AnalystAnomaliesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state_dir = pathlib.Path(self.tmp.name)
        self.state = _with_sqlite(self.state_dir)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_zscore_flags_shell_outlier(self) -> None:
        payload = analyst_anomalies.run(self.state, min_n=20, z_threshold=4.0)
        rows = payload["duration_anomalies"]
        self.assertEqual(payload["fallback_mode"], False)
        actor_rows = [row for row in rows if row["actor_name"] == "shell" and row["event"] == "post_tool_use"]
        self.assertTrue(actor_rows)
        outlier_ids = set(actor_rows[0]["supporting_event_ids"])
        self.assertIn("shell-outlier", outlier_ids)

    def test_min_n_filter_skips_small_bucket(self) -> None:
        payload = analyst_anomalies.run(self.state, min_n=4, z_threshold=4.0)
        actor_names = {row["actor_name"] for row in payload["duration_anomalies"]}
        self.assertNotIn("tiny", actor_names)
        self.assertIn("shell", actor_names)

    def test_missing_sqlite_falls_back_to_samples(self) -> None:
        sample_only = _State()
        sample_only.events_sqlite = pathlib.Path(tempfile.mkdtemp()) / "missing.sqlite"
        sample_only.repo_state_dir = sample_only.events_sqlite.parent
        payload = analyst_anomalies.run(sample_only, min_n=4, z_threshold=4.0)
        self.assertTrue(payload["fallback_mode"])
        self.assertEqual(payload["duration_anomalies"], [])


if __name__ == "__main__":
    unittest.main()
