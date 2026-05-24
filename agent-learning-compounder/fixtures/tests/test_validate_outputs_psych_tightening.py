"""Tests for review7 polish: tightened psychological-claim regex.

The state-verb branch (is/er/are/was/were/has/have/had) now requires an
adjective_tail term to fire. Bare "user is X" for neutral X must NOT trip
the validator. Judgment verbs (lacks/shows/...) still fire on their own.
The dårlig diacritical form must match alongside the stripped darlig.
"""

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


def run_validate(subject_line: str) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as td:
        report = pathlib.Path(td) / "report.md"
        report.write_text(
            REPORT_TEMPLATE.format(subject_line=subject_line),
            encoding="utf-8",
        )
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "validate_outputs.py"), str(report)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )


class PsychTighteningTests(unittest.TestCase):
    def test_darlig_diacritical_matches(self):
        proc = run_validate("user is dårlig at architecture")
        self.assertIn("psychological or ability claim", proc.stderr)
        self.assertNotEqual(proc.returncode, 0)

    def test_darlig_stripped_still_matches(self):
        proc = run_validate("brukeren er darlig paa arkitektur")
        self.assertIn("psychological or ability claim", proc.stderr)
        self.assertNotEqual(proc.returncode, 0)

    def test_bare_state_verb_with_neutral_tail_does_not_fire(self):
        proc = run_validate("user is great at architecture")
        self.assertNotIn("psychological or ability claim", proc.stderr)

    def test_bare_state_verb_with_skills_noun_does_not_fire(self):
        proc = run_validate("user has skills in Postgres")
        self.assertNotIn("psychological or ability claim", proc.stderr)

    def test_state_verb_with_adjective_tail_still_fires(self):
        proc = run_validate("user is weak at architecture")
        self.assertIn("psychological or ability claim", proc.stderr)

    def test_judgment_verb_alone_still_fires(self):
        proc = run_validate("user lacks experience")
        self.assertIn("psychological or ability claim", proc.stderr)


if __name__ == "__main__":
    unittest.main()
