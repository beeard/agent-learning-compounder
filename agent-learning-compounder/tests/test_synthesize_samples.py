import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import synthesize_samples


class SynthesizeSamplesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.corpus = Path(self.temp.name)
        self.output = Path(self.temp.name) / "samples.json"

    def tearDown(self):
        self.temp.cleanup()
        try:
            sys.path.remove(str(BIN))
        except ValueError:
            pass

    def run_with_mock(self, insights_fixture, adapter_output, *, args=None):
        def run_node_command(command, stdout_path=None):
            joined = " ".join(command)
            if "claude-insights-extracted.mjs" in joined:
                return subprocess.CompletedProcess(command, 0, stdout=json.dumps(insights_fixture), stderr="")

            if "alc-session-metrics-adapter.mjs" in joined:
                if stdout_path is not None:
                    stdout_path.write_text(json.dumps(adapter_output), encoding="utf-8")
                    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
                raise AssertionError("adapter command expected samples output path")

            raise AssertionError(f"Unexpected node command: {joined}")

        if args is None:
            args = ["--output", str(self.output), "--corpus", str(self.corpus)]
        with mock.patch.object(synthesize_samples, "run_node_command", side_effect=run_node_command):
            return synthesize_samples.main(args)

    def read_output(self):
        return json.loads(self.output.read_text(encoding="utf-8"))

    def test_basic_synthesis_from_adapter_output(self):
        insights = {
            "sessions": [
                {"session_id": "s1", "input_tokens": 10, "output_tokens": 20},
                {"session_id": "s2", "input_tokens": 5, "output_tokens": 8},
            ],
            "aggregate": {},
        }
        payload = {
            "metrics": [
                {
                    "session_ref": "s1",
                    "duration_minutes": 3,
                    "input_tokens": 10,
                    "output_tokens": 20,
                },
                {
                    "session_ref": "s2",
                    "duration_minutes": 7,
                    "input_tokens": 5,
                    "output_tokens": 8,
                },
            ],
        }

        ret = self.run_with_mock(insights, payload)
        self.assertEqual(ret, 0)

        rows = self.read_output()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["duration_minutes"], 3)
        self.assertEqual(rows[0]["input_tokens"], 10)
        self.assertEqual(rows[1]["output_tokens"], 8)

    def test_empty_input_produces_empty_array_not_crash(self):
        insights = {"sessions": [], "aggregate": {}}
        payload = {"metrics": []}

        ret = self.run_with_mock(insights, payload)
        self.assertEqual(ret, 0)

        rows = self.read_output()
        self.assertEqual(rows, [])

    def test_secrets_in_input_scrubbed_from_output(self):
        insights = {
            "sessions": [
                {
                    "session_id": "s1",
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "agent_model": "claude-opus-4-7",
                }
            ],
            "aggregate": {},
        }
        payload = {
            "metrics": [
                {
                    "session_ref": "s1",
                    "duration_minutes": 1,
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "note": "this includes sk-fake-test-key-abcdef",
                }
            ]
        }
        ret = self.run_with_mock(insights, payload)
        self.assertEqual(ret, 0)

        raw = self.output.read_text(encoding="utf-8")
        self.assertNotIn("sk-fake-test-key-abcdef", raw)

    def test_absolute_paths_relativized(self):
        insights = {
            "sessions": [
                {
                    "session_id": "s1",
                    "project_path": "/home/tth/secrets.txt",
                    "input_tokens": 10,
                    "output_tokens": 1,
                }
            ],
            "aggregate": {},
        }
        payload = {
            "metrics": [
                {
                    "session_ref": "s1",
                    "duration_minutes": 1,
                    "input_tokens": 10,
                    "output_tokens": 1,
                }
            ]
        }

        ret = self.run_with_mock(insights, payload)
        self.assertEqual(ret, 0)

        serialized = self.output.read_text(encoding="utf-8")
        self.assertNotIn("/home/", serialized)

    def test_cost_computed_for_opus(self):
        insights = {
            "sessions": [
                {
                    "session_id": "opus-session",
                    "agent_model": "claude-opus-4-7",
                    "input_tokens": 1_000_000,
                    "output_tokens": 1_000_000,
                }
            ],
            "aggregate": {},
        }
        payload = {
            "metrics": [
                {
                    "session_ref": "opus-session",
                    "duration_minutes": 1,
                    "input_tokens": 1_000_000,
                    "output_tokens": 1_000_000,
                }
            ]
        }

        ret = self.run_with_mock(insights, payload)
        self.assertEqual(ret, 0)

        row = self.read_output()[0]
        self.assertAlmostEqual(row["cost_usd"], 90.0, delta=0.01)

    def test_cost_falls_back_to_opus_for_unknown_model(self):
        insights = {
            "sessions": [
                {
                    "session_id": "unknown-model",
                    "agent_model": "claude-banana-9x",
                    "input_tokens": 1_000_000,
                    "output_tokens": 1_000_000,
                }
            ],
            "aggregate": {},
        }
        payload = {
            "metrics": [
                {
                    "session_ref": "unknown-model",
                    "duration_minutes": 1,
                    "input_tokens": 1_000_000,
                    "output_tokens": 1_000_000,
                }
            ]
        }

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            ret = self.run_with_mock(insights, payload)
        self.assertEqual(ret, 0)

        row = self.read_output()[0]
        self.assertAlmostEqual(row["cost_usd"], 90.0, delta=0.01)
        self.assertIn("unknown model", stderr.getvalue().lower())


if __name__ == "__main__":
    unittest.main()
