"""Tests for C1 + the federation gate_id contract.

Pre-fix:
  - bin/export_gates rebuilt latest-approved-gates.md from the source report
    only. Blocks written by gates_inherit (which carry a `derived_from:`
    line) were silently wiped on every re-export.
  - The gate_id hash recipe had no frozen-value coverage. A one-character
    change to the recipe would silently invalidate every cross-repo gate
    id while existing determinism tests would still pass (both legs use
    the new recipe).

Post-fix:
  - Re-exporting preserves any block in the existing output whose body
    contains a `derived_from:` line, keyed by gate_id.
  - A literal-value assertion locks the gate_id hash recipe so any
    federation-breaking change to the input ordering, separator, or
    slice has to be a deliberate (and visible) edit.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPORT_GATES = REPO_ROOT / "bin" / "export_gates"


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


class ExportGatesFrozenIdRecipe(unittest.TestCase):
    """The federation contract: every consumer (export, promote, inherit,
    scoring) MUST agree on the bytes that go into the hash and the slice
    that comes out. Pin one known input/output so the recipe can't drift
    silently across repos or releases."""

    # sha256("cloudflare|docs-check|Re-read current Cloudflare docs before
    # changing wrangler config.")[:12]
    EXPECTED_GATE_ID = "2aed10be9612"

    def test_export_emits_frozen_gate_id_for_canonical_input(self):
        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "report.md"
            report.write_text(SAMPLE_REPORT)
            output = Path(td) / "gates.md"
            subprocess.run(
                [str(EXPORT_GATES), "--report", str(report), "--output", str(output)],
                check=True,
            )
            ids = re.findall(r"gate_id:\s*([a-f0-9]{12})", output.read_text())
            self.assertIn(
                self.EXPECTED_GATE_ID, ids,
                msg=(
                    "frozen gate_id contract broke. If you changed the hash "
                    "recipe in bin/export_gates._gate_id intentionally, the "
                    "federation has to migrate every existing gate_id; this "
                    "test guards against accidental drift."
                ),
            )


class ExportGatesPreservesInheritedBlocks(unittest.TestCase):
    """C1: re-exporting must not wipe blocks that carry `derived_from:`."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.report = Path(self.tmp.name) / "report.md"
        self.report.write_text(SAMPLE_REPORT)
        self.output = Path(self.tmp.name) / "gates.md"

    def tearDown(self):
        self.tmp.cleanup()

    def _export(self):
        subprocess.run(
            [str(EXPORT_GATES), "--report", str(self.report), "--output", str(self.output)],
            check=True,
        )

    def test_re_export_preserves_derived_from_block(self):
        # First export: only the locally-discovered cloudflare gate lands.
        self._export()
        # Simulate a sibling repo's promotion landing here via gates_inherit:
        # append an inherited block carrying a derived_from line. The inherited
        # gate has a DIFFERENT gate_id from anything in our local report so we
        # can tell preservation apart from re-rendering.
        inherited_block = (
            "- domain: kubernetes\n"
            "  gate_id: cccccccccccc\n"
            "  gate_category: yaml-check\n"
            "  gate: Verify kustomize render before kubectl apply.\n"
            "  derived_from: sibling-repo:cccccccccccc:2026-01-15T00:00:00Z\n"
        )
        with self.output.open("a", encoding="utf-8") as fh:
            fh.write("\n" + inherited_block)
        self.assertIn("derived_from: sibling-repo", self.output.read_text())

        # Re-export from the same report (which knows nothing about kubernetes).
        # Pre-fix this wiped the inherited block.
        self._export()
        text = self.output.read_text()
        self.assertIn(
            "gate_id: cccccccccccc", text,
            msg=(
                "inherited block was wiped on re-export. _inherited_gates "
                "in refresh_learning_state would now see this federated gate "
                "as gone and queue it as a retirement candidate."
            ),
        )
        self.assertIn("derived_from: sibling-repo:cccccccccccc", text)
        # Local cloudflare block must still be there (rendered fresh).
        self.assertIn("gate_id: 2aed10be9612", text)

    def test_re_export_drops_inherited_block_when_local_discovers_same_gate_id(self):
        """If our local report independently rediscovers the same gate_id, the
        freshly-rendered local block wins and we don't emit two copies."""
        self._export()
        # Inject an inherited block carrying the SAME gate_id the report
        # would produce locally. The local render should take precedence
        # (no duplicate row).
        inherited_block = (
            "- domain: cloudflare\n"
            "  gate_id: 2aed10be9612\n"
            "  gate_category: docs-check\n"
            "  gate: Re-read current Cloudflare docs before changing wrangler config.\n"
            "  derived_from: sibling-repo:2aed10be9612:2026-01-15T00:00:00Z\n"
        )
        with self.output.open("a", encoding="utf-8") as fh:
            fh.write("\n" + inherited_block)
        self._export()
        text = self.output.read_text()
        gate_id_lines = re.findall(
            r"^\s*gate_id:\s*2aed10be9612\s*$", text, re.MULTILINE,
        )
        self.assertEqual(
            len(gate_id_lines), 1,
            msg=(
                f"expected exactly one gate_id line after re-export, "
                f"found {len(gate_id_lines)}; preserve-merge produced a duplicate"
            ),
        )

    def test_re_export_preserves_inherited_alias_chain(self):
        self._export()
        inherited_block = (
            "- domain: kubernetes\n"
            "  gate_id: cccccccccccc\n"
            "  gate_category: yaml-check\n"
            "  gate: Verify kustomize render before kubectl apply.\n"
            "  previous_gate_ids: bbbbbbbbbbbb, aaaaaaaaaaaa\n"
            "  derived_from: sibling-repo:cccccccccccc:2026-01-15T00:00:00Z\n"
        )
        with self.output.open("a", encoding="utf-8") as fh:
            fh.write("\n" + inherited_block)

        self._export()

        text = self.output.read_text()
        self.assertIn("gate_id: cccccccccccc", text)
        self.assertIn("previous_gate_ids: bbbbbbbbbbbb, aaaaaaaaaaaa", text)

    def test_local_explicit_rename_supersedes_inherited_old_id_without_duplicate(self):
        self._export()
        old_id = ExportGatesFrozenIdRecipe.EXPECTED_GATE_ID
        updated_report = SAMPLE_REPORT.replace("Re-read current Cloudflare docs", "Read fresh Cloudflare docs")
        self.report.write_text(updated_report)
        proc = subprocess.run(
            [str(EXPORT_GATES), "--report", str(self.report), "--output", str(self.output)],
            capture_output=True,
            text=True,
            check=False,
        )
        new_id = re.search(rf"--rename\s+{old_id}:([a-f0-9]{{12}})", proc.stderr).group(1)
        self.output.write_text(
            "# Approved Agent Gates\n\n"
            "## gates\n\n"
            "- domain: cloudflare\n"
            f"  gate_id: {old_id}\n"
            "  gate_category: docs-check\n"
            "  gate: Re-read current Cloudflare docs before changing wrangler config.\n"
            "  previous_gate_ids: bbbbbbbbbbbb\n"
            f"  derived_from: sibling-repo:{old_id}:2026-01-15T00:00:00Z\n",
            encoding="utf-8",
        )

        subprocess.run(
            [
                str(EXPORT_GATES),
                "--report", str(self.report),
                "--output", str(self.output),
                "--rename", f"{old_id}:{new_id}",
            ],
            check=True,
        )

        text = self.output.read_text()
        self.assertIn(f"gate_id: {new_id}", text)
        self.assertIn(f"previous_gate_ids: {old_id}, bbbbbbbbbbbb", text)
        self.assertEqual(len(re.findall(rf"^\s*gate_id:\s*{old_id}\s*$", text, re.MULTILINE)), 0)

    def test_first_export_when_output_does_not_exist(self):
        """Regression: the preserve path must be a no-op when the output
        file doesn't exist yet (no existing inherited blocks to merge)."""
        self.assertFalse(self.output.exists())
        self._export()
        text = self.output.read_text()
        self.assertIn("gate_id: 2aed10be9612", text)


if __name__ == "__main__":
    unittest.main()
