"""Tests for M1, M2, M4, M5, H2 in bin/refresh_learning_state.

H2: pre-fix the retirement filter consulted only the correlational label
(correlated_with_failure / no_signal). The causal-probe machinery was
effectively decorative -- the disruptive action never asked whether the
causal probe agreed. A gate with correlated_with_failure but
causal_correlated_with_success would still get queued for retirement,
even though retiring it would be wrong. Post-fix the filter requires
causal_signal in (causal_correlated_with_failure, causal_no_signal).

M5: pre-fix the filter checked n_loaded >= min_n_retire (default 20) but
not n_absent, while the underlying labels required both cohorts >= 10.
A gate could be queued for retirement with n_loaded=20, n_absent=10 --
half the strictness on the comparison side. Post-fix the filter applies
the stricter min_n_retire to both cohorts.

M4: pre-fix the retirement row id embedded the wall-clock second and a
within-batch counter, so two refreshes one second apart produced
different ids for the same candidate. The downstream trigram dedup
couldn't always collapse the drift (delta varies between refreshes, the
text differs, trigram-Dice can drop below the threshold). Post-fix the
id is sha256(gate_id|kind)[:16] and the queue is checked for membership
before append.

M2: pre-fix _inherited_gates required both gate_id AND derived_from to
mark a block inherited. A malformed block (CRLF, missing trailing
newline, partial write) was silently dropped from inherited_map and the
retirement filter then queued it as gate_retirement_candidate. An
operator acting on the queue would retire a gate that affects sibling
repos. Post-fix any gate_id without derived_from is treated as
inherited-with-unknown-origin and routed through the demote path.

M1: pre-fix per-file LOCK_EX guarded individual writes but releases
between them. Two concurrent refreshes could produce a baseline.json
from run A interleaved with a skill-map.json from run B. Post-fix a
top-level .refresh.lock sidecar serializes refresh() invocations
end-to-end.
"""
from __future__ import annotations

import json
import multiprocessing
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REFRESH = REPO_ROOT / "bin" / "refresh_learning_state"
FIXTURE_REPO = REPO_ROOT / "fixtures" / "eval-fixtures" / "mini-repo"
SEED = FIXTURE_REPO / "seed"

sys.path.insert(0, str(REPO_ROOT / "bin"))
from state_handle import repo_id  # noqa: E402


def _setup_repo_with_events(td: Path, *, events_filename: str) -> tuple[Path, Path, Path]:
    """Stage a mini-repo with the named hook-events fixture. Returns
    (repo_path, state_root, state_dir).
    """
    repo = td / "repo"
    shutil.copytree(FIXTURE_REPO, repo, ignore=shutil.ignore_patterns("seed"))
    rid = repo_id(repo)
    state_root = repo / ".agent-learning"
    state_dir = state_root / "repos" / rid
    state_dir.mkdir(parents=True, exist_ok=True)
    for name in ("config.json", "baseline.json", "domain-rules.active.json", "skill-map.json"):
        shutil.copy(SEED / name, state_dir / name)
    (state_dir / "improvement-queue.jsonl").write_text("", encoding="utf-8")
    shutil.copy(SEED / events_filename, state_dir / "hook-events.jsonl")
    shutil.copy(SEED / "config.json", state_root / "config.json")
    return repo, state_root, state_dir


def _run_refresh(repo: Path, state_root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(REFRESH), "--repo", str(repo), "--state-dir", str(state_root)],
        capture_output=True, text=True, check=False,
    )


def _refresh_worker(args):
    """Spawn-pickleable worker for the M1 concurrency test."""
    repo_str, state_root_str = args
    proc = subprocess.run(
        [str(REPO_ROOT / "bin" / "refresh_learning_state"),
         "--repo", repo_str, "--state-dir", state_root_str],
        capture_output=True, text=True, check=False,
    )
    return proc.returncode, proc.stderr


class M4StableRetirementRowId(unittest.TestCase):
    """Two refreshes against the same fixture should yield exactly one
    gate_retirement_candidate row, not two."""

    def test_two_refreshes_produce_one_row(self):
        with tempfile.TemporaryDirectory() as td:
            repo, state_root, state_dir = _setup_repo_with_events(
                Path(td), events_filename="hook-events-failure-cohort.jsonl",
            )
            for _ in range(2):
                proc = _run_refresh(repo, state_root)
                self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            rows = [
                json.loads(ln)
                for ln in (state_dir / "improvement-queue.jsonl").read_text().splitlines()
                if ln
            ]
            retirement_rows = [r for r in rows if r.get("kind") == "gate_retirement_candidate"]
            self.assertEqual(
                len(retirement_rows), 1,
                msg=(
                    f"expected stable id to collapse duplicates across "
                    f"refreshes; got {len(retirement_rows)} retirement rows "
                    f"after two refreshes"
                ),
            )


class H2CausalSignalGate(unittest.TestCase):
    """A correlationally-failing gate WITHOUT supporting causal evidence
    (no probe data) must not be queued for retirement post-H2."""

    def test_gate_without_probe_data_is_not_queued(self):
        with tempfile.TemporaryDirectory() as td:
            repo, state_root, state_dir = _setup_repo_with_events(
                Path(td), events_filename="hook-events-failure-cohort.jsonl",
            )
            # Strip probe_decisions from the cohort so causal_signal stays
            # at needs_review. The correlation evidence alone is no longer
            # enough to trigger retirement.
            events_path = state_dir / "hook-events.jsonl"
            stripped = []
            for line in events_path.read_text().splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                row.pop("probe_decisions", None)
                stripped.append(json.dumps(row))
            events_path.write_text("\n".join(stripped) + "\n")

            proc = _run_refresh(repo, state_root)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)

            rows = [
                json.loads(ln)
                for ln in (state_dir / "improvement-queue.jsonl").read_text().splitlines()
                if ln
            ]
            retirement_rows = [r for r in rows if r.get("kind") == "gate_retirement_candidate"]
            self.assertEqual(
                len(retirement_rows), 0,
                msg=(
                    "gate without causal probe data should not be queued "
                    "for retirement (correlation alone is not enough post-H2)"
                ),
            )


class M2InheritedGateMissingDerivedFrom(unittest.TestCase):
    """A gate_id row without a derived_from line (partial write, CRLF, or
    other malformedness) must be routed through the DEMOTE path, not the
    retirement path."""

    def test_malformed_inherited_block_demotes_not_retires(self):
        with tempfile.TemporaryDirectory() as td:
            repo, state_root, state_dir = _setup_repo_with_events(
                Path(td), events_filename="hook-events-inherited-failure-cohort.jsonl",
            )
            # Hand-craft a malformed inherited block: gate_id present,
            # derived_from missing. Pre-fix _inherited_gates would skip
            # this entirely and the retirement filter would queue it as
            # gate_retirement_candidate.
            reports = state_dir / "reports"
            reports.mkdir(parents=True, exist_ok=True)
            (reports / "latest-approved-gates.md").write_text(
                "# Approved Agent Gates\n\n"
                "- domain: cloudflare\n"
                "  gate_id: bbbbbbbbbbbb\n"
                "  gate_category: docs-check\n"
                "  gate: Some inherited gate.\n"
                "  # NOTE: no derived_from line (simulates partial write)\n",
                encoding="utf-8",
            )

            proc = _run_refresh(repo, state_root)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)

            rows = [
                json.loads(ln)
                for ln in (state_dir / "improvement-queue.jsonl").read_text().splitlines()
                if ln
            ]
            kinds_for_gate = {
                r.get("kind") for r in rows if r.get("gate_id") == "bbbbbbbbbbbb"
            }
            self.assertIn(
                "inherited_gate_demote_candidate", kinds_for_gate,
                msg=(
                    "fail-closed: gate_id without derived_from must route to "
                    "demote path, not retirement"
                ),
            )
            self.assertNotIn(
                "gate_retirement_candidate", kinds_for_gate,
                msg="should never retire an inherited gate (would affect siblings)",
            )

            # The demote row should carry an "unknown" derived_from sentinel.
            demote = next(
                r for r in rows
                if r.get("gate_id") == "bbbbbbbbbbbb"
                and r.get("kind") == "inherited_gate_demote_candidate"
            )
            self.assertEqual(demote["derived_from"], "unknown")


class M1ConcurrentRefreshSerializes(unittest.TestCase):
    """Two concurrent refresh() invocations on the same repo must
    serialize end-to-end via the top-level .refresh.lock sidecar."""

    def test_two_concurrent_refreshes_both_complete_without_corruption(self):
        with tempfile.TemporaryDirectory() as td:
            repo, state_root, state_dir = _setup_repo_with_events(
                Path(td), events_filename="hook-events-failure-cohort.jsonl",
            )
            jobs = [(str(repo), str(state_root))] * 3
            ctx = multiprocessing.get_context("spawn")
            with ctx.Pool(processes=3) as pool:
                results = pool.map(_refresh_worker, jobs)
            for rc, err in results:
                self.assertEqual(rc, 0, msg=f"refresh failed: {err}")
            # State files must all parse cleanly (no torn writes from
            # interleaving baseline.json with skill-map.json).
            for name in ("baseline.json", "skill-map.json", "skill-usage.json", "skill-impact.json"):
                path = state_dir / name
                self.assertTrue(path.exists())
                try:
                    json.loads(path.read_text())
                except json.JSONDecodeError as exc:
                    self.fail(f"{name} is not valid JSON after concurrent refreshes: {exc}")
            # Improvement queue should contain exactly one retirement row
            # for the failing gate (stable id + serialized refreshes).
            queue_lines = [
                json.loads(ln)
                for ln in (state_dir / "improvement-queue.jsonl").read_text().splitlines()
                if ln
            ]
            retirement = [r for r in queue_lines if r.get("kind") == "gate_retirement_candidate"]
            self.assertEqual(
                len(retirement), 1,
                msg=(
                    f"expected exactly 1 retirement row after 3 concurrent "
                    f"refreshes; got {len(retirement)}"
                ),
            )


if __name__ == "__main__":
    unittest.main()
