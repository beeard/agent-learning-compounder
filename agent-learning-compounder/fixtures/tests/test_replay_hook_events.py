"""Tests for P1-B: replay_hook_events cross-schema log migration."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
REPLAY = REPO_ROOT / "bin" / "replay_hook_events"


class ReplayHookEvents(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.input_path = Path(self.tmp.name) / "in.jsonl"
        self.output_path = Path(self.tmp.name) / "out.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, rows):
        self.input_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    def _run(self, *args):
        proc = subprocess.run(
            [str(REPLAY), "--input", str(self.input_path), "--output", str(self.output_path), *args],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return [json.loads(line) for line in self.output_path.read_text().splitlines() if line]

    def test_v1_row_upgrades_to_v2(self):
        self._write([{"ts": "2026-01-01T00:00:00Z", "event": "PreToolUse", "tool": "Bash"}])
        rows = self._run()
        self.assertEqual(rows[0]["schema_version"], 2)
        # normalize_event snake-cases event names (matches v2 collector convention).
        self.assertEqual(rows[0]["event"], "pre_tool_use")

    def test_v2_row_passes_through(self):
        self._write([{
            "ts": "2026-01-01T00:00:00Z", "event": "PreToolUse",
            "tool": "Bash", "schema_version": 2, "correlation_id": "c1",
        }])
        rows = self._run()
        self.assertEqual(rows[0]["correlation_id"], "c1")
        self.assertEqual(len(rows), 1)

    def test_malformed_row_skipped_not_crashed(self):
        self.input_path.write_text(
            json.dumps({"event": "PreToolUse"}) + "\n"
            + "not-json\n"
            + json.dumps({"event": "PostToolUse"}) + "\n"
        )
        rows = self._run("--skip-malformed")
        self.assertEqual(len(rows), 2)

    def test_dry_run_writes_nothing(self):
        self._write([{"event": "PreToolUse"}])
        proc = subprocess.run(
            [str(REPLAY), "--input", str(self.input_path), "--output", str(self.output_path), "--dry-run"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertFalse(self.output_path.exists())
        self.assertIn("would_write_rows=1", proc.stdout)

    def test_v2_row_preserves_original_ts(self):
        self._write([{
            "ts": "2020-01-01T00:00:00Z",
            "event": "PreToolUse",
            "tool": "Bash",
            "schema_version": 2,
        }])
        rows = self._run()
        self.assertEqual(rows[0]["ts"], "2020-01-01T00:00:00Z")

    def test_v1_row_without_ts_gets_one_stamped(self):
        self._write([{"event": "PreToolUse", "tool": "Bash"}])
        rows = self._run()
        self.assertIn("ts", rows[0])  # normalize_event filled it in


if __name__ == "__main__":
    unittest.main()
