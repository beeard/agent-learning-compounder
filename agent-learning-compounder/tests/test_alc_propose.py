from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
import sys
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

from state_handle import StateHandle
import alc_propose


class AlcProposeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir(parents=True, exist_ok=True)
        self.state = StateHandle.for_repo(self.repo)
        self.state.repo_state_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _read_rows(self, path: Path) -> list[dict]:
        if not path.is_file():
            return []
        rows: list[dict] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    def _event_rows(self) -> list[dict]:
        return self._read_rows(self.state.events_jsonl)

    def test_propose_gate_appends_queue_row_and_event(self) -> None:
        result = alc_propose.propose_gate(
            self.state,
            domain="tests",
            category="quality",
            gate="Always validate output and exit code.",
            evidence="Observed a flake in regression before.",
        )

        queue_rows = self._read_rows(self.state.repo_state_dir / "improvement-queue.jsonl")
        self.assertEqual(len(queue_rows), 1)
        self.assertEqual(queue_rows[0]["id"], result["queue_id"])

        events = self._event_rows()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event"], "gate_proposed")

    def test_propose_apply_returns_token_and_no_patch_mutation(self) -> None:
        patch_dir = self.state.repo_state_dir / "patches"
        patch_dir.mkdir(parents=True, exist_ok=True)
        patch = {"patch_id": "patch-1", "status": "pending"}
        patch_path = patch_dir / "patch-1.json"
        patch_path.write_text(json.dumps(patch, sort_keys=True), encoding="utf-8")

        before = patch_path.read_text(encoding="utf-8")
        result = alc_propose.propose_apply(self.state, "patch-1")

        after = patch_path.read_text(encoding="utf-8")
        self.assertEqual(before, after)
        self.assertIn("patch-1", result["command"])
        self.assertIn("--patch", result["command"])
        self.assertIn("--write", result["command"])
        # Token NOT returned to callers (alc_apply has no token-validation
        # surface; exposing one would imply a security guarantee that does
        # not exist). An audit nonce IS carried in the apply_proposed event
        # payload for telemetry correlation only.
        self.assertNotIn("token", result)
        events = self._event_rows()
        self.assertEqual(events[-1]["event"], "apply_proposed")
        self.assertTrue(events[-1]["payload"].get("audit_nonce"))
        self.assertNotIn(events[-1]["payload"]["audit_nonce"], result["command"])

    def test_report_outcome_emits_deterministic_event_id(self) -> None:
        first = alc_propose.report_outcome(self.state, "rec-1", "helpful", "passed all checks")
        second = alc_propose.report_outcome(self.state, "rec-1", "helpful", "passed all checks")
        self.assertEqual(first, second)
        events = self._event_rows()
        self.assertEqual(events[-1]["event_id"], first)

        expected = alc_propose.EventV4.deterministic_id(
            actor_kind="eval_judge",
            event_type="outcome_reported",
            payload_key="rec-1:helpful:passed all checks",
        )
        self.assertEqual(first, expected)

    def test_report_agent_event_emits_agent_dispatch_event(self) -> None:
        event_id = alc_propose.report_agent_event(
            self.state,
            kind="dispatched",
            actor_name="codex-runner",
            telemetry={"agent_model": "gpt-5"},
        )
        self.assertIsInstance(event_id, str)

        events = self._event_rows()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event"], "agent_dispatch_dispatched")

    def test_mark_patch_status_updates_file_and_event(self) -> None:
        patch_dir = self.state.repo_state_dir / "patches"
        patch_dir.mkdir(parents=True)
        patch_path = patch_dir / "p-1.json"
        patch_path.write_text(json.dumps({"patch_id": "p-1", "status": "pending"}), encoding="utf-8")

        result = alc_propose.mark_patch_status(self.state, "p-1", "rejected")
        self.assertEqual(result["patch_id"], "p-1")
        self.assertEqual(result["status"], "rejected")
        self.assertTrue(result["visibility"]["updated"])

        payload = json.loads(patch_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "rejected")

        events = self._event_rows()
        self.assertEqual(events[-1]["event"], "patch_rejected")
        self.assertEqual(events[-1]["payload"]["patch_id"], "p-1")

    def test_report_outcome_is_visible_to_query_after_write(self) -> None:
        event_id = alc_propose.report_outcome(self.state, "rec-1", "helpful", "visible immediately")

        conn = sqlite3.connect(self.state.events_sqlite)
        try:
            count = conn.execute("SELECT COUNT(*) FROM events WHERE event_id = ?", (event_id,)).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 1)

    def test_concurrent_propose_gate_calls_serialized(self) -> None:
        total = 40

        def worker(i: int) -> None:
            alc_propose.propose_gate(
                self.state,
                domain="tests",
                category="quality",
                gate=f"gate-{i}",
            )

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(total)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        queue_rows = self._read_rows(self.state.repo_state_dir / "improvement-queue.jsonl")
        self.assertEqual(len(queue_rows), total)
        self.assertEqual(len({row["id"] for row in queue_rows}), total)
        self.assertEqual(len(self._event_rows()), total)


if __name__ == "__main__":
    unittest.main()
