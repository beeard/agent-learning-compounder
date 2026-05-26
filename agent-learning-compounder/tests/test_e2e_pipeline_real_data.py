from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import sqlite3
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import analyst_score
import recommender_render
import state_handle
import synthesize_samples


def _create_events_db(path: pathlib.Path, samples: list[dict[str, object]]) -> None:
    conn = sqlite3.connect(path)
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
        INSERT INTO events_meta(key, value) VALUES ('schema_version', '4');
        """
    )
    base = dt.datetime(2026, 5, 26, 12, 0, 0, tzinfo=dt.timezone.utc)
    rows = []
    for index, sample in enumerate(samples):
        rows.append(
            (
                f"evt-{index}",
                (base + dt.timedelta(minutes=index)).isoformat(),
                "skill_execution",
                4,
                "subagent",
                sample.get("skill") or "alc-core",
                sample.get("agent_model") or "claude-sonnet-4-6",
                None,
                int(float(sample.get("duration_minutes") or 0) * 60_000),
                int(sample.get("input_tokens") or 0),
                int(sample.get("output_tokens") or 0),
                0,
                0,
                float(sample.get("cost_usd") or 0.0),
                0,
                "[]",
                None,
                "skills",
                None,
                sample.get("session_ref") or f"s{index}",
            )
        )
    conn.executemany("INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


class E2EPipelineRealDataTests(unittest.TestCase):
    def test_synthesize_score_and_render_against_fixture_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            repo.mkdir()
            previous = os.environ.get("AGENT_LEARNING_STATE_DIR")
            os.environ["AGENT_LEARNING_STATE_DIR"] = str(tmp_path / "state")
            try:
                state = state_handle.StateHandle.for_repo(repo)
                state.repo_state_dir.mkdir(parents=True, exist_ok=True)
                state.reports_dir.mkdir(parents=True, exist_ok=True)

                raw_sessions = {
                    f"s{i}": {"session_id": f"s{i}", "agent_model": "claude-sonnet-4-6"}
                    for i in range(5)
                }
                sample_payload = {
                    "metrics": [
                        {"session_ref": "s0", "skill": "alc-core", "duration_minutes": 1, "input_tokens": 10, "output_tokens": 5},
                        {"session_ref": "s1", "skill": "alc-core", "duration_minutes": 1.2, "input_tokens": 11, "output_tokens": 6},
                        {"session_ref": "s2", "skill": "alc-core", "duration_minutes": 1.1, "input_tokens": 12, "output_tokens": 6},
                        {"session_ref": "s3", "skill": "alc-core", "duration_minutes": 7, "input_tokens": 50, "output_tokens": 25},
                        {"session_ref": "s4", "skill": "alc-core", "duration_minutes": 25, "input_tokens": 70, "output_tokens": 30},
                    ]
                }
                samples = synthesize_samples.synthesize(sample_payload, raw_sessions, repo)
                self.assertEqual(len(samples), 5)

                _create_events_db(state.events_sqlite, samples)
                scored = analyst_score.run(state, limit=20)
                self.assertTrue(scored["recommendations"])
                self.assertTrue(any(row["kind"] == "anomaly_duration_spike" for row in scored["recommendations"]))

                target = repo / "skills" / "alc-core" / "SKILL.md"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("# alc-core\n\nObserved baseline.\n", encoding="utf-8")
                derived = [
                    {
                        "kind": "anomaly_investigate",
                        "recommendation_id": "real-signal-1",
                        "title": scored["recommendations"][0]["title"],
                        "details": "Derived from synthesized fixture corpus and analyst_score output.",
                        "target": str(target),
                    }
                ]
                (state.reports_dir / "recommendations.json").write_text(json.dumps(derived, indent=2), encoding="utf-8")

                written, _suggestions, skipped = recommender_render.run(state)
                self.assertEqual(skipped, [])
                self.assertGreaterEqual(written, 1)
                self.assertTrue(json.loads((state.reports_dir / "recommendations.json").read_text(encoding="utf-8")))
                self.assertGreaterEqual(len(list((state.repo_state_dir / "patches").glob("*.json"))), 1)
            finally:
                if previous is None:
                    os.environ.pop("AGENT_LEARNING_STATE_DIR", None)
                else:
                    os.environ["AGENT_LEARNING_STATE_DIR"] = previous


if __name__ == "__main__":
    unittest.main()
