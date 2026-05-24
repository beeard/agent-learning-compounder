import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


def run_export(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "export_gates.py"), *map(str, args)],
        text=True,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


class GateRegistryTests(unittest.TestCase):
    def test_exports_gates_from_valid_report_without_quotes_or_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            report = tmp_path / "report.md"
            output = tmp_path / "gate-registry.md"
            report.write_text(
                "\n".join(
                    [
                        "# Agent Learning Report",
                        "## confirmed_current",
                        "- [confirmed_current] Validation source exists. source: scripts/validate_outputs.py",
                        "## memory_derived",
                        '- [memory_derived] domain: teams; evidence: 4 matching user lines; quote: "raw session evidence that must not export" source: corpus',
                        "## needs_verification",
                        "- [needs_verification] Teams tenant state may drift. verify: run live tenant check.",
                        "## agent_compensation",
                        "### domain: teams",
                        "- **level:** 3",
                        "- **evidence_summary:** repeated issue. matching_lines: 4",
                        "- **gates:**",
                        "  - category: live-check",
                        "    gate: Check the live tenant before proposing Teams policy.",
                        "### domain: quick3",
                        "- **level:** 4",
                        "- **evidence_summary:** repeated write incidents. matching_lines: 2",
                        "- **gates:**",
                        "  - category: readback",
                        "    gate: Run smoke plus readback after every Quick3 write.",
                        "## self_healing_loop",
                        "- failure_signal -> candidate_gate -> validation_status -> next_session_load. Source: corpus",
                    ]
                ),
                encoding="utf-8",
            )

            result = run_export("--report", report, "--output", output)

            self.assertEqual(result.returncode, 0, result.stderr)
            registry = output.read_text(encoding="utf-8")
            self.assertIn("generated_at:", registry)
            self.assertIn("date:", registry)
            self.assertIn(f"source_report: {report.resolve()}", registry)
            self.assertIn("domains: teams, quick3", registry)
            self.assertIn("live-check", registry)
            self.assertIn("Check the live tenant before proposing Teams policy.", registry)
            self.assertIn("readback", registry)
            self.assertIn("Run smoke plus readback after every Quick3 write.", registry)
            self.assertIn("- domain: teams", registry)
            self.assertIn("  gate_category: live-check", registry)
            self.assertIn("- domain: quick3", registry)
            self.assertIn("  gate_category: readback", registry)
            self.assertIn("  level: 3", registry)
            self.assertIn("  matching_lines: 4", registry)
            self.assertIn("  level: 4", registry)
            self.assertIn("  matching_lines: 2", registry)
            self.assertNotIn("quote:", registry)
            self.assertNotIn("raw session evidence", registry)
            self.assertNotIn("evidence_summary", registry)

    def test_max_domains_limits_exported_domains(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            report = tmp_path / "report.md"
            output = tmp_path / "gate-registry.md"
            report.write_text(
                "\n".join(
                    [
                        "# Agent Learning Report",
                        "## confirmed_current",
                        "- [confirmed_current] Source exists. source: AGENTS.md:1",
                        "## memory_derived",
                        "- [memory_derived] Prior report exists. origin: prior",
                        "## needs_verification",
                        "- [needs_verification] Runtime state may drift. verify: command",
                        "## agent_compensation",
                        "### domain: first",
                        "  - category: repo-gate",
                        "    gate: Run first gate.",
                        "### domain: second",
                        "  - category: live-check",
                        "    gate: Run second gate.",
                        "## self_healing_loop",
                        "- failure_signal -> candidate_gate -> validation_status -> next_session_load. Source: corpus",
                    ]
                ),
                encoding="utf-8",
            )

            result = run_export("--report", report, "--output", output, "--max-domains", "1")

            self.assertEqual(result.returncode, 0, result.stderr)
            registry = output.read_text(encoding="utf-8")
            self.assertIn("domains: first", registry)
            self.assertIn("Run first gate.", registry)
            self.assertNotIn("second", registry)
            self.assertNotIn("Run second gate.", registry)


if __name__ == "__main__":
    unittest.main()
