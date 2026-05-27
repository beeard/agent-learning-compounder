from __future__ import annotations

import ast
import json
import os
import pathlib
import sqlite3
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

import collect_hook_event
import refresh_learning_state
import refresh_run
from state_handle import StateHandle


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
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{path} has no function named {name}")


class RefreshRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self._tmp.name) / "repo"
        self.repo.mkdir()
        self._saved_env = {
            key: os.environ.pop(key, None)
            for key in (
                "AGENT_LEARNING_STATE_DIR",
                "AGENT_LEARNING_USER",
                "AGENT_LEARNING_PERSONAL",
            )
        }

    def tearDown(self) -> None:
        for key, value in self._saved_env.items():
            if value is not None:
                os.environ[key] = value
        self._tmp.cleanup()

    def _state(self) -> StateHandle:
        state = StateHandle.for_repo(self.repo)
        state.repo_state_dir.mkdir(parents=True, exist_ok=True)
        return state

    def _sqlite_rows(self) -> list[sqlite3.Row]:
        state = self._state()
        with sqlite3.connect(state.events_sqlite) as conn:
            conn.row_factory = sqlite3.Row
            return list(conn.execute("SELECT event, session_id FROM events ORDER BY ts, event"))

    def test_invalid_profile_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "profile must be one of"):
            refresh_run.run(self.repo, profile="later")

    def test_warm_refresh_preserves_writer_rows_and_appends_hook_rows(self) -> None:
        state = self._state()
        writer_row = {
            "event_id": "writer-row",
            "ts": "2026-05-27T12:00:00+00:00",
            "event": "writer_event",
            "schema_version": 4,
            "actor": {"kind": "background_agent", "name": "writer"},
            "telemetry": {},
            "correlation_chain": [],
            "session_id": "writer-session",
        }
        state.events_jsonl.write_text(json.dumps(writer_row) + "\n", encoding="utf-8")
        hook_row = collect_hook_event.normalize_event(
            {
                "event": "PreToolUse",
                "tool": "Bash",
                "session_id": "hook-session",
                "ts": "2026-05-27T12:01:00+00:00",
            },
            self.repo,
        )
        (state.repo_state_dir / "hook-events.jsonl").write_text(
            json.dumps(hook_row) + "\n",
            encoding="utf-8",
        )

        result = refresh_run.run_warm(self.repo)

        lines = [json.loads(line) for line in state.events_jsonl.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(lines[0]["event"], "writer_event")
        self.assertEqual(lines[1]["event"], "pre_tool_use")
        self.assertEqual(result["profile"], "warm")
        self.assertEqual(result["hook_rows_appended"], 1)
        self.assertGreaterEqual(result["events_indexed"], 2)
        sessions = {row["session_id"] for row in self._sqlite_rows()}
        self.assertIn("writer-session", sessions)
        self.assertIn("hook-session", sessions)

    def test_warm_refresh_is_incremental_for_hook_replay(self) -> None:
        state = self._state()
        hook_row = collect_hook_event.normalize_event(
            {
                "event": "PreToolUse",
                "tool": "Bash",
                "session_id": "hook-session",
                "ts": "2026-05-27T12:01:00+00:00",
            },
            self.repo,
        )
        (state.repo_state_dir / "hook-events.jsonl").write_text(
            json.dumps(hook_row) + "\n",
            encoding="utf-8",
        )

        first = refresh_run.run_warm(self.repo)
        second = refresh_run.run_warm(self.repo)

        self.assertEqual(first["hook_rows_appended"], 1)
        self.assertEqual(second["hook_rows_appended"], 0)
        self.assertEqual(len(state.events_jsonl.read_text(encoding="utf-8").splitlines()), 1)
        self.assertEqual(len(self._sqlite_rows()), 1)

    def test_warm_refresh_skips_malformed_hook_rows(self) -> None:
        state = self._state()
        hook_row = collect_hook_event.normalize_event(
            {
                "event": "PostToolUse",
                "tool": "Bash",
                "session_id": "valid-session",
                "ts": "2026-05-27T12:02:00+00:00",
            },
            self.repo,
        )
        (state.repo_state_dir / "hook-events.jsonl").write_text(
            "not-json\n" + json.dumps(hook_row) + "\n",
            encoding="utf-8",
        )

        result = refresh_run.run_warm(self.repo)

        self.assertEqual(result["hook_rows_skipped"], 1)
        self.assertEqual(result["hook_rows_appended"], 1)
        sessions = {row["session_id"] for row in self._sqlite_rows()}
        self.assertIn("valid-session", sessions)

    def test_warm_refresh_refuses_symlinked_events_jsonl(self) -> None:
        state = self._state()
        target = pathlib.Path(self._tmp.name) / "outside-events.jsonl"
        target.write_text("", encoding="utf-8")
        state.events_jsonl.symlink_to(target)
        hook_row = collect_hook_event.normalize_event(
            {
                "event": "PreToolUse",
                "tool": "Bash",
                "session_id": "symlink-session",
                "ts": "2026-05-27T12:03:00+00:00",
            },
            self.repo,
        )
        (state.repo_state_dir / "hook-events.jsonl").write_text(
            json.dumps(hook_row) + "\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "symlink"):
            refresh_run.run_warm(self.repo)

    def test_warm_refresh_propagates_index_schema_errors(self) -> None:
        state = self._state()
        with sqlite3.connect(state.events_sqlite) as conn:
            conn.execute("CREATE TABLE events_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            conn.execute(
                "INSERT INTO events_meta(key, value) VALUES ('schema_version', '99')"
            )
            conn.commit()
        state.events_jsonl.write_text(
            json.dumps(
                {
                    "event_id": "schema-mismatch-row",
                    "ts": "2026-05-27T12:00:00+00:00",
                    "event": "schema_mismatch",
                    "schema_version": 4,
                    "actor": {"kind": "background_agent", "name": "writer"},
                    "telemetry": {},
                    "correlation_chain": [],
                }
            )
            + "\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(RuntimeError, "schema mismatch"):
            refresh_run.run_warm(self.repo)

    def test_refresh_learning_state_adapter_returns_compatibility_keys(self) -> None:
        state = self._state()
        result = refresh_learning_state.refresh(self.repo, state_dir=state.state_root)

        self.assertEqual(result["profile"], "full")
        for key in (
            "repo",
            "repo_state_dir",
            "event_log",
            "event_log_present",
            "events_indexed",
            "queued_candidates",
            "suppressed_needs_review",
            "suppressed_redacted",
            "dedup_removed",
            "retirement_candidates_queued",
            "inherited_demote_candidates_queued",
            "domain_rule_candidates_queued",
            "touched",
            "stages",
        ):
            self.assertIn(key, result)

    def test_refresh_adapters_delegate_to_refresh_run(self) -> None:
        refresh_adapter = _function_from(REPO_ROOT / "bin" / "refresh_learning_state", "refresh")
        bootstrap_adapter = _function_from(REPO_ROOT / "bin" / "alc_bootstrap_pipeline", "run")

        self.assertIn("run_full", _called_names(refresh_adapter))
        self.assertIn("run_warm", _called_names(bootstrap_adapter))


if __name__ == "__main__":
    unittest.main()
