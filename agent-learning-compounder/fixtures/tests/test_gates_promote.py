"""Tests for P4-A: gates_promote writes shared registry records."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMOTE = REPO_ROOT / "bin" / "gates_promote"
EXPORT_GATES = REPO_ROOT / "bin" / "export_gates"


SAMPLE_REPORT_CONTENT = """\
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


class GatesPromote(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.report = Path(self.tmp.name) / "report.md"
        self.report.write_text(SAMPLE_REPORT_CONTENT)
        self.gates_md = Path(self.tmp.name) / "approved-gates.md"
        self.shared = Path(self.tmp.name) / "shared"
        # Export so we get an actual gate_id stamped
        subprocess.run(
            [str(EXPORT_GATES), "--report", str(self.report),
             "--output", str(self.gates_md)],
            check=True,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _gate_id_for_category(self, category: str) -> str:
        """Return the gate_id of the first gate whose gate_category matches."""
        import re
        text = self.gates_md.read_text()
        # Each gate block contains gate_id and gate_category lines close together.
        pattern = re.compile(
            r"gate_id:\s*([a-f0-9]{12})\s*\n\s*gate_category:\s*(\S+)",
            re.M,
        )
        for match in pattern.finditer(text):
            if match.group(2) == category:
                return match.group(1)
        self.fail(f"no gate_id found for category {category} in:\n{text}")

    def _any_gate_id(self) -> str:
        import re
        text = self.gates_md.read_text()
        m = re.search(r"gate_id:\s*([a-f0-9]{12})", text)
        self.assertIsNotNone(m, f"no gate_id found in:\n{text}")
        return m.group(1)

    def test_promote_writes_shared_record(self):
        gate_id = self._gate_id_for_category("docs-check")
        subprocess.run([
            str(PROMOTE),
            "--gates", str(self.gates_md),
            "--gate-id", gate_id,
            "--origin-repo", "repo-abc",
            "--shared-root", str(self.shared),
        ], check=True)
        record_path = self.shared / "gates" / f"{gate_id}.json"
        self.assertTrue(record_path.exists(), f"expected record at {record_path}")
        data = json.loads(record_path.read_text())
        self.assertEqual(data["origin_repo"], "repo-abc")
        self.assertEqual(data["domain"], "cloudflare")
        self.assertEqual(data["gate_id"], gate_id)
        self.assertEqual(data["gate_category"], "docs-check")
        self.assertIn("Re-read current Cloudflare docs", data["gate"])
        self.assertIn("promoted_at", data)

    def test_promote_refuses_unknown_gate(self):
        proc = subprocess.run([
            str(PROMOTE),
            "--gates", str(self.gates_md),
            "--gate-id", "ffffffffffff",
            "--origin-repo", "repo-abc",
            "--shared-root", str(self.shared),
        ], capture_output=True, text=True, check=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("not found", proc.stderr)

    def test_promote_with_note_persists_note(self):
        gate_id = self._any_gate_id()
        subprocess.run([
            str(PROMOTE),
            "--gates", str(self.gates_md),
            "--gate-id", gate_id,
            "--origin-repo", "repo-abc",
            "--shared-root", str(self.shared),
            "--note", "high impact in our cloudflare workflow",
        ], check=True)
        record_path = self.shared / "gates" / f"{gate_id}.json"
        data = json.loads(record_path.read_text())
        self.assertEqual(data["note"], "high impact in our cloudflare workflow")

    def test_promote_rejects_non_hex_gate_id_before_writing(self):
        malicious = "../../escape"
        gates = Path(self.tmp.name) / "malicious-gates.md"
        gates.write_text(
            "# Approved Agent Gates\n\n"
            "## gates\n\n"
            "- domain: tests\n"
            f"  gate_id: {malicious}\n"
            "  gate_category: validation-check\n"
            "  gate: Run validation.\n",
            encoding="utf-8",
        )
        proc = subprocess.run([
            str(PROMOTE),
            "--gates", str(gates),
            "--gate-id", malicious,
            "--origin-repo", "repo-abc",
            "--shared-root", str(self.shared),
        ], capture_output=True, text=True, check=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("12 lowercase hex", proc.stderr)
        self.assertFalse((Path(self.tmp.name) / "escape.json").exists())


class GatesPromoteInheritRoundTrip(unittest.TestCase):
    """Promote a gate from one repo's gates.md, inherit into another's gates.md,
    confirming the field names line up across the federation boundary."""

    def test_promote_then_inherit_round_trip(self):
        import re
        INHERIT = REPO_ROOT / "bin" / "gates_inherit"
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            report = tdp / "report.md"
            report.write_text(SAMPLE_REPORT_CONTENT)
            origin_gates = tdp / "origin-gates.md"
            shared = tdp / "shared"
            subprocess.run(
                [str(EXPORT_GATES), "--report", str(report),
                 "--output", str(origin_gates)],
                check=True,
            )
            m = re.search(r"gate_id:\s*([a-f0-9]{12})", origin_gates.read_text())
            gate_id = m.group(1)

            subprocess.run([
                str(PROMOTE),
                "--gates", str(origin_gates),
                "--gate-id", gate_id,
                "--origin-repo", "repo-A",
                "--shared-root", str(shared),
            ], check=True)

            target_gates = tdp / "target-gates.md"
            target_gates.write_text("# Approved Agent Gates\n\n")
            subprocess.run([
                str(INHERIT),
                "--shared-root", str(shared),
                "--target-gates", str(target_gates),
                "--gate-id", gate_id,
            ], check=True)

            text = target_gates.read_text()
            self.assertIn(f"gate_id: {gate_id}", text)
            self.assertIn(f"derived_from: repo-A:{gate_id}:", text)
            self.assertIn("gate_category: docs-check", text)

    def test_promote_then_inherit_preserves_level(self):
        """Non-default severity (level: 3) must round-trip through promote +
        inherit. Previously ``build_record`` silently dropped ``level``, so the
        inherited block came out without it and effectively reset to default."""
        import re
        INHERIT = REPO_ROOT / "bin" / "gates_inherit"
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            report = tdp / "report.md"
            report.write_text(SAMPLE_REPORT_CONTENT)
            origin_gates = tdp / "origin-gates.md"
            shared = tdp / "shared"
            subprocess.run(
                [str(EXPORT_GATES), "--report", str(report),
                 "--output", str(origin_gates)],
                check=True,
            )
            # Sanity-check that export emitted ``level: 3`` for our source block.
            origin_text = origin_gates.read_text()
            self.assertIn("level: 3", origin_text)
            m = re.search(r"gate_id:\s*([a-f0-9]{12})", origin_text)
            gate_id = m.group(1)

            subprocess.run([
                str(PROMOTE),
                "--gates", str(origin_gates),
                "--gate-id", gate_id,
                "--origin-repo", "repo-A",
                "--shared-root", str(shared),
            ], check=True)

            # The shared record itself must carry the level so other repos see it.
            record = json.loads(
                (shared / "gates" / f"{gate_id}.json").read_text(encoding="utf-8")
            )
            self.assertEqual(record.get("level"), "3")

            target_gates = tdp / "target-gates.md"
            target_gates.write_text("# Approved Agent Gates\n\n")
            subprocess.run([
                str(INHERIT),
                "--shared-root", str(shared),
                "--target-gates", str(target_gates),
                "--gate-id", gate_id,
            ], check=True)

            inherited = target_gates.read_text()
            # The inherited block must carry the level line back into YAML form.
            level_line = re.search(
                rf"gate_id:\s*{gate_id}.*?^\s*level:\s*3\s*$",
                inherited,
                re.DOTALL | re.MULTILINE,
            )
            self.assertIsNotNone(
                level_line,
                f"expected ``level: 3`` to appear in inherited block:\n{inherited}",
            )

    def test_promote_without_level_omits_field(self):
        """When the source block has no level (older gates), the shared record
        must omit the field entirely rather than inventing a default."""
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            gates = tdp / "no-level-gates.md"
            shared = tdp / "shared"
            gates.write_text(
                "# Approved Agent Gates\n\n"
                "## gates\n\n"
                "- domain: tests\n"
                "  gate_id: abcdef012345\n"
                "  gate_category: validation-check\n"
                "  gate: Run validation.\n",
                encoding="utf-8",
            )
            subprocess.run([
                str(PROMOTE),
                "--gates", str(gates),
                "--gate-id", "abcdef012345",
                "--origin-repo", "repo-abc",
                "--shared-root", str(shared),
            ], check=True)
            record = json.loads(
                (shared / "gates" / "abcdef012345.json").read_text(encoding="utf-8")
            )
            self.assertNotIn("level", record)


if __name__ == "__main__":
    unittest.main()
