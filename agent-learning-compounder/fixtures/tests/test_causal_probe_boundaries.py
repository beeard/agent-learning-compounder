"""Tests for A3 (rate validation in decide) + A4 (boundary warnings in
register) + a frozen-value pin for the decide() hash recipe.

A3 pre-fix: decide() never re-validated probes.json's rate, so a hand-
edited value of 2.0 silently made every session skip and -0.1 silently
made every session load. The cohort math was corrupted invisibly.

A4 pre-fix: register accepted rate=0.0 and rate=1.0 (both within the
[0,1] interval the existing check enforces), but those degenerate values
keep one cohort empty forever and causal_signal stays at needs_review
indefinitely. The operator got no warning that they had silently
disabled the causal analysis they were trying to enable.

Frozen value: decide(gate_id, session_id, rate) is a federation contract.
Changing input ordering, separator, slice width, or modulus would still
be deterministic and approximately rate-correct, but every in-flight
cohort assignment would flip on the rollout day. Pin a few known values
so any future recipe change has to be a deliberate (visible) edit.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CAUSAL_PROBE = REPO_ROOT / "bin" / "causal_probe"


class DecideFrozenRecipe(unittest.TestCase):
    """Three (session_id, gate_id, rate) inputs with their expected
    verdicts. Computed once against the canonical recipe:

        bucket = int(sha256(f"{session_id}|{gate_id}")[:8], 16) % 10000
        verdict = "skip" if bucket < int(rate * 10000) else "load"
    """
    FROZEN_CASES = [
        # (session_id, gate_id, rate, expected_verdict)
        # session-abc / 2aed... → bucket 6840
        ("session-abc", "2aed10be9612", 0.50, "load"),   # 6840 >= 5000 → load
        ("session-abc", "2aed10be9612", 0.70, "skip"),   # 6840 < 7000 → skip
        # session-xyz / 2aed... → bucket 2258
        ("session-xyz", "2aed10be9612", 0.50, "skip"),   # 2258 < 5000 → skip
        ("session-xyz", "2aed10be9612", 0.10, "load"),   # 2258 >= 1000 → load
        # session-1 / cafe... → bucket 8658
        ("session-1", "cafebabe1234", 0.50, "load"),     # 8658 >= 5000 → load
        ("session-1", "cafebabe1234", 0.90, "skip"),     # 8658 < 9000 → skip
    ]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.probes = Path(self.tmp.name) / "probes.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _run_decide(self, session_id: str, gate_id: str) -> str:
        proc = subprocess.run(
            [str(CAUSAL_PROBE), "--probes", str(self.probes),
             "decide", "--gate-id", gate_id, "--session-id", session_id],
            capture_output=True, text=True, check=True,
        )
        return proc.stdout.strip()

    def _register(self, gate_id: str, rate: float):
        subprocess.run(
            [str(CAUSAL_PROBE), "--probes", str(self.probes),
             "register", "--gate-id", gate_id, "--rate", str(rate)],
            check=True, capture_output=True,
        )

    def test_decide_matches_frozen_verdicts(self):
        for session_id, gate_id, rate, expected in self.FROZEN_CASES:
            with self.subTest(session_id=session_id, gate_id=gate_id, rate=rate):
                # Re-register with the new rate (overwrites the prior entry).
                self._register(gate_id, rate)
                got = self._run_decide(session_id, gate_id)
                self.assertEqual(
                    got, expected,
                    msg=(
                        f"frozen decide contract broke for "
                        f"({session_id}, {gate_id}, {rate}): expected "
                        f"{expected!r}, got {got!r}. If you changed the hash "
                        f"recipe in bin/causal_probe.decide intentionally, "
                        f"every in-flight cohort assignment has flipped; "
                        f"this test guards against accidental drift."
                    ),
                )


class DecideRejectsOutOfRangeRate(unittest.TestCase):
    """A3: a hand-edited probes.json with rate outside [0, 1] must surface
    as an explicit error from cmd_decide, not silently flip every session."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.probes = Path(self.tmp.name) / "probes.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _decide(self, gate_id: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(CAUSAL_PROBE), "--probes", str(self.probes),
             "decide", "--gate-id", gate_id, "--session-id", "s1"],
            capture_output=True, text=True, check=False,
        )

    def test_decide_rejects_rate_above_one(self):
        # Bypass cmd_register's validation by hand-writing the probes file.
        self.probes.write_text(json.dumps({"aaaaaaaaaaaa": {"rate": 2.0}}))
        proc = self._decide("aaaaaaaaaaaa")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("invalid probe entry", proc.stderr)
        self.assertIn("0.0", proc.stderr)
        self.assertIn("1.0", proc.stderr)

    def test_decide_rejects_negative_rate(self):
        self.probes.write_text(json.dumps({"aaaaaaaaaaaa": {"rate": -0.5}}))
        proc = self._decide("aaaaaaaaaaaa")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("invalid probe entry", proc.stderr)

    def test_decide_rejects_non_numeric_rate(self):
        self.probes.write_text(json.dumps({"aaaaaaaaaaaa": {"rate": "high"}}))
        proc = self._decide("aaaaaaaaaaaa")
        self.assertNotEqual(proc.returncode, 0)


class RegisterBoundaryWarnings(unittest.TestCase):
    """A4: rate=0.0 and rate=1.0 are technically valid (inside [0,1]) but
    silently disable the causal analysis. Register must still accept them
    but print a warning to stderr so the operator knows."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.probes = Path(self.tmp.name) / "probes.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _register(self, rate: float) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(CAUSAL_PROBE), "--probes", str(self.probes),
             "register", "--gate-id", "aaaaaaaaaaaa", "--rate", str(rate)],
            capture_output=True, text=True, check=False,
        )

    def test_rate_zero_warns_about_empty_skipped_cohort(self):
        proc = self._register(0.0)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("warning", proc.stderr.lower())
        self.assertIn("probe_skipped", proc.stderr)
        # Registration still landed.
        data = json.loads(self.probes.read_text())
        self.assertEqual(data["aaaaaaaaaaaa"]["rate"], 0.0)

    def test_rate_one_warns_about_empty_loaded_cohort(self):
        proc = self._register(1.0)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("warning", proc.stderr.lower())
        self.assertIn("probe_loaded", proc.stderr)

    def test_normal_rate_does_not_warn(self):
        proc = self._register(0.5)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertNotIn("warning", proc.stderr.lower())


if __name__ == "__main__":
    unittest.main()
