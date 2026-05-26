from __future__ import annotations

import datetime as dt
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
import sys
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

from state_handle import StateHandle
import alc_query


_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    event TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
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
)
"""


class AlcQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir(parents=True, exist_ok=True)
        self.state = StateHandle.for_repo(self.repo)
        self.state.repo_state_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _connect(self):
        sqlite3.connect(self.state.events_sqlite).execute("DELETE FROM sqlite_master")

    def _make_db(self) -> None:
        conn = sqlite3.connect(self.state.events_sqlite)
        conn.executescript(_TABLE_SQL)
        conn.commit()
        conn.close()

    def _insert_rows(self, rows: list[dict]) -> None:
        conn = sqlite3.connect(self.state.events_sqlite)
        conn.executescript("DROP TABLE IF EXISTS events;\n" + _TABLE_SQL)
        conn.executemany(
            """
            INSERT INTO events (
                event_id, ts, event, schema_version, actor_kind, actor_name,
                actor_model, actor_parent_actor_id, telemetry_duration_ms,
                telemetry_tokens_in, telemetry_tokens_out,
                telemetry_cache_read_tokens, telemetry_cache_creation_tokens,
                telemetry_cost_usd, telemetry_interrupted,
                correlation_chain, parent_event_id, tool_server, error_class, session_id
            )
            VALUES (?, ?, ?, 4, ?, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?, ?, NULL, NULL, ?)
            """,
            [
                (
                    row["event_id"],
                    row["ts"],
                    row["event"],
                    row.get("actor_kind", "main_agent"),
                    row.get("actor_name", "tester"),
                    row.get("correlation_chain", "[]"),
                    row.get("parent_event_id"),
                    row.get("session_id"),
                )
                for row in rows
            ],
        )
        conn.commit()
        conn.close()

    def test_get_apply_log_filters_by_time_and_kind(self) -> None:
        now = dt.datetime.now(dt.timezone.utc)
        recent = now - dt.timedelta(hours=1)
        old = now - dt.timedelta(days=2)
        self._insert_rows([
            {"event_id": "1", "event": "session_start", "ts": old.isoformat(), "session_id": "s1"},
            {"event_id": "2", "event": "patch_applied", "ts": recent.isoformat(), "session_id": "s1"},
            {"event_id": "3", "event": "patch_reverted", "ts": recent.isoformat(), "session_id": "s1"},
            {"event_id": "4", "event": "other_event", "ts": recent.isoformat(), "session_id": "s1"},
        ])
        rows = alc_query.get_apply_log(self.state, since="24h")
        self.assertEqual([row["event_id"] for row in rows], ["2", "3"])

    def test_apply_log_with_kind_filter(self) -> None:
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        self._insert_rows([
            {"event_id": "a", "event": "patch_applied", "ts": now, "session_id": "s1"},
            {"event_id": "b", "event": "patch_reverted", "ts": now, "session_id": "s1"},
            {"event_id": "c", "event": "patch_applied", "ts": now, "session_id": "s1"},
        ])
        rows = alc_query.get_apply_log(self.state, kind_filter=["patch_applied"])
        self.assertEqual([row["event_id"] for row in rows], ["a", "c"])

    def test_read_only_connection_rejects_write(self) -> None:
        self._insert_rows([{"event_id": "1", "event": "patch_applied", "ts": dt.datetime.now(dt.timezone.utc).isoformat(), "session_id": "s1"}])
        conn = sqlite3.connect(f"file:{self.state.events_sqlite}?mode=ro", uri=True)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("CREATE TABLE reject_me(x INT)")
        finally:
            conn.close()

    def test_get_recommendations_reads_reports_json(self) -> None:
        payload = [{"id": "r1", "title": "add guardrails"}, {"id": "r2", "title": "reduce noise"}]
        self.state.reports_dir.mkdir(parents=True, exist_ok=True)
        (self.state.reports_dir / "recommendations.json").write_text(json.dumps(payload), encoding="utf-8")

        recommendations = alc_query.get_recommendations(self.state)
        self.assertEqual(len(recommendations), 2)
        self.assertEqual(recommendations[0]["id"], "r1")

    def test_get_pending_patches_filters_status(self) -> None:
        patch_dir = self.state.repo_state_dir / "patches"
        patch_dir.mkdir(parents=True)
        (patch_dir / "p1.json").write_text(json.dumps({"patch_id": "p1", "status": "pending"}), encoding="utf-8")
        (patch_dir / "p2.json").write_text(json.dumps({"patch_id": "p2", "status": "rejected"}), encoding="utf-8")
        (patch_dir / "p3.json").write_text(json.dumps({"patch_id": "p3"}), encoding="utf-8")

        rows = alc_query.get_pending_patches(self.state)
        self.assertEqual({r["patch_id"] for r in rows}, {"p1", "p3"})

    def test_get_event_dag_builds_hierarchy(self) -> None:
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        self._insert_rows([
            {"event_id": "root", "event": "patch_applied", "ts": now, "session_id": "s1", "parent_event_id": ""},
            {"event_id": "c1", "event": "patch_reverted", "ts": now, "session_id": "s1", "parent_event_id": "root"},
            {"event_id": "c2", "event": "eval_verdict", "ts": now, "session_id": "s1", "parent_event_id": "c1"},
            {"event_id": "c3", "event": "eval_verdict", "ts": now, "session_id": "s1", "parent_event_id": "root"},
        ])

        result = alc_query.get_event_dag(self.state, "s1")
        self.assertEqual(result["session_id"], "s1")
        self.assertEqual(len(result["nodes"]), 1)

        root = result["nodes"][0]
        self.assertEqual(root["event_id"], "root")
        child_ids = {child["event_id"] for child in root["children"]}
        self.assertEqual(child_ids, {"c1", "c3"})
        self.assertEqual(len(root["children"][0]["children"]), 1)

    def test_get_actor_summary_groups_by_actor_kind(self) -> None:
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        rows = [
            {"event_id": "1", "event": "patch_applied", "ts": now, "session_id": "s1", "actor_kind": "hook", "actor_name": "h1"},
            {"event_id": "2", "event": "eval_verdict", "ts": now, "session_id": "s1", "actor_kind": "main_agent", "actor_name": "m1"},
            {"event_id": "3", "event": "eval_verdict", "ts": now, "session_id": "s1", "actor_kind": "main_agent", "actor_name": "m2"},
        ]
        self._insert_rows(rows)
        summary = alc_query.get_actor_summary(self.state, since="7d")
        self.assertEqual(summary["total"], 3)
        self.assertEqual({entry["actor_kind"] for entry in summary["by_actor_kind"]}, {"hook", "main_agent"})

    def test_get_skill_invocation_history_filters_by_skill(self) -> None:
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        self._insert_rows([
            {"event_id": "a", "event": "skill_applied", "ts": now, "session_id": "s1", "actor_kind": "subagent", "actor_name": "alpha"},
            {"event_id": "b", "event": "skill_loaded", "ts": now, "session_id": "s1", "actor_kind": "subagent", "actor_name": "beta"},
            {"event_id": "c", "event": "skill_applied", "ts": now, "session_id": "s1", "actor_kind": "subagent", "actor_name": "alpha"},
        ])
        rows = alc_query.get_skill_invocation_history(self.state, "alpha")
        self.assertEqual([row["event_id"] for row in rows], ["a", "c"])


if __name__ == "__main__":
    unittest.main()
