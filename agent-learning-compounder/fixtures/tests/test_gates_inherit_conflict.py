"""Tests for Bug 2: gates_inherit must lock the target file and refuse silent
origin-repo collisions.

Pre-fix:
  - gate_already_present check ran outside any lock, so two concurrent
    inherits of the same gate_id from the same origin both observed absence,
    both appended, and the gate appeared TWICE.
  - re-inheriting an already-present gate_id from a DIFFERENT origin_repo
    returned 0 silently — provenance for the second origin was lost.

Post-fix:
  - read+check+write runs under fcntl.LOCK_EX, so concurrent inherits
    serialize: exactly one writes, the other no-ops.
  - same gate_id / different origin_repo returns non-zero with a clear
    stderr diagnostic.
"""
from __future__ import annotations

import json
import multiprocessing
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INHERIT = REPO_ROOT / "bin" / "gates_inherit"


def _run_inherit(args):
    """Module-level worker so multiprocessing 'spawn' / 'fork' both work."""
    shared, target, gate_id = args
    proc = subprocess.run(
        [
            str(INHERIT),
            "--shared-root", str(shared),
            "--target-gates", str(target),
            "--gate-id", gate_id,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stderr


class GatesInheritConflictTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.shared = Path(self.tmp.name) / "shared" / "gates"
        self.shared.mkdir(parents=True)
        self.target = Path(self.tmp.name) / "approved-gates.md"
        self.target.write_text("# Approved Agent Gates\n\n")
        # Two records sharing the same gate_id from different origin_repos.
        self.gate_id = "aaaaaaaaaaaa"
        (self.shared / f"{self.gate_id}.json").write_text(json.dumps({
            "domain": "cloudflare",
            "gate_id": self.gate_id,
            "gate_category": "docs-check",
            "gate": "Re-read current Cloudflare docs before changing wrangler config.",
            "origin_repo": "repo-abc",
            "promoted_at": "2026-01-01T00:00:00Z",
            "note": "",
        }))

    def tearDown(self):
        self.tmp.cleanup()

    def _write_alt_origin_record(self):
        """Overwrite the shared record so a re-inherit reports a different origin.

        Same gate_id, different origin_repo — simulates a sibling repo that
        independently promoted the same heuristic from its own context.
        """
        (self.shared / f"{self.gate_id}.json").write_text(json.dumps({
            "domain": "cloudflare",
            "gate_id": self.gate_id,
            "gate_category": "docs-check",
            "gate": "Re-read current Cloudflare docs before changing wrangler config.",
            "origin_repo": "repo-xyz",  # different!
            "promoted_at": "2026-01-02T00:00:00Z",
            "note": "",
        }))

    def test_conflicting_origin_repo_exits_nonzero(self):
        # First inherit succeeds and records origin=repo-abc.
        rc1, err1 = _run_inherit((self.shared.parent, self.target, self.gate_id))
        self.assertEqual(rc1, 0, msg=err1)
        self.assertIn("repo-abc", self.target.read_text())

        # Second inherit, same gate_id, DIFFERENT origin_repo.
        self._write_alt_origin_record()
        rc2, err2 = _run_inherit((self.shared.parent, self.target, self.gate_id))
        self.assertNotEqual(
            rc2, 0,
            msg=(
                "expected non-zero exit on origin_repo collision; "
                "pre-fix this silently returned 0 and lost provenance"
            ),
        )
        # Diagnostic must name BOTH the existing derived_from and the new
        # incoming origin so an operator can investigate.
        self.assertIn("repo-abc", err2)
        self.assertIn("repo-xyz", err2)
        # Target file must remain unchanged — refuse but don't corrupt.
        gate_id_lines = re.findall(
            rf"^\s*gate_id:\s*{self.gate_id}\s*$",
            self.target.read_text(),
            re.MULTILINE,
        )
        self.assertEqual(
            len(gate_id_lines), 1,
            msg="conflict path must not append a second copy of the gate",
        )

    def test_same_origin_repo_is_idempotent(self):
        """Regression check: legitimate re-inherit (same origin) still 0s."""
        for _ in range(2):
            rc, err = _run_inherit((self.shared.parent, self.target, self.gate_id))
            self.assertEqual(rc, 0, msg=err)
        gate_id_lines = re.findall(
            rf"^\s*gate_id:\s*{self.gate_id}\s*$",
            self.target.read_text(),
            re.MULTILINE,
        )
        self.assertEqual(len(gate_id_lines), 1)

    def test_concurrent_inherit_same_gate_appears_exactly_once(self):
        """Two concurrent inherits of the same gate (same origin) must not
        double-append.

        Pre-fix, both processes observed absence (read happened before any
        write), both appended, and the gate appeared twice. Post-fix, the
        first to acquire LOCK_EX writes; the second observes presence and
        no-ops.
        """
        n_concurrent = 6
        jobs = [(self.shared.parent, self.target, self.gate_id)] * n_concurrent
        ctx = multiprocessing.get_context("spawn")
        with ctx.Pool(processes=n_concurrent) as pool:
            results = pool.map(_run_inherit, jobs)

        # All calls must succeed — same origin_repo, so the lock-loser
        # observes presence and returns 0 (idempotent), not EXIT_CONFLICT.
        for rc, err in results:
            self.assertEqual(rc, 0, msg=err)

        gate_id_lines = re.findall(
            rf"^\s*gate_id:\s*{self.gate_id}\s*$",
            self.target.read_text(),
            re.MULTILINE,
        )
        self.assertEqual(
            len(gate_id_lines), 1,
            msg=(
                f"expected exactly 1 gate_id line after {n_concurrent} concurrent "
                f"inherits, found {len(gate_id_lines)}; pre-fix race produced 2+"
            ),
        )


if __name__ == "__main__":
    unittest.main()
