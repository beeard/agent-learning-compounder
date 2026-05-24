"""Tests for P2B-A: export_gates stamps stable 12-char gate_id."""
from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
EXPORT_GATES = REPO_ROOT / "bin" / "export_gates"

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
  - category: live-check
    gate: Run deploy verification and quote one non-secret line.

## self_healing_loop
- failure_signal -> candidate_gate -> validation_status -> next_session_load. source: corpus
"""


class ExportGatesId(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.report = Path(self.tmp.name) / "report.md"
        self.report.write_text(SAMPLE_REPORT)
        self.output = Path(self.tmp.name) / "gates.md"

    def tearDown(self):
        self.tmp.cleanup()

    def test_each_gate_has_stable_id(self):
        subprocess.run(
            [str(EXPORT_GATES), "--report", str(self.report), "--output", str(self.output)],
            check=True,
        )
        text = self.output.read_text()
        ids = re.findall(r"gate_id:\s*([a-f0-9]{12})", text)
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 2)

    def test_ids_are_deterministic_across_runs(self):
        subprocess.run(
            [str(EXPORT_GATES), "--report", str(self.report), "--output", str(self.output)],
            check=True,
        )
        first = self.output.read_text()
        subprocess.run(
            [str(EXPORT_GATES), "--report", str(self.report), "--output", str(self.output)],
            check=True,
        )
        second = self.output.read_text()
        # Strip timestamp lines for body-only equality
        strip = lambda s: re.sub(r"generated_at:[^\n]+", "", s)
        self.assertEqual(strip(first), strip(second))

    def test_id_changes_when_gate_text_changes(self):
        subprocess.run(
            [str(EXPORT_GATES), "--report", str(self.report), "--output", str(self.output)],
            check=True,
        )
        first_ids = set(re.findall(r"gate_id:\s*([a-f0-9]{12})", self.output.read_text()))

        modified = SAMPLE_REPORT.replace("Re-read current Cloudflare docs", "Read fresh Cloudflare docs")
        self.report.write_text(modified)
        subprocess.run(
            [str(EXPORT_GATES), "--report", str(self.report), "--output", str(self.output)],
            check=True,
        )
        second_ids = set(re.findall(r"gate_id:\s*([a-f0-9]{12})", self.output.read_text()))

        # The unchanged live-check gate's ID should appear in both; the changed docs-check gate's ID should differ.
        self.assertEqual(len(first_ids & second_ids), 1)


if __name__ == "__main__":
    unittest.main()
