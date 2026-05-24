"""Tests for P2B-B: per-gate effectiveness scoring."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL = REPO_ROOT / "bin" / "evaluate_gate_effectiveness"
FIXTURE = REPO_ROOT / "fixtures" / "eval-fixtures" / "gate_effectiveness_events.jsonl"


class EvaluateGateEffectiveness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.output = Path(self.tmp.name) / "effectiveness.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *args):
        proc = subprocess.run(
            [str(EVAL), "--events", str(FIXTURE), "--output", str(self.output), *args],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(self.output.read_text())

    def test_emits_one_row_per_seen_gate(self):
        result = self._run()
        gate_ids = {row["gate_id"] for row in result["gates"]}
        self.assertIn("g_aaa111", gate_ids)
        self.assertIn("g_bbb222", gate_ids)

    def test_labels_correlated_with_success(self):
        result = self._run()
        row = next(r for r in result["gates"] if r["gate_id"] == "g_aaa111")
        self.assertEqual(row["label"], "correlated_with_success")
        self.assertGreaterEqual(row["delta"], 0.20)

    def test_labels_correlated_with_failure(self):
        result = self._run()
        row = next(r for r in result["gates"] if r["gate_id"] == "g_bbb222")
        self.assertEqual(row["label"], "correlated_with_failure")
        self.assertLessEqual(row["delta"], -0.10)

    def test_min_n_gates_needs_review(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
            fh.write(json.dumps({
                "schema_version": 2, "event": "instructions_loaded",
                "correlation_id": "x1", "gate_loaded_ids": ["g_solo"]
            }) + "\n")
            fh.write(json.dumps({
                "schema_version": 2, "event": "session_end",
                "correlation_id": "x1", "outcome": "clean"
            }) + "\n")
            path = fh.name
        proc = subprocess.run(
            [str(EVAL), "--events", path, "--output", str(self.output), "--min-n", "10"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(self.output.read_text())
        row = next((r for r in result["gates"] if r["gate_id"] == "g_solo"), None)
        self.assertIsNotNone(row)
        self.assertEqual(row["label"], "needs_review")


if __name__ == "__main__":
    unittest.main()
