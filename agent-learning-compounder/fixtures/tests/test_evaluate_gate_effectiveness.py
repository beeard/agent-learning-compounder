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

    def test_probe_cohort_emits_causal_signal(self):
        result = self._run()
        row = next(r for r in result["gates"] if r["gate_id"] == "g_aaa111")
        self.assertIn("causal_signal", row)
        self.assertEqual(row["causal_signal"], "causal_correlated_with_success")

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


class RefreshSurfacesRetirementCandidate(unittest.TestCase):
    """refresh_learning_state should append a gate_retirement_candidate row
    for any gate labeled correlated_with_failure or no_signal with n_loaded>=20."""

    def test_refresh_queues_retirement_for_failing_gate(self):
        import shutil
        import sys

        fixture_src = REPO_ROOT / "fixtures" / "eval-fixtures" / "mini-repo"
        seed = fixture_src / "seed"

        sys.path.insert(0, str(REPO_ROOT / "bin"))
        import state_paths  # type: ignore

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            shutil.copytree(fixture_src, repo, ignore=shutil.ignore_patterns("seed"))

            rid = state_paths.repo_id(repo)
            state_root = repo / ".agent-learning"
            state_dir = state_root / "repos" / rid
            state_dir.mkdir(parents=True, exist_ok=True)
            for name in ("config.json", "baseline.json", "domain-rules.active.json", "skill-map.json"):
                shutil.copy(seed / name, state_dir / name)
            # Start with an empty queue
            (state_dir / "improvement-queue.jsonl").write_text("", encoding="utf-8")
            # Seed the hook-events log with the failure cohort
            shutil.copy(seed / "hook-events-failure-cohort.jsonl", state_dir / "hook-events.jsonl")

            # State-root config (per P2A-B convention)
            shutil.copy(seed / "config.json", state_root / "config.json")

            proc = subprocess.run(
                [str(REPO_ROOT / "bin" / "refresh_learning_state"),
                 "--repo", str(repo),
                 "--state-dir", str(state_root)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)

            queue = state_dir / "improvement-queue.jsonl"
            rows = [json.loads(ln) for ln in queue.read_text().splitlines() if ln]
            kinds = {r.get("kind") for r in rows}
            self.assertIn("gate_retirement_candidate", kinds)

            # Verify the candidate references the failing gate_id
            retirement = next(r for r in rows if r.get("kind") == "gate_retirement_candidate")
            self.assertEqual(retirement["gate_id"], "g_failgate12c")
            self.assertEqual(retirement["evidence"]["label"], "correlated_with_failure")
            self.assertGreaterEqual(retirement["evidence"]["n_loaded"], 20)


if __name__ == "__main__":
    unittest.main()
