"""Tests for B2: collect_hook_event rotation + 0o600 permissions."""

import importlib.machinery
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import time
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


def _load_collect_hook_event_module():
    """Import bin/collect_hook_event as a module so threads can call into it.

    The bin script has no .py extension, so we use SourceFileLoader directly
    (spec_from_file_location auto-loader lookup keys off the file suffix
    and returns no loader for an extensionless file).
    """
    bin_dir = str(ROOT / "bin")
    if bin_dir not in sys.path:
        sys.path.insert(0, bin_dir)
    bin_path = ROOT / "bin" / "collect_hook_event"
    loader = importlib.machinery.SourceFileLoader("collect_hook_event_mod", str(bin_path))
    spec = importlib.util.spec_from_loader("collect_hook_event_mod", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class CollectHookEventRotationTests(unittest.TestCase):
    def test_rotation_and_chmod(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            # Tiny threshold to force rotation on first append.
            (tmp / ".agent-learning.json").write_text(
                json.dumps({"retention": {"max_hook_event_bytes": 10}}),
                encoding="utf-8",
            )
            output = tmp / "hook-events.jsonl"
            # Pre-existing log past threshold.
            output.write_text("x" * 50, encoding="utf-8")

            event = json.dumps({
                "event": "test",
                "runtime": "unit",
                "session_id": "s1",
            })

            proc = subprocess.run(
                [
                    sys.executable, str(SCRIPTS / "collect_hook_event.py"),
                    "--repo", str(tmp),
                    "--output", str(output),
                    "--event", event,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)

            # A .bak should exist after rotation.
            backups = list(tmp.glob("hook-events.jsonl.*.bak"))
            self.assertTrue(backups, msg=f"no .bak file found in {list(tmp.iterdir())}")

            # New file exists and is mode 0o600.
            self.assertTrue(output.exists())
            mode = output.stat().st_mode & 0o777
            self.assertEqual(mode, 0o600, msg=f"mode is {oct(mode)}")

    def test_missing_config_uses_default(self):
        """No .agent-learning.json => default 5MB cap, no rotation, no error."""
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            output = tmp / "hook-events.jsonl"
            event = json.dumps({"event": "test", "runtime": "unit"})
            proc = subprocess.run(
                [
                    sys.executable, str(SCRIPTS / "collect_hook_event.py"),
                    "--repo", str(tmp),
                    "--output", str(output),
                    "--event", event,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertTrue(output.exists())
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_rotation_reads_bootstrap_state_config(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            state = tmp / ".agent-learning"
            state.mkdir()
            (state / "config.json").write_text(
                json.dumps({"retention": {"max_hook_event_bytes": 10}}),
                encoding="utf-8",
            )
            (tmp / ".agent-learning.json").write_text(
                json.dumps({"state_dir": str(state)}),
                encoding="utf-8",
            )
            output = tmp / "hook-events.jsonl"
            output.write_text("x" * 50, encoding="utf-8")

            event = json.dumps({"event": "test", "runtime": "unit"})
            proc = subprocess.run(
                [
                    sys.executable, str(SCRIPTS / "collect_hook_event.py"),
                    "--repo", str(tmp),
                    "--event", event,
                    "--output", str(output),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            backups = list(tmp.glob("hook-events.jsonl.*.bak"))
            self.assertTrue(backups)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "x" * 50)
            self.assertFalse(output.read_text(encoding="utf-8").startswith("x" * 50))


class CollectHookEventConcurrentRotationTests(unittest.TestCase):
    """Bug 1: concurrent writers must not have events lost during rotation.

    Exercises the rotate-vs-append race directly: many threads each
    open-write-close the live log in a tight loop while ONE thread fires
    rotate_if_needed at a low threshold. Pre-fix, the rotator's
    stat+rename ran outside any lock, so an appender that had already
    opened the fd would write into the renamed inode after rename. The
    assertion is total-conservation: union(live, all .baks) == events
    submitted, no dupes.

    Threads (not subprocesses) are used so the open/write window is wide
    enough to actually overlap with rename — subprocess startup dwarfs
    the racy window and hides the bug.
    """

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_collect_hook_event_module()

    def test_concurrent_writers_preserve_every_event(self):
        # Size the workload so total rotations stay within the retention
        # cap (MAX_HOOK_EVENT_BACKUPS=3) — otherwise the .bak pruner
        # deletes early backups by design and the test would conflate
        # retention loss with concurrency loss. With 240 events × ~170
        # bytes ≈ 40_800 bytes, max_bytes=15_000 yields ~2-3 rotations.
        events_per_writer = 30
        n_writers = 8
        total_events = events_per_writer * n_writers  # 240
        max_bytes = 15_000

        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            output = tmp / "hook-events.jsonl"
            mod = self.mod

            errors: list[str] = []
            written_markers: list[str] = []
            written_lock = threading.Lock()
            barrier = threading.Barrier(n_writers + 1)
            stop = threading.Event()

            def appender(thread_id: int):
                try:
                    barrier.wait(timeout=10)
                    for i in range(events_per_writer):
                        marker = f"t{thread_id:02d}-e{i:02d}"
                        event = mod.normalize_event({
                            "event": "concurrent",
                            "runtime": "unit",
                            "session_id": "s1",
                            "correlation_id": marker,
                        }, tmp)
                        rendered = json.dumps(event, sort_keys=True, separators=(",", ":"))
                        # Mirror the production path: take LOCK_SH around
                        # the open+write window. If the fix is missing
                        # (no lock), the rotator can rename + the pruner
                        # can unlink the backup containing this write
                        # before it lands, deleting the event entirely.
                        with mod._rotation_lock(output, exclusive=False):
                            fd = os.open(
                                str(output),
                                os.O_WRONLY | os.O_APPEND | os.O_CREAT,
                                0o600,
                            )
                            try:
                                # Small sleep widens the racy window so the
                                # bug is reproducible at unit-test scale.
                                # Under the fix, LOCK_SH prevents rotation
                                # from interleaving regardless of width.
                                time.sleep(0.0005)
                                os.write(fd, (rendered + "\n").encode("utf-8"))
                            finally:
                                os.close(fd)
                        with written_lock:
                            written_markers.append(marker)
                except Exception as exc:  # pragma: no cover - surfaced via errors
                    errors.append(f"appender {thread_id}: {exc!r}")

            def rotator():
                try:
                    barrier.wait(timeout=10)
                    # Spin rotate_if_needed continuously. Each call takes
                    # LOCK_EX under the fix, so it serializes cleanly with
                    # appenders.
                    while not stop.is_set():
                        mod.rotate_if_needed(output, max_bytes)
                        time.sleep(0.0002)
                except Exception as exc:  # pragma: no cover
                    errors.append(f"rotator: {exc!r}")

            threads = [threading.Thread(target=appender, args=(i,)) for i in range(n_writers)]
            rot_thread = threading.Thread(target=rotator)
            for t in threads:
                t.start()
            rot_thread.start()
            for t in threads:
                t.join(timeout=60)
            stop.set()
            rot_thread.join(timeout=5)

            self.assertEqual(errors, [], msg="thread errors")
            self.assertEqual(len(written_markers), total_events)

            # Collect every line across live log + every retained .bak.
            # The sidecar .lock is not JSONL — skip it.
            collected_lines: list[str] = []
            for path in sorted(tmp.iterdir()):
                name = path.name
                if not (name == output.name or name.startswith(output.name + ".")):
                    continue
                if name.endswith(".lock"):
                    continue
                try:
                    collected_lines.extend(
                        ln for ln in path.read_text(encoding="utf-8").splitlines() if ln
                    )
                except OSError:
                    pass

            seen_markers: list[str] = []
            for line in collected_lines:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cid = row.get("correlation_id")
                if isinstance(cid, str) and cid.startswith("t"):
                    seen_markers.append(cid)

            dupes = {m: seen_markers.count(m) for m in set(seen_markers) if seen_markers.count(m) > 1}
            self.assertFalse(dupes, msg=f"duplicate events found: {dupes}")
            missing = sorted(set(written_markers) - set(seen_markers))
            self.assertEqual(
                missing, [],
                msg=(
                    f"events lost during concurrent rotation: "
                    f"{len(missing)} of {len(written_markers)} missing; "
                    f"first few: {missing[:5]}"
                ),
            )


if __name__ == "__main__":
    unittest.main()
