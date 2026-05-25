from __future__ import annotations

import json
import math
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

import analyst_score


class _State:
    pass


def _build_events(state: _State) -> None:
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

    base = dt.datetime(2026, 5, 26, 10, 0, 0, tzinfo=dt.timezone.utc)
    rows = [
        (
            "g1", (base).isoformat(), "session_start", 4, "main_agent", "gate_alpha", "gpt-4o", None, 20, 0, 0, 0, 0, 0.0, 0,
            "[]", None, None, None, "sess-a"
        ),
        (
            "p1", (base + dt.timedelta(seconds=2)).isoformat(), "post_tool_use", 4, "subagent", "git", "gpt-4o", None, 1200, 40, 50, 1, 0, 1.2, 0,
            '[{"role":"parent", "id": "g1"}]', "g1", "bash", None, "sess-a"
        ),
        (
            "p2", (base + dt.timedelta(seconds=4)).isoformat(), "post_tool_use", 4, "subagent", "git", "gpt-4o", None, 1100, 46, 60, 1, 0, 1.1, 1,
            '[{"role":"parent", "id": "g1"}]', "g1", "bash", "tool_error", "sess-a"
        ),
        (
            "p3", (base + dt.timedelta(minutes=10)).isoformat(), "tool_use_pair", 4, "subagent", "search", "gpt-mini", None, 950, 20, 19, 0, 0, 0.3, 0,
            '[]', None, "search", None, "sess-a"
        ),
        (
            "p4", (base + dt.timedelta(minutes=20)).isoformat(), "tool_use_pair", 4, "subagent", "search", "gpt-mini", None, 980, 30, 18, 0, 0, 0.4, 0,
            '[]', None, "search", None, "sess-a"
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


def _state_with_data(tmp_dir: pathlib.Path) -> _State:
    state = _State()
    state.repo_state_dir = tmp_dir
    state.events_sqlite = tmp_dir / "events.sqlite"
    state.outcomes_json = tmp_dir / "outcomes.json"
    _build_events(state)
    return state


class AnalystScoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.state = _state_with_data(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_no_outcomes_uses_neutral_weight(self) -> None:
        payload = analyst_score.run(self.state, limit=20)
        self.assertFalse(payload["fallback_mode"])
        recs = payload["recommendations"]
        self.assertTrue(recs)
        for rec in recs:
            self.assertEqual(rec["outcome_weight"], 1.0)
            self.assertIsInstance(rec["evidence"].get("event_ids"), list)

    def test_negative_outcomes_down_weights_kind(self) -> None:
        self.state.outcomes_json.write_text(
            json.dumps(
                [
                    {"kind": "correlation_gate_effectiveness", "verdict": "negative"},
                    {"kind": "correlation_gate_effectiveness", "verdict": "negative"},
                    {"kind": "correlation_gate_effectiveness", "verdict": "positive"},
                ],
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        payload = analyst_score.run(self.state, limit=20)
        rec = next(
            (item for item in payload["recommendations"] if item["kind"] == "correlation_gate_effectiveness"),
            None,
        )
        self.assertIsNotNone(rec)
        self.assertLess(rec["outcome_weight"], 1.0)

    def test_evidence_strength_matches_log(self) -> None:
        payload = analyst_score.run(self.state, limit=20)
        sample = payload["recommendations"][0]
        self.assertAlmostEqual(
            sample["evidence_strength"],
            math.log(max(1, int(sample["supporting_events"]))),
        )


if __name__ == "__main__":
    unittest.main()
