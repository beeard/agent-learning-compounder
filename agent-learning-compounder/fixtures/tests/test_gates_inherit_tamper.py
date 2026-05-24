"""Tests for C2 (content-hash check) + M3 (CRLF-tolerant splitter) in gates_inherit.

Pre-fix:
  - validate_record only confirmed record["gate_id"] matched the filename;
    if an attacker edited the `gate` field in the shared registry, every
    inheritor pulled the mutated text under the original gate_id and
    cohort statistics kept rolling under the wrong instruction.
  - _existing_derived_from used text.split("\\n- domain:") which only matched
    LF-delimited blocks preceded by a newline. A CRLF file or one starting
    directly with "- domain:" was parsed as one giant block, the gate_id
    walk crossed block boundaries silently, and gate_already_present (which
    uses a separate MULTILINE regex) disagreed — breaking idempotency
    claims on rerun.

Post-fix:
  - validate_record recomputes _gate_id(domain, category, gate) and refuses
    on mismatch with a stderr message naming the derived id.
  - _existing_derived_from uses re.split(r"(?m)^-\\s+domain:\\s*", text),
    matching the convention in export_gates and gates_promote and handling
    both CRLF and missing-leading-newline cases.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INHERIT = REPO_ROOT / "bin" / "gates_inherit"

# Frozen-value gate_id for the canonical cloudflare/docs-check fixture.
# See test_export_gates_federation for the federation contract argument.
GATE_ID = "2aed10be9612"
GATE_TEXT = "Re-read current Cloudflare docs before changing wrangler config."


def _write_record(shared_dir: Path, *, gate: str, gate_id: str = GATE_ID) -> Path:
    record = {
        "domain": "cloudflare",
        "gate_id": gate_id,
        "gate_category": "docs-check",
        "gate": gate,
        "origin_repo": "repo-abc",
        "promoted_at": "2026-01-01T00:00:00Z",
        "note": "",
    }
    record_path = shared_dir / f"{gate_id}.json"
    record_path.write_text(json.dumps(record))
    return record_path


def _run_inherit(shared_root: Path, target: Path, gate_id: str):
    return subprocess.run(
        [str(INHERIT), "--shared-root", str(shared_root), "--target-gates", str(target),
         "--gate-id", gate_id],
        capture_output=True, text=True, check=False,
    )


class GatesInheritContentHash(unittest.TestCase):
    """C2: post-promote mutation of the gate text in the shared registry
    must be detected by re-deriving _gate_id from the record's content."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.shared = Path(self.tmp.name) / "shared" / "gates"
        self.shared.mkdir(parents=True)
        self.target = Path(self.tmp.name) / "approved-gates.md"
        self.target.write_text("# Approved Agent Gates\n\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_inherit_accepts_record_whose_content_hashes_correctly(self):
        _write_record(self.shared, gate=GATE_TEXT)
        proc = _run_inherit(self.shared.parent, self.target, GATE_ID)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn(f"gate_id: {GATE_ID}", self.target.read_text())

    def test_inherit_rejects_record_whose_gate_text_was_swapped(self):
        # Filename still claims GATE_ID but `gate` field was edited
        # post-promotion. Without the content-hash check this lands
        # silently with the mutated instruction.
        _write_record(self.shared, gate="Skip the docs check entirely.")
        proc = _run_inherit(self.shared.parent, self.target, GATE_ID)
        self.assertNotEqual(
            proc.returncode, 0,
            msg="expected non-zero on mutated gate text; pre-fix inherited silently",
        )
        self.assertIn("does not hash to gate_id", proc.stderr)
        # Critically: the target file must not contain the mutated text.
        self.assertNotIn("Skip the docs check entirely", self.target.read_text())

    def test_inherit_rejects_record_with_swapped_domain(self):
        # Also catches domain or category mutation since both feed the hash.
        record = {
            "domain": "kubernetes",  # was cloudflare
            "gate_id": GATE_ID,
            "gate_category": "docs-check",
            "gate": GATE_TEXT,
            "origin_repo": "repo-abc",
            "promoted_at": "2026-01-01T00:00:00Z",
            "note": "",
        }
        (self.shared / f"{GATE_ID}.json").write_text(json.dumps(record))
        proc = _run_inherit(self.shared.parent, self.target, GATE_ID)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("does not hash to gate_id", proc.stderr)


class GatesInheritParserRobustness(unittest.TestCase):
    """M3: idempotency must hold for CRLF files and for files with no
    leading newline before the first `- domain:` block."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.shared = Path(self.tmp.name) / "shared" / "gates"
        self.shared.mkdir(parents=True)
        self.target = Path(self.tmp.name) / "approved-gates.md"
        _write_record(self.shared, gate=GATE_TEXT)

    def tearDown(self):
        self.tmp.cleanup()

    def _gate_id_line_count(self) -> int:
        return len(re.findall(
            rf"^\s*gate_id:\s*{GATE_ID}\s*$",
            self.target.read_text(),
            re.MULTILINE,
        ))

    def test_idempotent_when_file_starts_directly_with_block(self):
        """No `# Approved Agent Gates` preamble, no leading newline; the
        file begins on its first character with `- domain:`. Pre-fix the
        LF-only splitter returned no blocks and a re-inherit would append
        a second copy."""
        # First inherit: target starts empty (post-fix path).
        self.target.write_text("")
        proc = _run_inherit(self.shared.parent, self.target, GATE_ID)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        # The target now starts directly with "- domain:" (no preamble).
        text = self.target.read_text()
        self.assertTrue(
            text.lstrip().startswith("- domain:"),
            msg=f"expected block at file start, got:\n{text!r}",
        )
        # Second inherit on the same file: must be idempotent.
        proc2 = _run_inherit(self.shared.parent, self.target, GATE_ID)
        self.assertEqual(proc2.returncode, 0, msg=proc2.stderr)
        self.assertEqual(
            self._gate_id_line_count(), 1,
            msg="rerun appended a duplicate; missing-leading-newline broke idempotency",
        )

    def test_idempotent_on_crlf_file(self):
        """CRLF line endings (Windows / cross-platform editor). Pre-fix
        the LF splitter treated the whole file as one block and the
        derived_from walk would cross block boundaries."""
        # Seed the target with a CRLF-encoded inherited block for our gate.
        crlf_block = (
            "# Approved Agent Gates\r\n"
            "\r\n"
            "- domain: cloudflare\r\n"
            f"  gate_id: {GATE_ID}\r\n"
            "  gate_category: docs-check\r\n"
            f"  gate: {GATE_TEXT}\r\n"
            "  derived_from: repo-abc:2aed10be9612:2026-01-01T00:00:00Z\r\n"
        )
        self.target.write_bytes(crlf_block.encode("utf-8"))
        # Rerun inherit. Pre-fix the splitter saw no derived_from row and
        # appended a duplicate (LF-only splitter returned one giant block).
        proc = _run_inherit(self.shared.parent, self.target, GATE_ID)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertEqual(
            self._gate_id_line_count(), 1,
            msg="CRLF file: rerun appended a duplicate after my CRLF-tolerant split fix",
        )


if __name__ == "__main__":
    unittest.main()
