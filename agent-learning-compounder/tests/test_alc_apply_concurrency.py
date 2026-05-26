from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

from alc_apply_dispatch import sha256_bytes
from state_handle import StateHandle


class AlcApplyConcurrencyTests(unittest.TestCase):
    def test_two_concurrent_apply_invocations_allow_one_winner(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            (repo / ".agent-learning.json").write_text(json.dumps({"state_dir": str(root / "state")}), encoding="utf-8")
            state = StateHandle.for_repo(repo)
            (state.repo_state_dir / "patches").mkdir(parents=True, exist_ok=True)
            target = repo / "skills" / "demo" / "SKILL.md"
            target.parent.mkdir(parents=True)
            original = "---\nname: test-skill\ndescription: Test skill\n---\n\nold\n"
            changed = original.replace("old", "new")
            target.write_text(original, encoding="utf-8")
            patch_id = "race"
            (state.repo_state_dir / "patches" / f"{patch_id}.json").write_text(
                json.dumps(
                    {
                        "patch_id": patch_id,
                        "skill_manage_op": {
                            "action": "patch",
                            "target_type": "skill",
                            "target": "skills/demo/SKILL.md",
                            "old_string": original,
                            "new_string": changed,
                        },
                        "preflight": {"expected_target_sha256": sha256_bytes(original.encode())},
                        "revert_op": {
                            "action": "patch",
                            "target_type": "skill",
                            "target": "skills/demo/SKILL.md",
                            "old_string": changed,
                            "new_string": original,
                        },
                    }
                ),
                encoding="utf-8",
            )

            def run_once() -> int:
                result = subprocess.run(
                    [sys.executable, str(BIN / "alc_apply"), "--repo", str(repo), "--patch", patch_id, "--write"],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env={**os.environ, "PYTHONPATH": str(BIN)},
                    check=False,
                )
                return result.returncode

            with ThreadPoolExecutor(max_workers=2) as pool:
                codes = sorted(pool.map(lambda _: run_once(), range(2)))

            self.assertEqual(codes, [0, 2])
            self.assertEqual(target.read_text(encoding="utf-8"), changed)


if __name__ == "__main__":
    unittest.main()
