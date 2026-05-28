"""Focused policy tests for bin/causal_evidence.py.

The CLI and hook tests cover adapter compatibility. These tests pin the pure
causal evidence surface so probe, scoring, and retirement policy can move
without dragging file IO into each assertion.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "bin"))

import causal_evidence  # noqa: E402


class ProbeDecisionContract(unittest.TestCase):
    def test_decide_probe_matches_frozen_verdicts(self):
        cases = [
            ("session-abc", "2aed10be9612", 0.50, "load"),
            ("session-abc", "2aed10be9612", 0.70, "skip"),
            ("session-xyz", "2aed10be9612", 0.50, "skip"),
            ("session-xyz", "2aed10be9612", 0.10, "load"),
            ("session-1", "cafebabe1234", 0.50, "load"),
            ("session-1", "cafebabe1234", 0.90, "skip"),
        ]
        for session_id, gate_id, rate, expected in cases:
            with self.subTest(session_id=session_id, gate_id=gate_id, rate=rate):
                self.assertEqual(
                    causal_evidence.decide_probe(gate_id, session_id, rate),
                    expected,
                )

    def test_validate_probe_rate_rejects_invalid_values(self):
        for value in (2.0, -0.5, "high"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    causal_evidence.validate_probe_rate(value)


class ProbeDecisionNormalization(unittest.TestCase):
    def test_normalizes_only_valid_probe_decision_entries(self):
        got = causal_evidence.normalize_probe_decisions(
            [
                {"gate_id": "g_ok", "decision": "load"},
                {"gate_id": 42, "decision": "skip"},
                {"gate_id": "g_bad", "decision": "invalid"},
                {"decision": "load"},
                "not-a-dict",
            ],
            max_entries=64,
            max_gate_id_len=64,
        )
        self.assertEqual(
            got,
            [
                {"gate_id": "g_ok", "decision": "load"},
                {"gate_id": "42", "decision": "skip"},
            ],
        )

    def test_respects_entry_cap_and_gate_id_length(self):
        got = causal_evidence.normalize_probe_decisions(
            [
                {"gate_id": "g1", "decision": "load"},
                {"gate_id": "x" * 65, "decision": "skip"},
                {"gate_id": "g2", "decision": "skip"},
            ],
            max_entries=1,
            max_gate_id_len=64,
        )
        self.assertEqual(got, [{"gate_id": "g1", "decision": "load"}])


class EvidenceEvaluation(unittest.TestCase):
    def test_aliases_fold_loaded_gates_and_probe_decisions(self):
        sessions = {}
        for i in range(5):
            sessions[f"old-{i}"] = {
                "gates": {"oldgate"},
                "outcome": "correction",
                "probe_decisions": {"oldgate": "load"},
            }
            sessions[f"current-{i}"] = {
                "gates": {"currentgate"},
                "outcome": "correction",
                "probe_decisions": {"currentgate": "load"},
            }
        for i in range(10):
            sessions[f"absent-{i}"] = {
                "gates": set(),
                "outcome": "clean",
                "probe_decisions": {"oldgate": "skip"},
            }

        result = causal_evidence.evaluate_evidence(
            sessions,
            min_n=1,
            alias_map={"oldgate": "currentgate"},
        )

        self.assertEqual([row["gate_id"] for row in result["gates"]], ["currentgate"])
        row = result["gates"][0]
        self.assertEqual(row["n_loaded"], 10)
        self.assertEqual(row["contributing_previous_gate_ids"], ["oldgate"])
        self.assertEqual(row["causal_signal"], "causal_correlated_with_failure")

    def test_small_probe_cohorts_need_review(self):
        result = causal_evidence.evaluate_evidence(
            {
                "s1": {
                    "gates": {"gate-a"},
                    "outcome": "clean",
                    "probe_decisions": {"gate-a": "load"},
                }
            },
            min_n=1,
        )
        self.assertEqual(result["gates"][0]["causal_signal"], "needs_review")


class RetirementEligibility(unittest.TestCase):
    def test_requires_allowed_causal_signal(self):
        row = {
            "gate_id": "gate-a",
            "n_loaded": 20,
            "n_absent": 20,
            "delta": -0.2,
            "label": "correlated_with_failure",
            "causal_signal": "needs_review",
        }
        self.assertEqual(causal_evidence.retirement_candidates([row]), [])

    def test_returns_retire_and_demote_candidates(self):
        rows = [
            {
                "gate_id": "local",
                "n_loaded": 20,
                "n_absent": 20,
                "delta": -0.2,
                "label": "correlated_with_failure",
                "causal_signal": "causal_correlated_with_failure",
                "contributing_previous_gate_ids": ["old-local"],
            },
            {
                "gate_id": "inherited",
                "n_loaded": 20,
                "n_absent": 20,
                "delta": -0.2,
                "label": "no_signal",
                "causal_signal": "causal_no_signal",
            },
        ]
        got = causal_evidence.retirement_candidates(
            rows,
            inherited={"inherited": "repo-origin"},
        )
        self.assertEqual([candidate.kind for candidate in got], [
            "gate_retirement_candidate",
            "inherited_gate_demote_candidate",
        ])
        self.assertEqual(got[0].gate_id, "local")
        self.assertEqual(got[0].evidence["contributing_previous_gate_ids"], ["old-local"])
        self.assertEqual(got[1].gate_id, "inherited")
        self.assertEqual(got[1].derived_from, "repo-origin")


if __name__ == "__main__":
    unittest.main()
