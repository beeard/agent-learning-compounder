"""Tests for gate alias normalization in effectiveness scoring."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL = REPO_ROOT / "bin" / "evaluate_gate_effectiveness"


def _event(event: str, cid: str, **extra) -> str:
    payload = {"schema_version": 2, "event": event, "correlation_id": cid}
    payload.update(extra)
    return json.dumps(payload) + "\n"


class GateAliasEffectiveness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.events = self.root / "events.jsonl"
        self.output = self.root / "effectiveness.json"
        self.gates = self.root / "latest-approved-gates.md"

    def tearDown(self):
        self.tmp.cleanup()

    def _write_alias_gates(self, *, cycle: bool = False) -> None:
        if cycle:
            self.gates.write_text(
                "- domain: repo\n"
                "  gate_id: cccccccccccc\n"
                "  gate_category: check\n"
                "  gate: current\n"
                "  previous_gate_ids: bbbbbbbbbbbb\n"
                "- domain: repo\n"
                "  gate_id: bbbbbbbbbbbb\n"
                "  gate_category: check\n"
                "  gate: old current\n",
                encoding="utf-8",
            )
            return
        self.gates.write_text(
            "- domain: repo\n"
            "  gate_id: cccccccccccc\n"
            "  gate_category: check\n"
            "  gate: current\n"
            "  previous_gate_ids: bbbbbbbbbbbb\n",
            encoding="utf-8",
        )

    def _write_mixed_events(self) -> None:
        lines: list[str] = []
        for i in range(5):
            cid = f"old-{i}"
            lines.append(_event(
                "instructions_loaded",
                cid,
                gate_loaded_ids=["bbbbbbbbbbbb"],
                probe_decisions=[{"gate_id": "bbbbbbbbbbbb", "decision": "load"}],
            ))
            lines.append(_event("session_end", cid, outcome="correction"))
        for i in range(5):
            cid = f"current-{i}"
            lines.append(_event(
                "instructions_loaded",
                cid,
                gate_loaded_ids=["cccccccccccc"],
                probe_decisions=[{"gate_id": "cccccccccccc", "decision": "load"}],
            ))
            lines.append(_event("session_end", cid, outcome="correction"))
        for i in range(10):
            cid = f"absent-{i}"
            lines.append(_event(
                "instructions_loaded",
                cid,
                gate_loaded_ids=[],
                probe_decisions=[{"gate_id": "bbbbbbbbbbbb", "decision": "skip"}],
            ))
            lines.append(_event("session_end", cid, outcome="clean"))
        self.events.write_text("".join(lines), encoding="utf-8")

    def test_evaluator_normalizes_old_and_current_ids_to_canonical(self):
        self._write_alias_gates()
        self._write_mixed_events()

        proc = subprocess.run(
            [
                str(EVAL),
                "--events", str(self.events),
                "--output", str(self.output),
                "--min-n", "1",
                "--gates", str(self.gates),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = json.loads(self.output.read_text())["gates"]
        self.assertEqual([row["gate_id"] for row in rows], ["cccccccccccc"])
        self.assertEqual(rows[0]["n_loaded"], 10)
        self.assertEqual(rows[0]["contributing_previous_gate_ids"], ["bbbbbbbbbbbb"])

    def test_evaluator_without_alias_map_keeps_existing_shape(self):
        self._write_mixed_events()

        proc = subprocess.run(
            [str(EVAL), "--events", str(self.events), "--output", str(self.output), "--min-n", "1"],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = json.loads(self.output.read_text())["gates"]
        self.assertEqual({row["gate_id"] for row in rows}, {"bbbbbbbbbbbb", "cccccccccccc"})
        self.assertNotIn("contributing_previous_gate_ids", rows[0])

    def test_evaluator_rejects_alias_cycle(self):
        self._write_alias_gates(cycle=True)
        self._write_mixed_events()

        proc = subprocess.run(
            [
                str(EVAL),
                "--events", str(self.events),
                "--output", str(self.output),
                "--gates", str(self.gates),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("alias", proc.stderr)

    def test_queue_rows_use_canonical_id_and_record_contributing_aliases(self):
        import sys

        sys.path.insert(0, str(REPO_ROOT / "bin"))
        import refresh_learning_state  # type: ignore

        self._write_mixed_events()
        queue = self.root / "queue.jsonl"

        retire_count, demote_count = refresh_learning_state._queue_retirement_candidates(
            queue,
            self.events,
            min_n_retire=1,
            inherited={},
            alias_map={"bbbbbbbbbbbb": "cccccccccccc"},
        )

        self.assertEqual((retire_count, demote_count), (1, 0))
        row = json.loads(queue.read_text().splitlines()[0])
        self.assertEqual(row["gate_id"], "cccccccccccc")
        self.assertEqual(row["evidence"]["contributing_previous_gate_ids"], ["bbbbbbbbbbbb"])


if __name__ == "__main__":
    unittest.main()
