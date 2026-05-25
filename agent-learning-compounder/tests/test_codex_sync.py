"""U18 — Codex sync script smoke tests (no-op per W2 G0.5.2=YELLOW verdict)."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "maintenance" / "sync-to-codex-plugin.sh"


class CodexSyncScriptTests(unittest.TestCase):
    def test_script_present(self) -> None:
        self.assertTrue(SCRIPT.exists(), f"missing: {SCRIPT}")
        self.assertTrue(
            os.access(SCRIPT, os.X_OK), f"not executable: {SCRIPT}"
        )

    def test_noop_when_codex_manifest_absent(self) -> None:
        codex_manifest = REPO_ROOT / ".codex-plugin" / "plugin.json"
        self.assertFalse(
            codex_manifest.exists(),
            "W2 verdict is AGENTS.md-only; .codex-plugin/plugin.json should NOT exist",
        )
        result = subprocess.run(
            [str(SCRIPT)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("no-op", result.stdout.lower())

    def test_fails_safe_if_manifest_appears_without_sync_logic(self) -> None:
        """If .codex-plugin/plugin.json materialises while this script is still
        a no-op stub, exit 2 so the divergence is loud rather than silent."""
        with tempfile.TemporaryDirectory() as td:
            fake_root = Path(td) / "agent-learning-compounder"
            shutil.copytree(REPO_ROOT, fake_root, dirs_exist_ok=False)
            (fake_root / ".codex-plugin").mkdir(parents=True, exist_ok=True)
            (fake_root / ".codex-plugin" / "plugin.json").write_text('{"name":"x"}\n')
            fake_script = fake_root / "scripts" / "maintenance" / "sync-to-codex-plugin.sh"
            result = subprocess.run(
                [str(fake_script)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("not implemented", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()
