import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
COLLECT = REPO_ROOT / "bin" / "collect_hook_event"


class CollectHookEventSchemaV2(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.tmp.name)
        self.log_path = self.state_dir / "hook-events.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def _emit(self, payload):
        env = {**os.environ, "AGENT_LEARNING_STATE_DIR": str(self.state_dir)}
        proc = subprocess.run(
            [str(COLLECT), "--output", str(self.log_path)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return [json.loads(line) for line in self.log_path.read_text().splitlines()]

    def test_event_has_current_schema_version(self):
        rows = self._emit({"event": "PreToolUse", "tool": "Bash"})
        # SCHEMA_VERSION=4 since PR 4 (B1 fix); rows must carry the current
        # collector schema so EventV4.upgrade_from accepts them without the
        # legacy v3 `repo`-bears-/home/ workaround.
        self.assertEqual(rows[-1]["schema_version"], 4)

    def test_correlation_id_pass_through(self):
        rows = self._emit({"event": "PreToolUse", "tool": "Bash", "correlation_id": "abc-123"})
        self.assertEqual(rows[-1]["correlation_id"], "abc-123")

    def test_gate_loaded_ids_pass_through(self):
        rows = self._emit({
            "event": "InstructionsLoaded",
            "gate_loaded_ids": ["g_aa11", "g_bb22"],
        })
        self.assertEqual(rows[-1]["gate_loaded_ids"], ["g_aa11", "g_bb22"])

    def test_unknown_fields_dropped(self):
        rows = self._emit({"event": "PreToolUse", "random_field": "ignored"})
        self.assertNotIn("random_field", rows[-1])

    def test_secret_shaped_correlation_id_drops_field_not_row(self):
        # `sk_live_<...>` matches the stripe_secret pattern in scrub_secrets,
        # which the bounded() helper turns into a field-level drop. Without
        # the bounded() routing this would trip the whole-row reject and the
        # entire telemetry event (including schema_version + tool) would be
        # silently lost.
        rows = self._emit({
            "event": "PreToolUse",
            "tool": "Bash",
            "correlation_id": "sk_live_" + "a" * 30,
        })
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[-1]["schema_version"], 4)
        self.assertEqual(rows[-1].get("tool"), "Bash")
        self.assertNotIn("correlation_id", rows[-1])

    def test_oversize_gate_loaded_id_member_dropped(self):
        rows = self._emit({
            "event": "InstructionsLoaded",
            "gate_loaded_ids": ["g_ok", "x" * 200],
        })
        self.assertEqual(rows[-1]["gate_loaded_ids"], ["g_ok"])

    def test_agent_dispatch_fields_are_bounded_and_scrubbed(self):
        rows = self._emit({
            "event": "AgentDispatchStart",
            "agent_role": "builder",
            "agent_backend": "codex-exec",
            "agent_model": "gpt-5.3-codex-spark",
            "agent_effort": "low",
            "agent_sandbox": "workspace-write",
            "dispatch_id": "dispatch-1",
            "agent_write_scope": ["src/app.ts", "/etc/passwd"],
            "agent_branch": "wt/dispatch-1",
            "prompt": "raw prompt must not persist",
        })
        row = rows[-1]
        self.assertEqual(row["event"], "agent_dispatch_start")
        self.assertEqual(row["agent_role"], "builder")
        self.assertEqual(row["agent_backend"], "codex-exec")
        self.assertEqual(row["agent_model"], "gpt-5.3-codex-spark")
        self.assertEqual(row["agent_write_scope"][0], "src/app.ts")
        self.assertTrue(row["agent_write_scope"][1].startswith("<outside_repo:"))
        self.assertEqual(row["agent_branch"], "wt/dispatch-1")
        rendered = json.dumps(row, sort_keys=True)
        self.assertNotIn("raw prompt", rendered)

    def test_repo_config_can_disable_agent_model_and_scope_capture(self):
        repo = self.state_dir / "repo"
        repo.mkdir()
        (repo / ".agent-learning.json").write_text(json.dumps({
            "telemetry": {
                "agent_dispatch_model": False,
                "agent_dispatch_scope": False,
            },
        }))
        proc = subprocess.run(
            [str(COLLECT), "--repo", str(repo), "--output", str(self.log_path)],
            input=json.dumps({
                "event": "AgentDispatchStart",
                "agent_role": "builder",
                "agent_model": "gpt-5.3-codex-spark",
                "agent_write_scope": ["src/app.ts"],
                "agent_branch": "wt/dispatch-1",
            }),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        row = [json.loads(line) for line in self.log_path.read_text().splitlines()][-1]
        self.assertEqual(row["agent_role"], "builder")
        self.assertNotIn("agent_model", row)
        self.assertNotIn("agent_write_scope", row)
        self.assertNotIn("agent_branch", row)


if __name__ == "__main__":
    unittest.main()
