"""Pure causal evidence policy shared by probe, hook, scorer, and refresh adapters."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
from typing import Any, Callable


PROBE_DECISION_LOAD = "load"
PROBE_DECISION_SKIP = "skip"
VALID_PROBE_DECISIONS = frozenset({PROBE_DECISION_LOAD, PROBE_DECISION_SKIP})
PROBE_COHORT_MIN_N = 5
RETIRE_CAUSAL_OK = ("causal_correlated_with_failure", "causal_no_signal")


def validate_probe_rate(rate: Any) -> float:
    """Validate the persisted probe rate and return it as a float."""
    if not isinstance(rate, (int, float)) or not (0.0 <= rate <= 1.0):
        raise ValueError(f"probe rate must be a number in [0.0, 1.0]; got {rate!r}")
    return float(rate)


def decide_probe(gate_id: str, session_id: str, rate: Any) -> str:
    """Return the frozen deterministic probe decision for a gate/session pair."""
    validated_rate = validate_probe_rate(rate)
    h = hashlib.sha256(f"{session_id}|{gate_id}".encode("utf-8")).hexdigest()
    bucket = int(h[:8], 16) % 10000
    return PROBE_DECISION_SKIP if bucket < int(validated_rate * 10000) else PROBE_DECISION_LOAD


def normalize_probe_decisions(
    raw: Any,
    *,
    max_entries: int,
    max_gate_id_len: int,
    normalize_text: Callable[[str, int], str | None] | None = None,
) -> list[dict[str, str]]:
    """Normalize bounded probe-decision entries.

    The caller owns hook-safety policy such as whether the field is accepted,
    exact caps, and secret-shaped text handling. This helper owns only the
    causal entry contract: a gate id plus a decision from the closed vocabulary.
    """
    if not isinstance(raw, list):
        return []

    def clean(value: str, limit: int) -> str | None:
        if normalize_text is None:
            return value
        return normalize_text(value, limit)

    coerced: list[dict[str, str]] = []
    for member in raw:
        if not isinstance(member, dict):
            continue
        gate_id_raw = member.get("gate_id")
        decision_raw = member.get("decision")
        if not isinstance(gate_id_raw, (str, int)):
            continue
        gate_id_text = str(gate_id_raw)
        if not gate_id_text or len(gate_id_text) > max_gate_id_len:
            continue
        gate_id_bounded = clean(gate_id_text, max_gate_id_len)
        if not gate_id_bounded:
            continue
        if not isinstance(decision_raw, str):
            continue
        decision_bounded = clean(decision_raw, 16)
        if decision_bounded not in VALID_PROBE_DECISIONS:
            continue
        coerced.append({"gate_id": gate_id_bounded, "decision": decision_bounded})
        if len(coerced) >= max_entries:
            break
    return coerced


def normalize_sessions(sessions: dict[str, Any], alias_map: dict[str, str]):
    if not alias_map:
        return sessions, {}
    normalized = {}
    contributing: dict[str, set[str]] = defaultdict(set)
    for cid, session in sessions.items():
        gates = set()
        for gid in session["gates"]:
            canonical = alias_map.get(gid, gid)
            gates.add(canonical)
            if canonical != gid:
                contributing[canonical].add(gid)
        probe_decisions = {}
        for gid, decision in session.get("probe_decisions", {}).items():
            canonical = alias_map.get(gid, gid)
            if canonical != gid:
                contributing[canonical].add(gid)
            existing = probe_decisions.get(canonical)
            if existing == PROBE_DECISION_LOAD or decision == PROBE_DECISION_LOAD:
                probe_decisions[canonical] = PROBE_DECISION_LOAD
            else:
                probe_decisions[canonical] = decision
        normalized[cid] = {
            "gates": gates,
            "outcome": session.get("outcome"),
            "probe_decisions": probe_decisions,
        }
    return normalized, {gid: sorted(values) for gid, values in contributing.items()}


def _rate(outcomes: list[str]) -> float | None:
    if not outcomes:
        return None
    return sum(1 for outcome in outcomes if outcome == "correction") / len(outcomes)


def evaluate_evidence(
    sessions: dict[str, Any],
    min_n: int = 10,
    alias_map: dict[str, str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Compute correlational and causal evidence rows per logical gate id."""
    alias_map = alias_map or {}
    sessions, contributing_aliases = normalize_sessions(sessions, alias_map)

    all_gate_ids = set()
    for session in sessions.values():
        all_gate_ids.update(session["gates"])
        all_gate_ids.update(session.get("probe_decisions", {}).keys())

    rows = []
    for gid in sorted(all_gate_ids):
        loaded_outcomes = [
            session["outcome"] for session in sessions.values()
            if gid in session["gates"] and session["outcome"]
        ]
        absent_outcomes = [
            session["outcome"] for session in sessions.values()
            if gid not in session["gates"] and session["outcome"]
        ]
        probe_loaded_outcomes = [
            session["outcome"] for session in sessions.values()
            if session.get("probe_decisions", {}).get(gid) == PROBE_DECISION_LOAD
            and session["outcome"]
        ]
        probe_skipped_outcomes = [
            session["outcome"] for session in sessions.values()
            if session.get("probe_decisions", {}).get(gid) == PROBE_DECISION_SKIP
            and session["outcome"]
        ]

        loaded_rate = _rate(loaded_outcomes)
        absent_rate = _rate(absent_outcomes)
        n_loaded = len(loaded_outcomes)
        n_absent = len(absent_outcomes)

        if n_loaded < min_n or n_absent < min_n or loaded_rate is None or absent_rate is None:
            label = "needs_review"
            delta = None
        else:
            delta = absent_rate - loaded_rate
            if delta >= 0.20:
                label = "correlated_with_success"
            elif delta <= -0.10:
                label = "correlated_with_failure"
            else:
                label = "no_signal"

        probe_loaded_rate = _rate(probe_loaded_outcomes)
        probe_skipped_rate = _rate(probe_skipped_outcomes)
        n_probe_loaded = len(probe_loaded_outcomes)
        n_probe_skipped = len(probe_skipped_outcomes)

        if (
            n_probe_loaded < PROBE_COHORT_MIN_N
            or n_probe_skipped < PROBE_COHORT_MIN_N
            or probe_loaded_rate is None
            or probe_skipped_rate is None
        ):
            causal_signal = "needs_review"
        else:
            probe_delta = probe_skipped_rate - probe_loaded_rate
            if probe_delta >= 0.20:
                causal_signal = "causal_correlated_with_success"
            elif probe_delta <= -0.10:
                causal_signal = "causal_correlated_with_failure"
            else:
                causal_signal = "causal_no_signal"

        row = {
            "gate_id": gid,
            "n_loaded": n_loaded,
            "n_absent": n_absent,
            "correction_rate_loaded": loaded_rate,
            "correction_rate_absent": absent_rate,
            "delta": delta,
            "label": label,
            "causal_signal": causal_signal,
        }
        if contributing_aliases.get(gid):
            row["contributing_previous_gate_ids"] = contributing_aliases[gid]
        rows.append(row)
    return {"gates": rows}


@dataclass(frozen=True)
class RetirementCandidate:
    kind: str
    gate_id: str
    evidence: dict[str, Any]
    derived_from: str | None = None

    @property
    def row_id_input(self) -> tuple[str, str]:
        return (self.gate_id, self.kind)


def candidate_evidence(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "n_loaded": row["n_loaded"],
        "n_absent": row["n_absent"],
        "delta": row["delta"],
        "label": row["label"],
        "causal_signal": row.get("causal_signal"),
        "contributing_previous_gate_ids": row.get("contributing_previous_gate_ids", []),
    }


def retirement_candidates(
    evidence_rows: list[dict[str, Any]],
    *,
    inherited: dict[str, str] | None = None,
    min_n_retire: int = 20,
    allowed_causal_signals: tuple[str, ...] = RETIRE_CAUSAL_OK,
) -> list[RetirementCandidate]:
    """Return disruptive-action candidates from normalized evidence rows."""
    inherited_map = inherited or {}
    candidates: list[RetirementCandidate] = []
    for row in evidence_rows:
        if row["label"] not in ("correlated_with_failure", "no_signal"):
            continue
        if row["n_loaded"] < min_n_retire or row["n_absent"] < min_n_retire:
            continue
        if row.get("causal_signal") not in allowed_causal_signals:
            continue
        gate_id = row["gate_id"]
        if gate_id in inherited_map:
            candidates.append(
                RetirementCandidate(
                    kind="inherited_gate_demote_candidate",
                    gate_id=gate_id,
                    derived_from=inherited_map[gate_id],
                    evidence=candidate_evidence(row),
                )
            )
        else:
            candidates.append(
                RetirementCandidate(
                    kind="gate_retirement_candidate",
                    gate_id=gate_id,
                    evidence=candidate_evidence(row),
                )
            )
    return candidates
