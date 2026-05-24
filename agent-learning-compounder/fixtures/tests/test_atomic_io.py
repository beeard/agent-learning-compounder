"""Tests for the durable-write primitives in bin/state_paths.

Pre-fix: three locations (refresh_learning_state.write_json,
refresh_learning_state._post_dedup, causal_probe._locked_probes) rewrote
their state files via seek + truncate + write inside an flock on the
data file's own fd. SIGKILL between truncate and write left the file
empty; the comment at refresh_learning_state acknowledged the gap. Also,
swapping in tmp+rename without a sidecar lockfile would lose updates
because the data file's inode lock does not survive its own os.replace.

Post-fix: atomic_write_text and atomic_rewrite write via a pid-tagged
.tmp file with fsync+os.replace, serialized by a sidecar `<path>.lock`
that is never renamed and so survives across replaces.
"""
from __future__ import annotations

import multiprocessing
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "bin"))
from state_paths import atomic_rewrite, atomic_write_text  # noqa: E402


def _concurrent_append_worker(args):
    """Append a unique marker line to a shared file under atomic_rewrite.
    Module-level so multiprocessing 'spawn' can pickle it."""
    path_str, marker = args
    # Re-import inside the worker; spawn does not inherit sys.path mutations.
    bin_dir = Path(__file__).resolve().parents[2] / "bin"
    sys.path.insert(0, str(bin_dir))
    from state_paths import atomic_rewrite as worker_atomic_rewrite  # noqa: E402
    path = Path(path_str)
    with worker_atomic_rewrite(path) as (current, commit):
        commit((current.rstrip("\n") + "\n" if current else "") + marker + "\n")
    return marker


class AtomicWriteTextBasic(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "subdir" / "state.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_parent_directories(self):
        atomic_write_text(self.path, "hello")
        self.assertTrue(self.path.exists())
        self.assertEqual(self.path.read_text(), "hello")

    def test_overwrites_existing_content(self):
        atomic_write_text(self.path, "first")
        atomic_write_text(self.path, "second")
        self.assertEqual(self.path.read_text(), "second")

    def test_leaves_no_tmp_orphans_after_success(self):
        atomic_write_text(self.path, "x")
        leftovers = list(self.path.parent.glob(f"{self.path.name}.*.tmp"))
        self.assertEqual(
            leftovers, [],
            msg=f"expected no .tmp orphans, found {leftovers}",
        )

    def test_creates_sidecar_lockfile(self):
        """The sidecar lockfile gets created on first write and stays. It's
        intentionally not cleaned up so a later writer's flock has a stable
        inode to lock."""
        atomic_write_text(self.path, "x")
        lock = self.path.parent / f"{self.path.name}.lock"
        self.assertTrue(lock.exists())

    def test_respects_mode_for_new_file(self):
        atomic_write_text(self.path, "secret", mode=0o600)
        actual_mode = self.path.stat().st_mode & 0o777
        self.assertEqual(actual_mode, 0o600)


class AtomicRewriteReadModifyWrite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "queue.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_yields_empty_string_when_path_does_not_exist(self):
        with atomic_rewrite(self.path) as (current, _):
            self.assertEqual(current, "")

    def test_yields_existing_content(self):
        self.path.write_text("initial content\n")
        with atomic_rewrite(self.path) as (current, _):
            self.assertEqual(current, "initial content\n")

    def test_commit_replaces_content(self):
        self.path.write_text("old\n")
        with atomic_rewrite(self.path) as (current, commit):
            commit(current + "new\n")
        self.assertEqual(self.path.read_text(), "old\nnew\n")

    def test_skipping_commit_leaves_file_untouched(self):
        self.path.write_text("preserved\n")
        with atomic_rewrite(self.path) as (current, _commit):
            self.assertEqual(current, "preserved\n")
            # Caller decides not to write. File must be unchanged on exit.
        self.assertEqual(self.path.read_text(), "preserved\n")


class AtomicWriteRefusesSymlinkTarget(unittest.TestCase):
    """B-6: the symlink check is now inside atomic_write_text /
    atomic_rewrite, run under the same lock that guards the write.
    Pre-fix callers ran an out-of-band assert_regular_file_destination
    before acquiring the lock -- a symlink swap in that gap was honored.
    """

    def test_atomic_write_text_refuses_symlink_at_destination(self):
        with tempfile.TemporaryDirectory() as td:
            real = Path(td) / "real-target"
            real.write_text("real content")
            link = Path(td) / "link"
            link.symlink_to(real)
            with self.assertRaises(ValueError) as cm:
                atomic_write_text(link, "new content")
            self.assertIn("symlink", str(cm.exception))
            # The real file must be untouched.
            self.assertEqual(real.read_text(), "real content")

    def test_atomic_rewrite_refuses_symlink_at_destination(self):
        with tempfile.TemporaryDirectory() as td:
            real = Path(td) / "real-target"
            real.write_text("real content")
            link = Path(td) / "link"
            link.symlink_to(real)
            with self.assertRaises(ValueError):
                with atomic_rewrite(link) as (_current, _commit):
                    self.fail("atomic_rewrite must not yield through a symlink")
            self.assertEqual(real.read_text(), "real content")

    def test_atomic_write_text_refuses_non_regular_file(self):
        # FIFO is a non-regular file the test can construct portably.
        import os as _os
        with tempfile.TemporaryDirectory() as td:
            fifo = Path(td) / "fifo"
            _os.mkfifo(fifo)
            with self.assertRaises(ValueError) as cm:
                atomic_write_text(fifo, "x")
            self.assertIn("non-regular", str(cm.exception))


class AtomicRewriteConcurrency(unittest.TestCase):
    """The whole point of the sidecar lockfile: parallel writers must
    serialize so no update is lost.

    Pre-fix (truncate-in-place under data-file flock): correct mutex but
    not crash-atomic.
    Naive tmp+rename (no sidecar): would lose updates because the data
    file's inode lock does not survive os.replace.
    Post-fix (sidecar lockfile + tmp+rename): correct on both counts.
    """

    def test_concurrent_appends_all_land(self):
        n_workers = 8
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "queue.jsonl"
            jobs = [(str(path), f"worker-{i}") for i in range(n_workers)]
            ctx = multiprocessing.get_context("spawn")
            with ctx.Pool(processes=n_workers) as pool:
                returned_markers = pool.map(_concurrent_append_worker, jobs)
            # Each worker appended one unique line. Every marker must show
            # up exactly once in the final file -- no lost updates.
            final_lines = [ln for ln in path.read_text().splitlines() if ln]
            self.assertEqual(
                sorted(final_lines), sorted(returned_markers),
                msg=(
                    f"expected all {n_workers} workers' markers to land; "
                    f"got {len(final_lines)} lines, {len(returned_markers)} returns. "
                    f"Without the sidecar lock, the data file's inode lock would not "
                    f"survive os.replace and some appends would clobber others."
                ),
            )


if __name__ == "__main__":
    unittest.main()
