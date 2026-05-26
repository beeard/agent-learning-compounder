from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

from alc_apply_dispatch import sha256_bytes
from state_handle import StateHandle


class AlcApplyPathTests(unittest.TestCase):
    def _repo(self, root: Path) -> tuple[Path, StateHandle]:
        repo = root / "repo"
        repo.mkdir()
        state_root = root / "state"
        (repo / ".agent-learning.json").write_text(json.dumps({"state_dir": str(state_root)}), encoding="utf-8")
        state = StateHandle.for_repo(repo)
        (state.repo_state_dir / "patches").mkdir(parents=True, exist_ok=True)
        return repo, state

    def _run_patch(self, repo: Path, state: StateHandle, target: str, patch_id: str = "bad-path") -> subprocess.CompletedProcess[str]:
        payload = {
            "patch_id": patch_id,
            "skill_manage_op": {
                "action": "write_file",
                "target_type": "skill",
                "target": target,
                "content": "---\nname: test-skill\ndescription: x\n---\n",
            },
            "preflight": {"expected_target_sha256": sha256_bytes(b"")},
            "revert_op": {"action": "write_file", "target_type": "skill", "target": target, "content": ""},
        }
        (state.repo_state_dir / "patches" / f"{patch_id}.json").write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(BIN / "alc_apply"), "--repo", str(repo), "--patch", patch_id, "--write"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, "PYTHONPATH": str(BIN)},
            check=False,
        )

    def test_rejects_absolute_target_outside_allowed_roots(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, state = self._repo(Path(td))
            result = self._run_patch(repo, state, "/etc/hosts")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("outside allowed_roots", result.stderr)

    def test_rejects_target_escape_via_dotdot(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, state = self._repo(Path(td))
            result = self._run_patch(repo, state, "skills/../../outside.md")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("outside allowed_roots", result.stderr)

    def test_rejects_symlink_target(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, state = self._repo(Path(td))
            outside = Path(td) / "outside.md"
            outside.write_text("", encoding="utf-8")
            (repo / "skills").mkdir()
            (repo / "skills" / "link.md").symlink_to(outside)
            result = self._run_patch(repo, state, "skills/link.md")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("symlink", result.stderr)

    def test_rejects_copy_to_clipboard_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, state = self._repo(Path(td))
            patch_id = "clipboard"
            (state.repo_state_dir / "patches" / f"{patch_id}.json").write_text(
                json.dumps({"patch_id": patch_id, "apply_strategy": "copy_to_clipboard", "skill_manage_op": {}}),
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(BIN / "alc_apply"), "--repo", str(repo), "--patch", patch_id, "--write"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, "PYTHONPATH": str(BIN)},
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("copy_to_clipboard", result.stderr)


if __name__ == "__main__":
    unittest.main()
