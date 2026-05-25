import json
import os
import pathlib
import subprocess
import tempfile
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
CORRELATE_EVENTS = REPO_ROOT / "bin" / "correlate_events"


class TestCorrelateEvents(unittest.TestCase):
    def setUp(self) -> None:
        self.state_dir = pathlib.Path(tempfile.mkdtemp())
        self.state_events = self.state_dir / "events.jsonl"

    def tearDown(self) -> None:
        if self.state_dir.exists():
            for child in self.state_dir.iterdir():
                if child.is_file():
                    child.unlink()
            self.state_dir.rmdir()

    def _run_correlator(self) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["AGENT_LEARNING_STATE_DIR"] = str(self.state_dir)
        result = subprocess.run(
            [str(CORRELATE_EVENTS), "--state-dir", str(self.state_dir)],
            cwd=str(REPO_ROOT),
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        return result

    def _write_events(self, rows: list[dict]) -> None:
        data = "\n".join(json.dumps(row) for row in rows)
        if data:
            data += "\n"
        self.state_events.write_text(data, encoding="utf-8")

    def _load_events(self) -> list[dict]:
        return [json.loads(line) for line in self.state_events.read_text(encoding="utf-8").splitlines() if line]

    def test_tool_use_pair_emits_duration(self):
        self._write_events([
            {
                "event_id": "evt-pre-1",
                "ts": "2026-01-01T00:00:00+00:00",
                "event": "PreToolUse",
                "schema_version": 4,
                "actor": {"kind": "main_agent", "name": "agent-main"},
                "telemetry": {"duration_ms": 0},
                "tool": "bash",
                "correlation_chain": [{"role": "session", "id": "s1"}],
            },
            {
                "event_id": "evt-post-1",
                "ts": "2026-01-01T00:00:01+00:00",
                "event": "PostToolUse",
                "schema_version": 4,
                "actor": {"kind": "main_agent", "name": "agent-main"},
                "telemetry": {"duration_ms": 2},
                "tool": "bash",
            },
        ])

        self._run_correlator()
        rows = self._load_events()
        pairs = [row for row in rows if row.get("event") == "tool_use_pair"]

        self.assertEqual(len(pairs), 1)
        pair = pairs[0]
        self.assertEqual(pair["parent_event_id"], "evt-pre-1")
        self.assertEqual(pair["telemetry"].get("duration_ms"), 1000)

    def test_subagent_start_without_end_warns(self):
        self._write_events([
            {
                "event_id": "evt-sub-start-1",
                "ts": "2026-01-01T00:00:00+00:00",
                "event": "subagent_start",
                "schema_version": 4,
                "actor": {
                    "kind": "subagent",
                    "name": "child",
                    "parent_actor_id": "parent-root",
                },
                "telemetry": {},
            },
        ])
        result = self._run_correlator()

        rows = self._load_events()
        runs = [row for row in rows if row.get("event") == "subagent_run"]
        self.assertEqual(len(runs), 0)
        self.assertIn("warn.subagent_start_without_end", result.stderr)

    def test_nested_subagent_chain_is_rolled_through(self):
        self._write_events([
            {
                "event_id": "evt-sub-parent-start",
                "ts": "2026-01-01T00:00:00+00:00",
                "event": "subagent_start",
                "schema_version": 4,
                "actor": {"kind": "subagent", "name": "parent", "parent_actor_id": "root-actor"},
                "telemetry": {},
                "correlation_chain": [{"role": "line", "id": "c1"}],
            },
            {
                "event_id": "evt-sub-parent-end",
                "ts": "2026-01-01T00:00:05+00:00",
                "event": "subagent_end",
                "schema_version": 4,
                "actor": {"kind": "subagent", "name": "parent", "parent_actor_id": "root-actor"},
                "telemetry": {},
            },
            {
                "event_id": "evt-sub-child-start",
                "ts": "2026-01-01T00:00:10+00:00",
                "event": "subagent_start",
                "schema_version": 4,
                "actor": {
                    "kind": "subagent",
                    "name": "child",
                    "parent_actor_id": "parent-actor",
                },
                "telemetry": {},
                "correlation_chain": [
                    {"role": "line", "id": "c1"},
                    {"role": "line", "id": "c2"},
                    {"role": "line", "id": "c3"},
                ],
            },
            {
                "event_id": "evt-sub-child-end",
                "ts": "2026-01-01T00:00:15+00:00",
                "event": "subagent_end",
                "schema_version": 4,
                "actor": {
                    "kind": "subagent",
                    "name": "child",
                    "parent_actor_id": "parent-actor",
                },
                "telemetry": {},
            },
        ])

        self._run_correlator()
        rows = self._load_events()
        runs = [row for row in rows if row.get("event") == "subagent_run"]
        child = next(row for row in runs if row.get("parent_event_id") == "evt-sub-child-start")

        self.assertGreaterEqual(len(child["correlation_chain"]), 4)
        self.assertEqual(child["actor"].get("parent_actor_id"), "parent-actor")

    def test_idempotent_rerun_does_not_duplicate_derived(self):
        self._write_events([
            {
                "event_id": "evt-pre-2",
                "ts": "2026-01-01T00:00:00+00:00",
                "event": "pre_tool_use",
                "schema_version": 4,
                "actor": {"kind": "main_agent", "name": "agent-main"},
                "telemetry": {},
                "tool": "bash",
            },
            {
                "event_id": "evt-post-2",
                "ts": "2026-01-01T00:00:00.500+00:00",
                "event": "post_tool_use",
                "schema_version": 4,
                "actor": {"kind": "main_agent", "name": "agent-main"},
                "telemetry": {},
                "tool": "bash",
            },
        ])

        self._run_correlator()
        first = self._load_events()
        count_first = len([row for row in first if row.get("event") == "tool_use_pair"])

        self._run_correlator()
        second = self._load_events()
        count_second = len([row for row in second if row.get("event") == "tool_use_pair"])

        self.assertEqual(count_first, 1)
        self.assertEqual(count_second, 1)
        self.assertEqual(len(second), len(first))


if __name__ == "__main__":
    unittest.main()
