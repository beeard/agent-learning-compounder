"""Regression tests from the post-B-4 multi-reviewer audit (B-5 fixes).

These cover four lock / parsing gaps the convergent reviewers surfaced:

1. gates_promote conflict-check + write must happen under ONE lock --
   otherwise two different-origin promoters both observe absence and
   silently last-writer-wins the shared registry. The H5 fix narrowed
   the race window via atomic_write_json; B-5 closes it via shared
   sidecar lock (state_handle.atomic_rewrite).

2. export_gates render + write must use the same sidecar lock that
   gates_inherit uses. Pre-B-5 a concurrent inherit between export's
   read and write was silently overwritten by the render-from-stale
   snapshot, even though C1 added the preserve-inherited path. Lock
   has to be on a never-renamed sidecar because os.replace invalidates
   any data-file inode lock.

3. preserved_inherited_blocks used `"derived_from:" in part` substring
   matching, which would pin any block whose gate text legitimately
   contained that literal substring (e.g. an instruction about
   verifying derived_from values). B-5 anchors to the canonical
   indented multiline regex.
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
EXPORT_GATES = REPO_ROOT / "bin" / "export_gates"
PROMOTE = REPO_ROOT / "bin" / "gates_promote"
INHERIT = REPO_ROOT / "bin" / "gates_inherit"

# Reuses the canonical cloudflare/docs-check fixture content so the
# derived gate_id matches the frozen federation value.
GATE_ID = "2aed10be9612"
GATE_TEXT = "Re-read current Cloudflare docs before changing wrangler config."

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


def _stage_shared_record(shared_dir: Path, *, origin: str) -> Path:
    record = {
        "domain": "cloudflare",
        "gate_id": GATE_ID,
        "gate_category": "docs-check",
        "gate": GATE_TEXT,
        "origin_repo": origin,
        "promoted_at": "2026-01-01T00:00:00Z",
        "note": "",
    }
    record_path = shared_dir / f"{GATE_ID}.json"
    record_path.write_text(json.dumps(record))
    return record_path


def _export_gates(report: Path, output: Path):
    subprocess.run(
        [str(EXPORT_GATES), "--report", str(report), "--output", str(output)],
        check=True, capture_output=True,
    )


def _promote(gates_md: Path, shared: Path, origin: str) -> int:
    proc = subprocess.run(
        [str(PROMOTE),
         "--gates", str(gates_md),
         "--gate-id", GATE_ID,
         "--origin-repo", origin,
         "--shared-root", str(shared)],
        capture_output=True, text=True, check=False,
    )
    return proc.returncode


def _promote_worker(args):
    return _promote(Path(args[0]), Path(args[1]), args[2])


def _inherit_worker(args):
    """Spawn-pickleable inherit worker."""
    shared_root, target, gate_id = args
    proc = subprocess.run(
        [str(REPO_ROOT / "bin" / "gates_inherit"),
         "--shared-root", shared_root,
         "--target-gates", target,
         "--gate-id", gate_id],
        capture_output=True, text=True, check=False,
    )
    return proc.returncode, proc.stderr


def _export_worker(args):
    """Spawn-pickleable export worker."""
    report, output = args
    proc = subprocess.run(
        [str(REPO_ROOT / "bin" / "export_gates"),
         "--report", report, "--output", output],
        capture_output=True, text=True, check=False,
    )
    return proc.returncode, proc.stderr


class PromoteConflictRaceUnderSharedLock(unittest.TestCase):
    """Two concurrent different-origin promoters must NOT both succeed
    silently. With the B-5 shared-lock fix exactly one writes; the other
    sees the winner's record and either succeeds (idempotent match) or
    exits EXIT_CONFLICT.
    """
    EXIT_CONFLICT = 5

    def test_concurrent_different_origins_one_wins_other_conflicts(self):
        n = 6
        origins = [f"repo-{i}" for i in range(n)]
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            report = tdp / "report.md"
            report.write_text(SAMPLE_REPORT)
            gates_md = tdp / "approved-gates.md"
            _export_gates(report, gates_md)
            shared = tdp / "shared"

            jobs = [(str(gates_md), str(shared), origin) for origin in origins]
            ctx = multiprocessing.get_context("spawn")
            with ctx.Pool(processes=n) as pool:
                rcs = pool.map(_promote_worker, jobs)

            # Exactly one promoter wins (rc=0). The rest must be EXIT_CONFLICT.
            # Pre-B-5 the TOCTOU window would let multiple promoters silently
            # overwrite each other; the shared lock now serializes them.
            winners = [rc for rc in rcs if rc == 0]
            conflicts = [rc for rc in rcs if rc == self.EXIT_CONFLICT]
            self.assertEqual(
                len(winners), 1,
                msg=(
                    f"expected exactly one promoter to succeed; got "
                    f"{len(winners)} (rcs={rcs}). pre-B-5 multiple would "
                    f"silently last-writer-win the registry"
                ),
            )
            self.assertEqual(len(conflicts), n - 1, msg=f"rcs={rcs}")

            # File must be valid JSON and name exactly one of the racers.
            record = json.loads((shared / "gates" / f"{GATE_ID}.json").read_text())
            self.assertIn(record["origin_repo"], origins)


class ExportInheritRaceUnderSharedLock(unittest.TestCase):
    """A gates_inherit running concurrently with export_gates must not
    lose its appended block. Pre-B-5 export read the file, gates_inherit
    appended, export wrote a rendered string that excluded the new block
    -- the inherit was silently overwritten."""

    # Four DISTINCT (domain, category, gate, gate_id) so every inherit
    # exercises the append path. Same-id same-origin inherits would
    # hit the idempotent-match short-circuit on the 2nd-4th calls and
    # the test couldn't distinguish "lock serialized 4 appends" from
    # "only the first inherit ran, the rest no-op'd". gate_ids are the
    # real sha256(domain|category|gate)[:12]; C2 rejects mismatches.
    INHERITED_GATES = [
        ("kubernetes", "yaml-check", "Verify kustomize render before kubectl apply.", "592673b3333a"),
        ("terraform", "plan-check", "Run terraform plan and quote one resource change.", "3f5415acb6c7"),
        ("docker", "dockerfile-check", "Inspect Dockerfile for hardcoded secrets.", "33008792ade7"),
        ("aws", "iam-check", "Verify IAM role minimum permissions.", "6c449f0a07f0"),
    ]

    def test_concurrent_inherit_during_export_preserves_inherited_block(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            report = tdp / "report.md"
            report.write_text(SAMPLE_REPORT)
            target = tdp / "approved-gates.md"
            _export_gates(report, target)

            shared = tdp / "shared" / "gates"
            shared.mkdir(parents=True)
            for domain, category, gate_text, gate_id in self.INHERITED_GATES:
                (shared / f"{gate_id}.json").write_text(json.dumps({
                    "domain": domain,
                    "gate_id": gate_id,
                    "gate_category": category,
                    "gate": gate_text,
                    "origin_repo": "sibling-repo",
                    "promoted_at": "2026-01-15T00:00:00Z",
                    "note": "",
                }))

            inherit_jobs = [
                (str(shared.parent), str(target), gate_id)
                for _, _, _, gate_id in self.INHERITED_GATES
            ]
            export_jobs = [(str(report), str(target))] * 4

            ctx = multiprocessing.get_context("spawn")
            with ctx.Pool(processes=8) as pool:
                inherit_results = pool.map_async(_inherit_worker, inherit_jobs)
                export_results = pool.map_async(_export_worker, export_jobs)
                inherit_rcs = inherit_results.get(timeout=60)
                export_rcs = export_results.get(timeout=60)

            for rc, err in export_rcs:
                self.assertEqual(rc, 0, msg=f"export failed: rc={rc} stderr={err!r}")
            for rc, err in inherit_rcs:
                self.assertEqual(rc, 0, msg=f"inherit failed: rc={rc} stderr={err!r}")

            text = target.read_text()
            # Every distinct inherit's block must appear exactly once.
            # Strengthens the earlier test which used same-id inherits and
            # could not distinguish "all appended" from "first appended,
            # rest idempotent-matched".
            for _, _, _, gate_id in self.INHERITED_GATES:
                n_lines = len(re.findall(
                    rf"^\s*gate_id:\s*{gate_id}\s*$", text, re.MULTILINE,
                ))
                self.assertEqual(
                    n_lines, 1,
                    msg=(
                        f"expected exactly one occurrence of gate_id "
                        f"{gate_id}, got {n_lines}. The race between "
                        f"export's render-from-stale-snapshot and inherit's "
                        f"append would silently drop a freshly-appended "
                        f"block, leaving zero occurrences here."
                    ),
                )
            # And one derived_from line per inherit.
            self.assertEqual(
                text.count("derived_from: sibling-repo"),
                len(self.INHERITED_GATES),
            )


class PreservedInheritedBlocksAnchoredMatch(unittest.TestCase):
    """A local gate whose `gate:` text legitimately contains the literal
    substring 'derived_from:' must NOT be treated as inherited and pinned
    across re-exports."""

    def test_local_gate_with_derived_from_in_text_is_not_pinned(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            output = tdp / "gates.md"
            # Build a local block whose gate text mentions "derived_from:"
            # as part of the instruction. Pre-B-5 the substring match would
            # treat this as inherited; B-5 requires the line to start with
            # whitespace + canonical "derived_from:" indent.
            output.write_text(
                "# Approved Agent Gates\n\n"
                "## gates\n\n"
                "- domain: cloudflare\n"
                "  gate_id: dddddddddddd\n"
                "  gate_category: provenance-check\n"
                "  gate: Verify derived_from: matches the expected origin.\n"
            )

            # Re-export with a report that produces a DIFFERENT gate. The
            # local-with-substring block should NOT be preserved (it is
            # not actually inherited); the new render replaces the file.
            report = tdp / "report.md"
            report.write_text(SAMPLE_REPORT)
            _export_gates(report, output)

            text = output.read_text()
            self.assertNotIn(
                "gate_id: dddddddddddd", text,
                msg=(
                    "local block with 'derived_from:' in its gate text was "
                    "incorrectly preserved as inherited. The anchored "
                    "regex should require the line to start at the "
                    "canonical indent."
                ),
            )

    def test_real_inherited_block_is_still_preserved(self):
        """Sanity-check: the anchored regex must still match the canonical
        `  derived_from: ...` line that gates_inherit writes."""
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            output = tdp / "gates.md"
            output.write_text(
                "# Approved Agent Gates\n\n"
                "## gates\n\n"
                "- domain: kubernetes\n"
                "  gate_id: eeeeeeeeeeee\n"
                "  gate_category: yaml-check\n"
                "  gate: Verify kustomize render.\n"
                "  derived_from: sibling-repo:eeeeeeeeeeee:2026-01-15T00:00:00Z\n"
            )
            report = tdp / "report.md"
            report.write_text(SAMPLE_REPORT)
            _export_gates(report, output)

            text = output.read_text()
            self.assertIn("gate_id: eeeeeeeeeeee", text)
            self.assertIn("derived_from: sibling-repo", text)


if __name__ == "__main__":
    unittest.main()
