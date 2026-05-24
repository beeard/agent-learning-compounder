"""Test for H4: hook-event writer must serialize concurrent appenders.

Pre-fix: collect_hook_event.main held LOCK_SH on the sidecar lock during
the append, relying on O_APPEND being atomic up to PIPE_BUF (4096B on
Linux). A full v2 event carrying MAX_GATE_LOADED_IDS * MAX_GATE_LOADED_ID_LEN
== 4096B for gate_loaded_ids alone, plus probe_decisions, headers, and
JSON overhead, easily exceeds PIPE_BUF. Two concurrent appenders writing
oversized payloads interleaved bytes mid-line; readers saw torn JSON.

Post-fix: LOCK_EX serializes appenders. Each append completes whole
before the next begins; every line in the resulting file parses cleanly.

This test exercises the actual subprocess so the test reproduces the
real OS-level write semantics rather than a Python in-process simulation.
"""
from __future__ import annotations

import json
import multiprocessing
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COLLECT = REPO_ROOT / "bin" / "collect_hook_event"


def _collect_worker(args):
    """Invoke collect_hook_event with a large v2 instructions_loaded payload.
    Module-level so multiprocessing 'spawn' can pickle it."""
    output_path, cid_suffix = args
    # Build a payload that exceeds PIPE_BUF. 64 gate_ids x 64 chars each
    # is the cap, so we hit the worst case.
    gate_ids = [f"gid{i:061d}" for i in range(64)]
    event = {
        "schema_version": 2,
        "event": "instructions_loaded",
        "correlation_id": f"sess-{cid_suffix}",
        "gate_loaded_ids": gate_ids,
        "probe_decisions": [{"gate_id": gid, "decision": "load"} for gid in gate_ids[:16]],
    }
    proc = subprocess.run(
        [str(COLLECT), "--output", output_path, "--event", json.dumps(event)],
        capture_output=True, text=True, check=False,
    )
    return proc.returncode, proc.stderr


class CollectHookEventConcurrentAppend(unittest.TestCase):
    def test_oversized_events_appear_as_whole_lines(self):
        n_workers = 6
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "hook-events.jsonl"
            output.write_text("")  # ensure parent dir exists
            jobs = [(str(output), str(i)) for i in range(n_workers)]
            ctx = multiprocessing.get_context("spawn")
            with ctx.Pool(processes=n_workers) as pool:
                results = pool.map(_collect_worker, jobs)

            for rc, err in results:
                self.assertEqual(rc, 0, msg=f"appender failed: {err!r}")

            # Every line in the resulting file must be valid JSON. Pre-fix
            # the oversize payloads + LOCK_SH would produce torn lines.
            lines = [ln for ln in output.read_text().splitlines() if ln]
            self.assertEqual(
                len(lines), n_workers,
                msg=(
                    f"expected {n_workers} whole lines, got {len(lines)} "
                    f"after concurrent appends with payloads > PIPE_BUF"
                ),
            )
            for i, line in enumerate(lines):
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    self.fail(
                        f"line {i} is not valid JSON (torn write): {exc}\n"
                        f"{line[:200]!r}"
                    )
                self.assertEqual(row.get("event"), "instructions_loaded")


if __name__ == "__main__":
    unittest.main()
