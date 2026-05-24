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


if __name__ == "__main__":
    unittest.main()
