from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"

if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

import event_emit


class EventEmitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = tempfile.TemporaryDirectory()
        self.events_path = pathlib.Path(self.state.name) / "events.jsonl"
        self._saved_env = {
            "AGENT_LEARNING_STATE_DIR": os.environ.get("AGENT_LEARNING_STATE_DIR"),
            "AGENT_LEARNING_SKILL_DIR": os.environ.get("AGENT_LEARNING_SKILL_DIR"),
        }
        os.environ["AGENT_LEARNING_STATE_DIR"] = self.state.name

    def tearDown(self) -> None:
        self.state.cleanup()
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _run_event_emit(self, *args: str) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(BIN_DIR) + os.pathsep + env.get("PYTHONPATH", "")
        return subprocess.run(
            [sys.executable, str(BIN_DIR / "event_emit"), *args],
            cwd=str(REPO_ROOT),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def _read_events(self) -> list[dict]:
        if not self.events_path.is_file():
            return []
        rows: list[dict] = []
        for line in self.events_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
        return rows

    def test_event_emit_cli_writes_valid_event(self) -> None:
        proc = self._run_event_emit("--kind", "distill_run", "--actor-name", "scheduled-distill")
        self.assertEqual(proc.returncode, 0, proc.stderr)

        rows = self._read_events()
        self.assertEqual(len(rows), 1)
        row = rows[-1]
        self.assertEqual(row["event"], "distill_run")
        self.assertEqual(row["actor"]["kind"], "background_agent")
        self.assertEqual(row["actor"]["name"], "scheduled-distill")
        self.assertEqual(row["source"], "background")
        self.assertIn("event_id", row)

    def test_event_emit_without_parent_is_root(self) -> None:
        proc = self._run_event_emit("--kind", "distill_run", "--actor-name", "scheduled-distill")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = self._read_events()
        self.assertTrue(rows)
        self.assertIsNone(rows[-1]["parent_event_id"])

    def test_event_emit_python_api(self) -> None:
        event_id = event_emit.event_emit(kind="x", actor_name="y")
        rows = self._read_events()
        self.assertTrue(any(row["event_id"] == event_id for row in rows))

    def _write_fake_skill_tooling(self, root: pathlib.Path) -> pathlib.Path:
        skill_dir = root / "skill"
        (skill_dir / "scripts").mkdir(parents=True)
        extract = skill_dir / "scripts" / "extract_sessions.py"
        distill = skill_dir / "scripts" / "distill_learning.py"
        extract.write_text(
            """#!/usr/bin/env python3\n"""
            "import argparse\n"
            "import pathlib\n\n"
            "def main() -> None:\n"
            "    parser = argparse.ArgumentParser()\n"
            "    parser.add_argument(\"--output\", required=True)\n"
            "    args, _ = parser.parse_known_args()\n"
            "    pathlib.Path(args.output).write_text(\"\", encoding=\"utf-8\")\n"
            "\n"
            "if __name__ == \"__main__\":\n"
            "    main()\n",
            encoding="utf-8",
        )
        distill.write_text(
            """#!/usr/bin/env python3\n"""
            "import argparse\n"
            "import pathlib\n"
            "import time\n\n"
            "def main() -> None:\n"
            "    parser = argparse.ArgumentParser()\n"
            "    parser.add_argument(\"--output\")\n"
            "    parser.parse_known_args()\n"
            "    time.sleep(0.15)\n"
            "    args, _ = parser.parse_known_args()\n"
            "    if args.output:\n"
            "        pathlib.Path(args.output).write_text(\"\", encoding=\"utf-8\")\n"
            "\n"
            "if __name__ == \"__main__\":\n"
            "    main()\n",
            encoding="utf-8",
        )
        extract.chmod(0o755)
        distill.chmod(0o755)

        skill_bin = skill_dir / "bin"
        skill_bin.mkdir(exist_ok=True)
        shutil.copy2(BIN_DIR / "event_emit", skill_bin / "event_emit")
        shutil.copy2(BIN_DIR / "event_emit.py", skill_bin / "event_emit.py")
        return skill_dir

    def test_wrapped_auto_distill_emits_start_end(self) -> None:
        with tempfile.TemporaryDirectory() as run_root:
            run_root_path = pathlib.Path(run_root)
            skill_dir = self._write_fake_skill_tooling(run_root_path)

            env = os.environ.copy()
            env["AGENT_LEARNING_STATE_DIR"] = self.state.name
            env["AGENT_LEARNING_SKILL_DIR"] = str(skill_dir)
            proc = subprocess.run(
                [str(BIN_DIR / "auto_distill_session")],
                cwd=str(run_root_path),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)

            deadline = time.monotonic() + 5.0
            events: list[dict] = []
            while time.monotonic() < deadline:
                events = self._read_events()
                kinds = {row["event"] for row in events}
                if kinds.issuperset({"distill_start", "distill_end"}):
                    break
                time.sleep(0.05)

            starts = [row for row in events if row["event"] == "distill_start"]
            ends = [row for row in events if row["event"] == "distill_end"]
            self.assertEqual(len(starts), 1, events)
            self.assertEqual(len(ends), 1, events)
            duration_ms = ends[0]["telemetry"]["duration_ms"]
            self.assertIsInstance(duration_ms, int)
            self.assertGreater(duration_ms, 0)
            self.assertLess(duration_ms, 5000)
