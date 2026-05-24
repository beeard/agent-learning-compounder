"""Tests for P4-B: gates_inherit appends shared gates with provenance."""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INHERIT = REPO_ROOT / "bin" / "gates_inherit"


class GatesInherit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.shared = Path(self.tmp.name) / "shared" / "gates"
        self.shared.mkdir(parents=True)
        self.target = Path(self.tmp.name) / "approved-gates.md"
        self.target.write_text("# Approved Agent Gates\n\n")
        (self.shared / "aaaaaaaaaaaa.json").write_text(json.dumps({
            "domain": "cloudflare",
            "gate_id": "aaaaaaaaaaaa",
            "gate_category": "docs-check",
            "gate": "Re-read current Cloudflare docs before changing wrangler config.",
            "origin_repo": "repo-abc",
            "promoted_at": "2026-01-01T00:00:00Z",
            "note": "",
        }))

    def tearDown(self):
        self.tmp.cleanup()

    def test_inherit_appends_with_provenance(self):
        subprocess.run([
            str(INHERIT),
            "--shared-root", str(self.shared.parent),
            "--target-gates", str(self.target),
            "--gate-id", "aaaaaaaaaaaa",
        ], check=True)
        text = self.target.read_text()
        self.assertIn("aaaaaaaaaaaa", text)
        self.assertIn("derived_from: repo-abc:aaaaaaaaaaaa:2026-01-01T00:00:00Z", text)
        self.assertIn("docs-check", text)
        self.assertIn("cloudflare", text)

    def test_inherit_is_idempotent(self):
        for _ in range(2):
            subprocess.run([
                str(INHERIT),
                "--shared-root", str(self.shared.parent),
                "--target-gates", str(self.target),
                "--gate-id", "aaaaaaaaaaaa",
            ], check=True)
        text = self.target.read_text()
        # Count canonical gate_id field lines only — the gate_id also appears
        # inside derived_from, so a bare substring count would be misleading.
        gate_id_lines = re.findall(r"^\s*gate_id:\s*aaaaaaaaaaaa\s*$", text, re.MULTILINE)
        self.assertEqual(
            len(gate_id_lines), 1,
            f"expected exactly 1 gate_id line, found {len(gate_id_lines)}",
        )

    def test_inherit_refuses_missing_shared_record(self):
        proc = subprocess.run([
            str(INHERIT),
            "--shared-root", str(self.shared.parent),
            "--target-gates", str(self.target),
            "--gate-id", "doesnotexist",
        ], capture_output=True, text=True, check=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("not found", proc.stderr)

    def test_inherit_refuses_missing_target(self):
        target = Path(self.tmp.name) / "nonexistent.md"
        proc = subprocess.run([
            str(INHERIT),
            "--shared-root", str(self.shared.parent),
            "--target-gates", str(target),
            "--gate-id", "aaaaaaaaaaaa",
        ], capture_output=True, text=True, check=False)
        self.assertNotEqual(proc.returncode, 0)
        # The error message should mention the target was not found
        self.assertIn("not", proc.stderr.lower())


if __name__ == "__main__":
    unittest.main()
