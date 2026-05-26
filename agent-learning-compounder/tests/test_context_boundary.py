from __future__ import annotations

import base64
import os
import pathlib
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import event_writer


def _event(payload: dict[str, object], event: str = "unit_boundary") -> dict[str, object]:
    return {
        "event": event,
        "actor": {"kind": "main_agent", "name": "boundary-test"},
        "payload": payload,
    }


class ContextBoundaryTests(unittest.TestCase):
    def assertBoundaryRejects(self, payload: dict[str, object]) -> None:
        with self.assertRaises(ValueError):
            event_writer.write_event(_event(payload), source="background")

    def test_enforce_boundary_rejects_secret(self) -> None:
        self.assertBoundaryRejects({"note": "token sk-fake-key must not persist"})

    def test_enforce_boundary_rejects_abs_path(self) -> None:
        self.assertBoundaryRejects({"path": "/home/tth/secrets"})

    def test_enforce_boundary_rejects_oversized_string(self) -> None:
        self.assertBoundaryRejects({"field": "x" * 500})

    def test_enforce_boundary_allows_revert_blob_for_patch_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.environ.get("AGENT_LEARNING_STATE_DIR")
            os.environ["AGENT_LEARNING_STATE_DIR"] = tmp
            try:
                blob = base64.b64encode(b"x" * 1200).decode("ascii")
                event_id = event_writer.write_event(
                    _event({"revert_bytes_b64": blob}, event="patch_reverted"),
                    source="apply",
                )
                self.assertTrue(event_id.startswith("evt_"))
                self.assertGreater((pathlib.Path(tmp) / "events.jsonl").stat().st_size, 0)
            finally:
                if previous is None:
                    os.environ.pop("AGENT_LEARNING_STATE_DIR", None)
                else:
                    os.environ["AGENT_LEARNING_STATE_DIR"] = previous

    def test_enforce_boundary_rejects_raw_transcript_marker(self) -> None:
        self.assertBoundaryRejects({"chunk": "assistant: here is a raw transcript line"})
        self.assertBoundaryRejects({"chunk": "user: raw transcript line"})

    def test_write_event_rejects_bad_event_before_disk_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.environ.get("AGENT_LEARNING_STATE_DIR")
            os.environ["AGENT_LEARNING_STATE_DIR"] = tmp
            try:
                path = pathlib.Path(tmp) / "events.jsonl"
                with self.assertRaises(ValueError):
                    event_writer.write_event(_event({"path": "/home/tth/secrets.txt"}), source="background")
                self.assertFalse(path.exists(), "boundary failure must not create events.jsonl")
            finally:
                if previous is None:
                    os.environ.pop("AGENT_LEARNING_STATE_DIR", None)
                else:
                    os.environ["AGENT_LEARNING_STATE_DIR"] = previous


if __name__ == "__main__":
    unittest.main()
