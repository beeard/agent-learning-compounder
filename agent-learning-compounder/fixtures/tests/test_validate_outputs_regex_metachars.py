"""Tests for B3: validate_outputs handles regex metachars in subject names."""

import os
import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


REPORT_TEMPLATE = """## confirmed_current
- [confirmed_current] {subject_line} source: notes.md

## memory_derived
- [memory_derived] note source: notes.md

## needs_verification
- [needs_verification] note verify: run check

## agent_compensation
note

## self_healing_loop
note
"""


class ValidateOutputsMetacharsTests(unittest.TestCase):
    def test_metachar_subject_names_do_not_crash(self):
        env = os.environ.copy()
        env["AGENT_LEARNING_SUBJECT_NAMES"] = "Foo.Bar,Q+R,(X)"

        with tempfile.TemporaryDirectory() as td:
            report = pathlib.Path(td) / "report.md"
            report.write_text(
                REPORT_TEMPLATE.format(subject_line="Foo.Bar shows weakness"),
                encoding="utf-8",
            )
            proc = subprocess.run(
                [sys.executable, str(SCRIPTS / "validate_outputs.py"), str(report)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                check=False,
            )
            # Validator must not crash with re.error.
            self.assertNotIn("re.error", proc.stderr)
            self.assertNotIn("Traceback", proc.stderr)
            # The literal "Foo.Bar shows weakness" should trigger the psych
            # flag and cause non-zero exit.
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("psychological or ability claim", proc.stderr)


if __name__ == "__main__":
    unittest.main()
