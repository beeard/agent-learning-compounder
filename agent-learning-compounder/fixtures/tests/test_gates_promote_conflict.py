"""Tests for H5 (atomic write + conflict detection) and H6 (field validation)
in gates_promote.

Pre-fix:
  - out_path.write_text was unguarded by flock or tmp+rename. Two operators
    promoting the same gate_id from different repos raced; the loser's bytes
    could interleave with the winner's, and gates_inherit on a sibling repo
    would see truncated JSON as a misleading "invalid shared gate record".
  - The promote path did no field validation. Empty or newline-bearing
    --origin-repo wrote through, and every subsequent gates_inherit on the
    record failed validation, bricking federation until manual hand-edit.

Post-fix:
  - atomic_write_json writes to .tmp + fsync + os.replace.
  - Same-content re-promote is idempotent (only promoted_at differs).
  - Same gate_id from a DIFFERENT origin (or with mutated gate text) exits
    with EXIT_CONFLICT (5) so federation can't silently lose provenance.
  - validate_record_for_promote rejects empty/newline-bearing fields with
    EXIT_INVALID_RECORD (6), matching the gates_inherit contract.
"""
from __future__ import annotations

import json
import multiprocessing
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMOTE = REPO_ROOT / "bin" / "gates_promote"
EXPORT_GATES = REPO_ROOT / "bin" / "export_gates"

# Mirrors the constants defined in bin/gates_promote. Asserting on the
# exact value (not just non-zero) catches accidental renumbering that would
# break any caller switching on exit codes.
EXIT_CONFLICT = 5
EXIT_INVALID_RECORD = 6

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

# Canonical gate_id derived from (cloudflare|docs-check|<text>).
GATE_ID = "2aed10be9612"


def _stage_gates_md(tmpdir: Path) -> Path:
    """Run export_gates against SAMPLE_REPORT and return the gates.md path
    with our canonical GATE_ID already stamped in it."""
    report = tmpdir / "report.md"
    report.write_text(SAMPLE_REPORT)
    gates_md = tmpdir / "approved-gates.md"
    subprocess.run(
        [str(EXPORT_GATES), "--report", str(report), "--output", str(gates_md)],
        check=True,
    )
    return gates_md


def _promote(gates_md: Path, shared: Path, origin: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            str(PROMOTE),
            "--gates", str(gates_md),
            "--gate-id", GATE_ID,
            "--origin-repo", origin,
            "--shared-root", str(shared),
        ],
        capture_output=True, text=True, check=False,
    )


def _promote_worker(args):
    """Module-level worker so multiprocessing 'spawn' works on macOS too."""
    gates_md, shared, origin = args
    return _promote(Path(gates_md), Path(shared), origin).returncode


class GatesPromoteAtomicWrite(unittest.TestCase):
    """H5: parallel promoters must not produce a torn shared-registry file."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self.tmp.name)
        self.gates_md = _stage_gates_md(self.tmpdir)
        self.shared = self.tmpdir / "shared"

    def tearDown(self):
        self.tmp.cleanup()

    def test_re_promote_same_origin_is_idempotent(self):
        proc1 = _promote(self.gates_md, self.shared, "repo-A")
        self.assertEqual(proc1.returncode, 0, msg=proc1.stderr)
        record_path = self.shared / "gates" / f"{GATE_ID}.json"
        first = json.loads(record_path.read_text())

        proc2 = _promote(self.gates_md, self.shared, "repo-A")
        self.assertEqual(proc2.returncode, 0, msg=proc2.stderr)
        second = json.loads(record_path.read_text())

        self.assertEqual(first["origin_repo"], second["origin_repo"])
        self.assertEqual(first["gate"], second["gate"])

    def test_concurrent_promote_writes_a_valid_json_file(self):
        """No matter who wins the race, the final file must parse cleanly.
        Pre-fix the unguarded write could interleave bytes into invalid JSON."""
        n = 5
        jobs = [(str(self.gates_md), str(self.shared), "repo-A")] * n
        ctx = multiprocessing.get_context("spawn")
        with ctx.Pool(processes=n) as pool:
            rcs = pool.map(_promote_worker, jobs)
        record_path = self.shared / "gates" / f"{GATE_ID}.json"
        self.assertTrue(record_path.exists())
        # File must be valid JSON regardless of race outcome.
        record = json.loads(record_path.read_text())
        self.assertEqual(record["gate_id"], GATE_ID)
        # All callers should have succeeded (same content, idempotent).
        for rc in rcs:
            self.assertEqual(
                rc, 0,
                msg=f"got non-zero exit {rc} in concurrent same-origin promote; "
                    "expected idempotent success for all racers",
            )


class GatesPromoteConflictDetection(unittest.TestCase):
    """H5 second half: same gate_id from a different origin is a conflict,
    not a silent overwrite. Pinned exit code so callers can switch on it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self.tmp.name)
        self.gates_md = _stage_gates_md(self.tmpdir)
        self.shared = self.tmpdir / "shared"

    def tearDown(self):
        self.tmp.cleanup()

    def test_conflicting_origin_repo_exits_with_pinned_conflict_code(self):
        proc1 = _promote(self.gates_md, self.shared, "repo-A")
        self.assertEqual(proc1.returncode, 0, msg=proc1.stderr)

        proc2 = _promote(self.gates_md, self.shared, "repo-B")
        self.assertEqual(
            proc2.returncode, EXIT_CONFLICT,
            msg=(
                f"expected EXIT_CONFLICT={EXIT_CONFLICT} on different-origin "
                f"re-promote, got {proc2.returncode}. stderr: {proc2.stderr!r}"
            ),
        )
        self.assertIn("repo-A", proc2.stderr)
        self.assertIn("repo-B", proc2.stderr)

        # Original record must survive untouched; conflict path must not
        # rewrite the registry with the loser's content.
        record = json.loads(
            (self.shared / "gates" / f"{GATE_ID}.json").read_text()
        )
        self.assertEqual(record["origin_repo"], "repo-A")


class GatesPromoteFieldValidation(unittest.TestCase):
    """H6: empty / newline-bearing fields must be rejected before the
    record reaches the shared registry. Pre-fix a malformed --origin-repo
    bricked every future gates_inherit on the same id."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self.tmp.name)
        self.gates_md = _stage_gates_md(self.tmpdir)
        self.shared = self.tmpdir / "shared"

    def tearDown(self):
        self.tmp.cleanup()

    def _promote_with_origin(self, origin: str) -> subprocess.CompletedProcess:
        return _promote(self.gates_md, self.shared, origin)

    def test_rejects_empty_origin_repo(self):
        proc = self._promote_with_origin("")
        self.assertEqual(
            proc.returncode, EXIT_INVALID_RECORD,
            msg=f"expected EXIT_INVALID_RECORD={EXIT_INVALID_RECORD}, "
                f"got {proc.returncode}: {proc.stderr!r}",
        )
        self.assertIn("origin_repo", proc.stderr)
        # Nothing should land in the registry on rejection.
        self.assertFalse((self.shared / "gates" / f"{GATE_ID}.json").exists())

    def test_rejects_newline_in_origin_repo(self):
        proc = self._promote_with_origin("repo-A\n- domain: injected")
        self.assertEqual(
            proc.returncode, EXIT_INVALID_RECORD,
            msg=f"expected EXIT_INVALID_RECORD={EXIT_INVALID_RECORD}, "
                f"got {proc.returncode}: {proc.stderr!r}",
        )
        self.assertIn("newline", proc.stderr.lower())
        self.assertFalse((self.shared / "gates" / f"{GATE_ID}.json").exists())


if __name__ == "__main__":
    unittest.main()
