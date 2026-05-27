"""Tests for P2A-A: queue_dedup trigram-Jaccard semantic dedup."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEDUP = REPO_ROOT / "bin" / "queue_dedup"


class QueueDedup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.queue = Path(self.tmp.name) / "improvement-queue.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, rows):
        self.queue.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    def _run(self, *args):
        proc = subprocess.run(
            [str(DEDUP), "--queue", str(self.queue), "--backend", "trigram",
             "--threshold", "0.80", *args],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return [json.loads(line) for line in self.queue.read_text().splitlines() if line]

    def test_dedups_near_identical_text(self):
        self._write([
            {"id": "a", "text": "Re-read AGENTS.md before changing the repo."},
            {"id": "b", "text": "Re-read AGENTS.md before modifying the repo."},
        ])
        rows = self._run()
        self.assertEqual(len(rows), 1)
        self.assertIn(rows[0]["id"], {"a", "b"})

    def test_keeps_semantically_distinct(self):
        self._write([
            {"id": "a", "text": "Re-read AGENTS.md before changing the repo."},
            {"id": "b", "text": "Run pytest with -x before pushing."},
        ])
        rows = self._run()
        self.assertEqual(len(rows), 2)

    def test_preserves_oldest_id_on_dedup(self):
        self._write([
            {"id": "older", "text": "Always quote one line of deploy output.",
             "ts": "2026-01-01T00:00:00Z"},
            {"id": "newer", "text": "Always quote a line of deploy output.",
             "ts": "2026-02-01T00:00:00Z"},
        ])
        rows = self._run("--keep", "oldest")
        self.assertEqual(rows[0]["id"], "older")

    def test_dry_run_does_not_modify_queue(self):
        original = [
            {"id": "a", "text": "Re-read AGENTS.md before changing the repo."},
            {"id": "b", "text": "Re-read AGENTS.md before modifying the repo."},
        ]
        self._write(original)
        proc = subprocess.run(
            [str(DEDUP), "--queue", str(self.queue), "--backend", "trigram",
             "--threshold", "0.80", "--dry-run"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        on_disk = [json.loads(line) for line in self.queue.read_text().splitlines() if line]
        self.assertEqual(on_disk, original)
        self.assertIn("would_remove=1", proc.stdout)

    def test_does_not_collapse_across_distinct_domains(self):
        """Two ``operator_proposed_gate`` rows with identical ``text`` but
        different ``domain`` must both survive — the gate proposal is a
        legitimately distinct candidate for each domain."""
        self._write([
            {"id": "a", "kind": "operator_proposed_gate", "domain": "cloudflare",
             "text": "Always quote one line of deploy output.",
             "ts": "2026-01-01T00:00:00Z"},
            {"id": "b", "kind": "operator_proposed_gate", "domain": "rails",
             "text": "Always quote one line of deploy output.",
             "ts": "2026-02-01T00:00:00Z"},
        ])
        rows = self._run()
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["id"] for r in rows}, {"a", "b"})

    def test_does_not_collapse_across_distinct_skills(self):
        """Two ``gate_retirement_candidate`` rows with identical
        ``candidate_adjustment`` wording but different ``skill`` must both
        survive — retirement is per-skill."""
        self._write([
            {"id": "a", "kind": "gate_retirement_candidate", "skill": "frontend-design",
             "text": "Retire: gate no longer triggers in last 30 sessions.",
             "ts": "2026-01-01T00:00:00Z"},
            {"id": "b", "kind": "gate_retirement_candidate", "skill": "build-mcp-server",
             "text": "Retire: gate no longer triggers in last 30 sessions.",
             "ts": "2026-02-01T00:00:00Z"},
        ])
        rows = self._run()
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["id"] for r in rows}, {"a", "b"})

    def test_still_collapses_within_same_bucket(self):
        """Within the same (kind, domain, skill) bucket, near-paraphrases
        must still collapse — the bucketing only widens the safe set, it
        doesn't disable dedup."""
        self._write([
            {"id": "a", "kind": "operator_proposed_gate", "domain": "cloudflare",
             "text": "Always quote one line of deploy output.",
             "ts": "2026-01-01T00:00:00Z"},
            {"id": "b", "kind": "operator_proposed_gate", "domain": "cloudflare",
             "text": "Always quote a line of deploy output.",
             "ts": "2026-02-01T00:00:00Z"},
        ])
        rows = self._run("--keep", "oldest")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "a")

    def test_symlinked_queue_rejected(self):
        import os
        real = self.queue.with_suffix(".real.jsonl")
        real.write_text(json.dumps({"id": "a", "text": "hi"}) + "\n")
        os.symlink(real, self.queue)
        proc = subprocess.run(
            [str(DEDUP), "--queue", str(self.queue), "--backend", "trigram",
             "--threshold", "0.80"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(real.read_text().strip(), json.dumps({"id": "a", "text": "hi"}))


class RefreshWiresDedup(unittest.TestCase):
    """refresh_learning_state should invoke queue_dedup after appending candidates."""

    def test_refresh_emits_dedup_count(self):
        import shutil
        import sys

        fixture_src = REPO_ROOT / "fixtures" / "eval-fixtures" / "mini-repo"
        seed = fixture_src / "seed"

        sys.path.insert(0, str(REPO_ROOT / "bin"))
        import state_handle  # type: ignore

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            # Copy everything except seed/ into the staged repo
            shutil.copytree(fixture_src, repo, ignore=shutil.ignore_patterns("seed"))

            rid = state_handle.repo_id(repo)
            state_root = repo / ".agent-learning"
            state_dir = state_root / "repos" / rid
            state_dir.mkdir(parents=True, exist_ok=True)
            for name in (
                "config.json",
                "baseline.json",
                "domain-rules.active.json",
                "skill-map.json",
            ):
                shutil.copy(seed / name, state_dir / name)
            (state_dir / "improvement-queue.jsonl").write_text(
                (seed / "improvement-queue-near-dupes.jsonl").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            # The state root also expects a config.json so refresh can read runtime.
            shutil.copy(seed / "config.json", state_root / "config.json")

            proc = subprocess.run(
                [
                    str(REPO_ROOT / "bin" / "refresh_learning_state"),
                    "--repo", str(repo),
                    "--state-dir", str(state_root),
                ],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            # Combined stdout+stderr should report dedup_removed somewhere
            output = proc.stdout + proc.stderr
            self.assertIn("dedup_removed", output)

            # Verify queue actually got deduped
            queue = state_dir / "improvement-queue.jsonl"
            rows = [json.loads(ln) for ln in queue.read_text().splitlines() if ln]
            self.assertEqual(len(rows), 1, f"expected 1 row, got {len(rows)}")
            # Oldest (id='a') should survive
            self.assertEqual(rows[0]["id"], "a")


if __name__ == "__main__":
    unittest.main()
