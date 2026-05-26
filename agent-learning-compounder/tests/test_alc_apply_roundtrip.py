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


def _state(repo: Path, state_root: Path) -> StateHandle:
    (repo / ".agent-learning.json").write_text(json.dumps({"state_dir": str(state_root)}), encoding="utf-8")
    state = StateHandle.for_repo(repo)
    (state.repo_state_dir / "patches").mkdir(parents=True, exist_ok=True)
    return state


def _skill(text: str) -> str:
    return f"---\nname: test-skill\ndescription: Test skill\n---\n\n{text}\n"


class AlcApplyRoundtripTests(unittest.TestCase):
    def test_apply_revert_roundtrip_via_patch_applied_event(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            state = _state(repo, root / "state")
            target = repo / "skills" / "demo" / "SKILL.md"
            target.parent.mkdir(parents=True)
            original = _skill("old")
            changed = _skill("new")
            target.write_text(original, encoding="utf-8")
            patch_id = "roundtrip-1"
            (state.repo_state_dir / "patches" / f"{patch_id}.json").write_text(
                json.dumps(
                    {
                        "patch_id": patch_id,
                        "status": "pending",
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
            env = {**os.environ, "PYTHONPATH": str(BIN)}
            apply_result = subprocess.run(
                [sys.executable, str(BIN / "alc_apply"), "--repo", str(repo), "--patch", patch_id, "--write"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                check=False,
            )
            self.assertEqual(apply_result.returncode, 0, apply_result.stderr)
            self.assertEqual(target.read_text(encoding="utf-8"), changed)

            second = subprocess.run(
                [sys.executable, str(BIN / "alc_apply"), "--repo", str(repo), "--patch", patch_id, "--write"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                check=False,
            )
            self.assertEqual(second.returncode, 2)

            revert_result = subprocess.run(
                [sys.executable, str(BIN / "alc_apply"), "--repo", str(repo), "--patch", patch_id, "--revert"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                check=False,
            )
            self.assertEqual(revert_result.returncode, 0, revert_result.stderr)
            self.assertEqual(target.read_text(encoding="utf-8"), original)
            events = [json.loads(line) for line in state.events_jsonl.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([e["event"] for e in events], ["patch_applied", "patch_reverted"])
            self.assertEqual(events[1]["parent_event_id"], events[0]["event_id"])


if __name__ == "__main__":
    unittest.main()
