from __future__ import annotations

import datetime as dt
import json
import os
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

    def test_skill_usage_summary_buckets_by_actor_name(self) -> None:
        now = dt.datetime.now(dt.timezone.utc)
        recent = now - dt.timedelta(hours=2)
        old = now - dt.timedelta(days=20)
        self._insert_rows([
            {"event_id": "1", "event": "agent_dispatch", "ts": recent.isoformat(),
             "actor_kind": "agent", "actor_name": "ce-brainstorm", "session_id": "s1"},
            {"event_id": "2", "event": "agent_dispatch", "ts": recent.isoformat(),
             "actor_kind": "agent", "actor_name": "ce-brainstorm", "session_id": "s2"},
            {"event_id": "3", "event": "agent_dispatch", "ts": recent.isoformat(),
             "actor_kind": "agent", "actor_name": "ce-plan", "session_id": "s2"},
            {"event_id": "4", "event": "agent_dispatch", "ts": old.isoformat(),
             "actor_kind": "agent", "actor_name": "ce-old", "session_id": "s3"},
            {"event_id": "5", "event": "agent_dispatch", "ts": recent.isoformat(),
             "actor_kind": "hook", "actor_name": "session-start", "session_id": "s1"},
        ])
        # No filter — see all actor_names recent
        rows = alc_query.get_skill_usage_summary(self.state, since="7d")
        actor_names = [r["actor_name"] for r in rows]
        self.assertIn("ce-brainstorm", actor_names)
        self.assertIn("ce-plan", actor_names)
        self.assertIn("session-start", actor_names)
        self.assertNotIn("ce-old", actor_names)  # outside the 7d window

        # Counts respect order (ce-brainstorm should be first with 2 events)
        first = rows[0]
        self.assertEqual(first["actor_name"], "ce-brainstorm")
        self.assertEqual(first["count"], 2)

        # Prefix filter narrows to ce-*
        ce_rows = alc_query.get_skill_usage_summary(self.state, since="7d", prefix_filter=["ce-"])
        ce_names = {r["actor_name"] for r in ce_rows}
        self.assertEqual(ce_names, {"ce-brainstorm", "ce-plan"})

    def test_skill_usage_summary_missing_db_returns_empty(self) -> None:
        # Fresh state, no db
        self.assertEqual(alc_query.get_skill_usage_summary(self.state), [])

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

    def test_get_suggestions_reads_bounded_json_safe_rows(self) -> None:
        payload = {
            "suggestions": [
                {"recommendation_id": "r1", "title": "One", "rank": 1},
                "skip-me",
                {"recommendation_id": "r2", "title": "Two", "nested": {"ok": True}},
            ]
        }
        (self.state.repo_state_dir / "suggestions.json").write_text(json.dumps(payload), encoding="utf-8")

        rows = alc_query.get_suggestions(self.state, limit=1)

        self.assertEqual(rows, [{"recommendation_id": "r1", "title": "One", "rank": 1}])

    def test_get_suggestions_missing_or_malformed_returns_empty(self) -> None:
        self.assertEqual(alc_query.get_suggestions(self.state), [])

        (self.state.repo_state_dir / "suggestions.json").write_text("{broken", encoding="utf-8")
        self.assertEqual(alc_query.get_suggestions(self.state), [])

        (self.state.repo_state_dir / "suggestions.json").write_text(json.dumps({"suggestions": {}}), encoding="utf-8")
        self.assertEqual(alc_query.get_suggestions(self.state), [])

    def test_get_suggestions_user_scope_returns_empty(self) -> None:
        (self.state.repo_state_dir / "suggestions.json").write_text(
            json.dumps({"suggestions": [{"recommendation_id": "r1"}]}),
            encoding="utf-8",
        )

        self.assertEqual(alc_query.get_suggestions(self.state, scope="user"), [])

    def test_get_proposal_queue_reads_improvement_queue(self) -> None:
        queue = self.state.repo_state_dir / "improvement-queue.jsonl"
        queue.write_text(
            "\n".join(
                [
                    json.dumps({"id": "q1", "kind": "operator_proposed_gate", "status": "open", "ts": "2"}),
                    json.dumps({"id": "q2", "kind": "operator_proposed_gate", "status": "closed", "ts": "1"}),
                ]
            ),
            encoding="utf-8",
        )

        rows = alc_query.get_proposal_queue(self.state, status="open")
        self.assertEqual([row["queue_id"] for row in rows], ["q1"])
        self.assertEqual(rows[0]["proposal_kind"], "gate")

    def test_get_proposal_lifecycle_returns_queue_patch_and_suggestion_rows(self) -> None:
        (self.state.repo_state_dir / "improvement-queue.jsonl").write_text(
            json.dumps({"id": "q1", "kind": "operator_proposed_gate", "status": "open", "ts": "1"}) + "\n",
            encoding="utf-8",
        )
        patch_dir = self.state.repo_state_dir / "patches"
        patch_dir.mkdir()
        (patch_dir / "p1.json").write_text(
            json.dumps({"patch_id": "p1", "status": "pending", "recommendation_id": "r1"}),
            encoding="utf-8",
        )
        (self.state.repo_state_dir / "suggestions.json").write_text(
            json.dumps({"suggestions": [{"recommendation_id": "r2", "kind": "workflow_chain"}]}),
            encoding="utf-8",
        )

        rows = alc_query.get_proposal_lifecycle(self.state)
        self.assertEqual(
            {(row["proposal_kind"], row["artifact_id"]) for row in rows},
            {("gate", "q1"), ("patch", "p1"), ("workflow_chain", "r2")},
        )

    def test_get_proposal_reads_user_scope_return_empty(self) -> None:
        (self.state.repo_state_dir / "improvement-queue.jsonl").write_text(
            json.dumps({"id": "q1", "kind": "operator_proposed_gate", "status": "open"}) + "\n",
            encoding="utf-8",
        )
        self.assertEqual(alc_query.get_proposal_queue(self.state, scope="user"), [])
        self.assertEqual(alc_query.get_proposal_lifecycle(self.state, scope="user"), [])

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

    def test_project_scope_requires_state_handle_for_project_only_reads(self) -> None:
        with self.assertRaises(alc_query.QueryError):
            alc_query.get_gates(scope="project")
        with self.assertRaises(alc_query.QueryError):
            alc_query.get_skill_context(scope="project")

    def test_user_scope_reads_reports_from_state_scope_user_root(self) -> None:
        user_root = Path(self.temp.name) / "user"
        reports = user_root / "reports" / "agent-learning"
        reports.mkdir(parents=True)
        (reports / "latest-approved-gates.md").write_text(
            "\n- domain: repo\n  gate_id: user-gate\n  gate_category: workflow\n  gate: prefer shared resolver\n",
            encoding="utf-8",
        )
        (reports / "latest-skill-context.md").write_text("user context\n", encoding="utf-8")

        gates = alc_query.get_gates(scope="user", user_root=user_root)
        context = alc_query.get_skill_context(scope="user", user_root=user_root)

        self.assertEqual([row["gate_id"] for row in gates], ["user-gate"])
        self.assertEqual(context, "user context\n")

    def test_both_scope_prefers_project_rows_on_gate_collision(self) -> None:
        self.state.reports_dir.mkdir(parents=True, exist_ok=True)
        self.state.reports_dir.joinpath("latest-approved-gates.md").write_text(
            "\n- domain: repo\n  gate_id: shared\n  gate_category: project\n  gate: project wins\n",
            encoding="utf-8",
        )
        user_root = Path(self.temp.name) / "user"
        reports = user_root / "reports" / "agent-learning"
        reports.mkdir(parents=True)
        (reports / "latest-approved-gates.md").write_text(
            "\n- domain: repo\n  gate_id: shared\n  gate_category: user\n  gate: user loses\n"
            "\n- domain: repo\n  gate_id: user-only\n  gate_category: user\n  gate: user remains\n",
            encoding="utf-8",
        )

        rows = alc_query.get_gates(self.state, scope="both", user_root=user_root)

        self.assertEqual([row["gate_id"] for row in rows], ["shared", "user-only"])
        self.assertEqual(rows[0]["_source_scope"], "project")

    def test_env_user_scope_uses_shared_state_scope_resolver(self) -> None:
        user_root = Path(self.temp.name) / "env-user"
        reports = user_root / "reports" / "agent-learning"
        reports.mkdir(parents=True)
        (reports / "latest-skill-context.md").write_text("env context\n", encoding="utf-8")
        old_user = os.environ.get("AGENT_LEARNING_USER")
        try:
            os.environ["AGENT_LEARNING_USER"] = str(user_root)
            self.assertEqual(alc_query.get_skill_context(scope="user"), "env context\n")
        finally:
            if old_user is None:
                os.environ.pop("AGENT_LEARNING_USER", None)
            else:
                os.environ["AGENT_LEARNING_USER"] = old_user

    def test_invalid_scope_fails_through_shared_validation(self) -> None:
        with self.assertRaisesRegex(alc_query.QueryError, "scope must be one of"):
            alc_query.get_gates(self.state, scope="invalid")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
