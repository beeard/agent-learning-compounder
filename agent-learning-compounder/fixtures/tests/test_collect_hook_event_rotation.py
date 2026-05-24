"""Tests for B2: collect_hook_event rotation + 0o600 permissions."""

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


class CollectHookEventRotationTests(unittest.TestCase):
    def test_rotation_and_chmod(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            # Tiny threshold to force rotation on first append.
            (tmp / ".agent-learning.json").write_text(
                json.dumps({"retention": {"max_hook_event_bytes": 10}}),
                encoding="utf-8",
            )
            output = tmp / "hook-events.jsonl"
            # Pre-existing log past threshold.
            output.write_text("x" * 50, encoding="utf-8")

            event = json.dumps({
                "event": "test",
                "runtime": "unit",
                "session_id": "s1",
            })

            proc = subprocess.run(
                [
                    sys.executable, str(SCRIPTS / "collect_hook_event.py"),
                    "--repo", str(tmp),
                    "--output", str(output),
                    "--event", event,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)

            # A .bak should exist after rotation.
            backups = list(tmp.glob("hook-events.jsonl.*.bak"))
            self.assertTrue(backups, msg=f"no .bak file found in {list(tmp.iterdir())}")

            # New file exists and is mode 0o600.
            self.assertTrue(output.exists())
            mode = output.stat().st_mode & 0o777
            self.assertEqual(mode, 0o600, msg=f"mode is {oct(mode)}")

    def test_missing_config_uses_default(self):
        """No .agent-learning.json => default 5MB cap, no rotation, no error."""
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            output = tmp / "hook-events.jsonl"
            event = json.dumps({"event": "test", "runtime": "unit"})
            proc = subprocess.run(
                [
                    sys.executable, str(SCRIPTS / "collect_hook_event.py"),
                    "--repo", str(tmp),
                    "--output", str(output),
                    "--event", event,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertTrue(output.exists())
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_rotation_reads_bootstrap_state_config(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            state = tmp / ".agent-learning"
            state.mkdir()
            (state / "config.json").write_text(
                json.dumps({"retention": {"max_hook_event_bytes": 10}}),
                encoding="utf-8",
            )
            (tmp / ".agent-learning.json").write_text(
                json.dumps({"state_dir": str(state)}),
                encoding="utf-8",
            )
            output = tmp / "hook-events.jsonl"
            output.write_text("x" * 50, encoding="utf-8")

            event = json.dumps({"event": "test", "runtime": "unit"})
            proc = subprocess.run(
                [
                    sys.executable, str(SCRIPTS / "collect_hook_event.py"),
                    "--repo", str(tmp),
                    "--event", event,
                    "--output", str(output),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            backups = list(tmp.glob("hook-events.jsonl.*.bak"))
            self.assertTrue(backups)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "x" * 50)
            self.assertFalse(output.read_text(encoding="utf-8").startswith("x" * 50))


if __name__ == "__main__":
    unittest.main()
