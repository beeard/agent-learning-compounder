"""Tests for P3B-B: probe_decision wiring through exports and effectiveness."""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPORT_GATES = REPO_ROOT / "bin" / "export_gates"
COLLECT = REPO_ROOT / "bin" / "collect_hook_event"


SAMPLE_REPORT = """\
# Agent Learning Report

## confirmed_current
- [confirmed_current] Source exists. source: AGENTS.md:1

## memory_derived
- [memory_derived] Prior report exists. origin: prior

## needs_verification
- [needs_verification] Runtime state may drift. verify: rerun validation.

## agent_compensation

### domain: cloudflare

- **level:** 3
- **gates:**
  - category: docs-check
    gate: Re-read current Cloudflare docs before changing wrangler config.

## self_healing_loop
- failure_signal -> candidate_gate -> validation_status -> next_session_load. source: corpus
"""


class ExportGatesProbeStatus(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.report = Path(self.tmp.name) / "report.md"
        self.report.write_text(SAMPLE_REPORT)
        self.output = Path(self.tmp.name) / "gates.md"
        self.probes = Path(self.tmp.name) / "probes.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_export_emits_probe_status_when_registered(self):
        # First, export gates without probes to learn the actual gate_id
        subprocess.run([str(EXPORT_GATES), "--report", str(self.report),
                        "--output", str(self.output)], check=True)
        text = self.output.read_text()
        gate_id = re.search(r"gate_id:\s*([a-f0-9]{12})", text).group(1)

        # Register a probe for that gate_id
        self.probes.write_text(json.dumps({gate_id: {"rate": 0.10}}))

        # Re-export with --probes
        subprocess.run([str(EXPORT_GATES), "--report", str(self.report),
                        "--output", str(self.output), "--probes", str(self.probes)], check=True)
        text = self.output.read_text()
        self.assertIn("probe_status: active", text)
        self.assertIn("probe_rate: 0.1", text)

    def test_export_omits_probe_status_when_no_probes_flag(self):
        subprocess.run([str(EXPORT_GATES), "--report", str(self.report),
                        "--output", str(self.output)], check=True)
        text = self.output.read_text()
        self.assertNotIn("probe_status", text)


class CollectHookEventProbeDecisions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / "hook-events.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def _emit(self, payload):
        proc = subprocess.run(
            [str(COLLECT), "--output", str(self.log)],
            input=json.dumps(payload), text=True, capture_output=True, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return [json.loads(l) for l in self.log.read_text().splitlines() if l]

    def test_probe_decisions_pass_through(self):
        rows = self._emit({
            "event": "InstructionsLoaded",
            "probe_decisions": [
                {"gate_id": "g_x", "decision": "load"},
                {"gate_id": "g_y", "decision": "skip"},
            ],
        })
        self.assertEqual(len(rows[-1]["probe_decisions"]), 2)
        self.assertEqual(rows[-1]["probe_decisions"][0]["decision"], "load")

    def test_invalid_probe_decisions_dropped(self):
        rows = self._emit({
            "event": "InstructionsLoaded",
            "probe_decisions": [
                {"gate_id": "g_ok", "decision": "load"},
                {"gate_id": "g_bad", "decision": "invalid_choice"},  # bad decision
                "not-a-dict",  # not a dict
                {"decision": "load"},  # missing gate_id
            ],
        })
        kept = rows[-1].get("probe_decisions", [])
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["gate_id"], "g_ok")

    def test_non_list_probe_decisions_dropped(self):
        rows = self._emit({
            "event": "InstructionsLoaded",
            "probe_decisions": "not-a-list",
        })
        self.assertNotIn("probe_decisions", rows[-1])


if __name__ == "__main__":
    unittest.main()
