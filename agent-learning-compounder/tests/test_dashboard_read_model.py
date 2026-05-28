from __future__ import annotations

import ast
import datetime as dt
import json
import pathlib
import sqlite3
import sys
import tempfile
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

from state_handle import StateHandle
import dashboard_read_model


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


def _called_names(function: ast.FunctionDef) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                names.add(node.func.attr)
    return names


def _function_from(path: pathlib.Path, name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{path} has no function named {name}")


class DashboardReadModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.state = StateHandle.for_repo(self.repo)
        self.state.repo_state_dir.mkdir(parents=True, exist_ok=True)
        self.state.reports_dir.mkdir(parents=True, exist_ok=True)
        self.user_root = self.root / "user"
        (self.user_root / "reports" / "agent-learning").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_event_db(self) -> None:
        conn = sqlite3.connect(self.state.events_sqlite)
        conn.executescript("DROP TABLE IF EXISTS events;\n" + _TABLE_SQL)
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO events (
                event_id, ts, event, schema_version, actor_kind, actor_name,
                actor_model, actor_parent_actor_id, telemetry_duration_ms,
                telemetry_tokens_in, telemetry_tokens_out,
                telemetry_cache_read_tokens, telemetry_cache_creation_tokens,
                telemetry_cost_usd, telemetry_interrupted,
                correlation_chain, parent_event_id, tool_server, error_class, session_id
            )
            VALUES ('e1', ?, 'patch_applied', 4, 'main_agent', 'ce-work',
                    NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
                    '[]', NULL, NULL, NULL, 's1')
            """,
            (now,),
        )
        conn.commit()
        conn.close()

    def test_static_archive_payload_reads_latest_and_history(self) -> None:
        reports = self.user_root / "reports" / "agent-learning"
        (reports / "latest-report.html").write_text(
            '<html><script id="report-payload">{"date":"2026-05-27","repo":"repo"}</script></html>',
            encoding="utf-8",
        )
        (reports / "metrics.jsonl").write_text(
            '{"date":"one","totals":{"gates":1}}\n'
            'broken\n'
            '{"date":"two","totals":{"gates":2}}\n',
            encoding="utf-8",
        )

        payload = dashboard_read_model.build_static_payload(self.user_root, history_limit=1)

        self.assertEqual(payload["latest"]["repo"], "repo")
        self.assertEqual([row["date"] for row in payload["history"]], ["two"])
        self.assertIn("archive_diagnostics", payload)

    def test_fastapi_payload_preserves_compatibility_keys(self) -> None:
        self.state.reports_dir.joinpath("latest-approved-gates.md").write_text(
            "\n- domain: validation\n"
            "  gate_id: cccccccccccc\n"
            "  gate_category: check\n"
            "  gate: run tests\n"
            "  previous_gate_ids: bbbbbbbbbbbb\n",
            encoding="utf-8",
        )
        self.state.reports_dir.joinpath("recommendations.json").write_text(
            json.dumps([{"id": "rec-1", "kind": "pattern"}]),
            encoding="utf-8",
        )
        self.state.repo_state_dir.joinpath("suggestions.json").write_text(
            json.dumps({"suggestions": [{"recommendation_id": "s1", "title": "Try it"}]}),
            encoding="utf-8",
        )
        self._write_event_db()

        payload = dashboard_read_model.build_fastapi_payload(
            self.user_root,
            state=self.state,
            history_limit=5,
        )

        for key in ("generated_at", "personal_root", "latest", "history", "scoped_gates", "read_surface"):
            self.assertIn(key, payload)
        self.assertEqual(payload["scoped_gates"]["summary"]["project"], 1)
        self.assertEqual(
            payload["scoped_gates"]["rows"][0]["previous_gate_ids"],
            ["bbbbbbbbbbbb"],
        )
        surface = payload["read_surface"]
        self.assertEqual(surface["recommendations"][0]["id"], "rec-1")
        self.assertEqual(surface["suggestions"][0]["recommendation_id"], "s1")
        self.assertIn("diagnostics", surface)

    def test_fastapi_payload_without_state_has_no_project_read_surface(self) -> None:
        payload = dashboard_read_model.build_fastapi_payload(self.user_root, state=None, history_limit=5)

        self.assertIsNone(payload["read_surface"])
        self.assertEqual(payload["scoped_gates"]["summary"], {"total": 0, "user": 0, "project": 0})

    def test_stdlib_payload_preserves_current_keys_and_buckets(self) -> None:
        self.state.reports_dir.joinpath("recommendations.json").write_text(
            json.dumps([
                {"id": "a", "kind": "anomaly"},
                {"id": "p", "kind": "pattern"},
                {"id": "c", "kind": "event_correlation"},
            ]),
            encoding="utf-8",
        )
        self.state.repo_state_dir.joinpath("suggestions.json").write_text(
            json.dumps({"suggestions": [{"recommendation_id": "s1"}]}),
            encoding="utf-8",
        )

        payload = dashboard_read_model.build_stdlib_payload(self.state, user_root=self.user_root)

        for key in (
            "recommendations",
            "pending_patches",
            "anomalies",
            "patterns",
            "correlations",
            "apply_log",
            "gates_and_insights",
            "suggestions",
            "sections",
        ):
            self.assertIn(key, payload)
        self.assertEqual([row["id"] for row in payload["anomalies"]], ["a"])
        self.assertEqual(payload["suggestions"], [{"recommendation_id": "s1"}])

    def test_read_model_does_not_import_action_or_writer_modules(self) -> None:
        tree = ast.parse((BIN_DIR / "dashboard_read_model.py").read_text(encoding="utf-8"))
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)

        forbidden = {
            "dashboard.actions",
            "event_writer",
            "bin.event_writer",
            "alc_propose",
            "bin.alc_propose",
            "sqlite3",
        }
        self.assertFalse(imports & forbidden, imports & forbidden)

    def test_dashboard_adapters_delegate_payload_assembly_to_read_model(self) -> None:
        fastapi_adapter = _function_from(REPO_ROOT / "dashboard" / "__init__.py", "_build_dashboard_payload")
        static_adapter = _function_from(REPO_ROOT / "bin" / "render_dashboard", "build_dashboard_data")
        stdlib_adapter = _function_from(REPO_ROOT / "skills" / "alc-dashboard" / "server.py", "build_data_blob")

        self.assertIn("build_fastapi_payload", _called_names(fastapi_adapter))
        self.assertIn("build_static_payload", _called_names(static_adapter))
        self.assertIn("build_stdlib_payload", _called_names(stdlib_adapter))


if __name__ == "__main__":
    unittest.main()
