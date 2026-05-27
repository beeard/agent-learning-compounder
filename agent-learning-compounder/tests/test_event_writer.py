from __future__ import annotations

import base64
import importlib
import json
import os
import pathlib
import sys
import tempfile
import threading
import unittest
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

import event_writer
from state_handle import StateHandle


class EventWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = tempfile.TemporaryDirectory()
        os.environ["AGENT_LEARNING_STATE_DIR"] = self.state.name

    def tearDown(self) -> None:
        self.state.cleanup()
        os.environ.pop("AGENT_LEARNING_STATE_DIR", None)

    def _event_path(self) -> pathlib.Path:
        return pathlib.Path(self.state.name) / "events.jsonl"

    def _row(self, **extra):
        base = {
            "event": "test",
            "schema_version": 4,
            "payload": {"value": "ok"},
        }
        base.update(extra)
        return base

    def test_write_event_returns_event_id(self):
        row = self._row(event_id="evt-test-1", event="hooked")
        event_id = event_writer.write_event(row, source="hook")
        self.assertEqual(event_id, "evt-test-1")
        line = self._event_path().read_text(encoding="utf-8").strip()
        payload = json.loads(line)
        self.assertEqual(payload["event_id"], "evt-test-1")
        self.assertEqual(payload["payload"]["_write_scope"], "legacy_state_dir_fallback")

    def test_write_event_auto_id_when_absent_and_fallback_true(self):
        row = self._row(event="apply")
        event_id = event_writer.write_event(row, source="hook")
        self.assertTrue(event_id.startswith("evt_"))

    def test_write_event_with_explicit_state_handle(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp) / "repo"
            repo.mkdir()
            state = StateHandle.for_repo(repo, state_dir=pathlib.Path(tmp) / "state")
            event_id = event_writer.write_event(
                self._row(event_id="evt-explicit", event="hooked"),
                source="hook",
                state=state,
            )
            payload = json.loads(state.events_jsonl.read_text(encoding="utf-8").strip())
            self.assertEqual(event_id, "evt-explicit")
            self.assertEqual(payload["event_id"], "evt-explicit")
            self.assertEqual(payload["payload"]["_write_scope"], "project_state_handle")
            self.assertTrue(state.events_jsonl.exists())

    def test_write_event_rejects_missing_id_when_fallback_disabled(self):
        with self.assertRaises(ValueError):
            event_writer.write_event(self._row(), source="hook", auto_id_fallback=False)

    def test_write_event_with_repo_param(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp) / "repo"
            repo.mkdir()
            with mock.patch.dict(os.environ, {"AGENT_LEARNING_STATE_DIR": str(pathlib.Path(tmp) / "other-state")}):
                expected = StateHandle.for_repo(repo)
                event_writer.write_event(self._row(event_id="evt-repo", event="hooked"), source="hook", repo=repo)

            payload = json.loads(expected.events_jsonl.read_text(encoding="utf-8").strip())
            self.assertEqual(payload["event_id"], "evt-repo")
            self.assertEqual(payload["payload"]["_write_scope"], "project_repo")

    def test_write_event_with_explicit_state_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "explicit-state-root"
            root.mkdir(parents=True)
            event_id = event_writer.write_event(
                self._row(event_id="evt-root", event="hooked"),
                source="hook",
                state_root=root,
            )
            payload = json.loads((root / "events.jsonl").read_text(encoding="utf-8").strip())
            self.assertEqual(event_id, "evt-root")
            self.assertEqual(payload["event_id"], "evt-root")
            self.assertEqual(payload["payload"]["_write_scope"], "legacy_state_root")

    def test_write_event_rejects_ambiguous_target_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp) / "repo"
            repo.mkdir()
            state = StateHandle.for_repo(repo, state_dir=pathlib.Path(tmp) / "state")

            with self.assertRaisesRegex(ValueError, "ambiguous event write target"):
                event_writer.write_event(self._row(event_id="evt-conflict"), source="hook", state=state, repo=repo)

            with self.assertRaisesRegex(ValueError, "ambiguous event write target"):
                event_writer.write_event(
                    self._row(event_id="evt-conflict-2"),
                    source="hook",
                    repo=repo,
                    state_root=pathlib.Path(tmp) / "root",
                )

    def test_write_event_rejects_symlink_event_path(self):
        state_root = pathlib.Path(self.state.name) / "symlink-state"
        events_path = state_root / "events.jsonl"
        state_root.mkdir(parents=True, exist_ok=True)
        events_path.symlink_to("/dev/null")
        with self.assertRaises(ValueError):
            event_writer.write_event(self._row(event_id="evt-symlink", event="hooked"), source="hook", state_root=state_root)

    def test_write_event_appends_to_jsonl(self):
        event_writer.write_event(self._row(event="one", event_id="evt-1"), source="hook")
        event_writer.write_event(self._row(event="two", event_id="evt-2"), source="hook")
        event_writer.write_event(self._row(event="three", event_id="evt-3"), source="hook")
        lines = [line for line in self._event_path().read_text(encoding="utf-8").splitlines() if line]
        self.assertEqual(len(lines), 3)

    def test_write_event_rejects_secret_in_payload(self):
        with self.assertRaises(ValueError):
            event_writer.write_event(self._row(payload={"token": "sk-fake-key"}, event="x"), source="hook")

    def test_write_event_rejects_absolute_host_path(self):
        with self.assertRaises(ValueError):
            event_writer.write_event(self._row(payload={"path": "/home/user/secrets"}, event="x"), source="hook")

    def test_write_event_rejects_overlong_string(self):
        with self.assertRaises(ValueError):
            event_writer.write_event(self._row(payload={"text": "x" * 300}, event="x"), source="hook")

    def test_write_event_allows_revert_blob_for_apply(self):
        blob = base64.b64encode(b"x" * 1536).decode("ascii")
        event_id = event_writer.write_event(
            self._row(
                event="patch_applied",
                payload={"original_bytes_b64": blob},
            ),
            source="apply",
        )
        self.assertTrue(event_id.startswith("evt_"))

    def test_write_events_batch_single_flock(self):
        rows = [self._row(event=f"row-{i}", event_id=f"evt-{i}") for i in range(100)]
        with mock.patch.object(event_writer, "_acquire_state_lock", wraps=event_writer._acquire_state_lock) as lock_mock:
            ids = event_writer.write_events_batch(rows, source="hook")
            self.assertEqual(len(ids), len(rows))
            self.assertEqual(lock_mock.call_count, 1)

    def test_concurrent_writes_serialized_via_flock(self):
        written: list[str] = []
        lock = threading.Lock()

        def writer(prefix: str) -> None:
            for i in range(50):
                with lock:
                    pass
                event_writer.write_event(self._row(event=f"{prefix}-{i}", event_id=f"evt-{prefix}-{i}"), source="hook")
                written.append(f"evt-{prefix}-{i}")

        t1 = threading.Thread(target=writer, args=("a",))
        t2 = threading.Thread(target=writer, args=("b",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        lines = [line for line in self._event_path().read_text(encoding="utf-8").splitlines() if line]
        self.assertEqual(len(lines), 100)

        parsed = []
        for line in lines:
            parsed.append(json.loads(line).get("event_id"))
        self.assertEqual(len(parsed), 100)
        self.assertEqual(set(parsed), set(written))
        self.assertEqual(len(set(parsed)), 100)

    def test_apply_revert_round_trip_via_event_id(self):
        # apply/eval/sync callers MUST pre-compute deterministic_id and pass auto_id_fallback=False
        # per U5.5.0a contract; this round-trip test enforces that contract.
        actor_kind = "operator"
        event_type = "patch_reverted"
        payload_key = "patch-abc:1700000000"
        expected = event_writer.EventV4.deterministic_id(
            actor_kind=actor_kind, event_type=event_type, payload_key=payload_key
        )
        row = {
            "event": event_type,
            "source": "apply",
            "schema_version": 4,
            "actor": {"kind": actor_kind, "name": "alc_apply"},
            "telemetry": {},
            "payload": {"original_bytes_b64": base64.b64encode(b"payload" * 200).decode("ascii")},
            "ts": "2023-11-14T22:13:20+00:00",
            "event_id": expected,
        }
        event_id = event_writer.write_event(row, source="apply", auto_id_fallback=False)
        self.assertEqual(event_id, expected)

        lines = [json.loads(ln) for ln in self._event_path().read_text(encoding="utf-8").splitlines() if ln]
        self.assertTrue(any(item.get("event_id") == expected for item in lines))

    def test_v3_upgrade_re_enforces_boundary(self):
        v3_row = {
            "schema_version": 3,
            "event": "transcript",
            "payload": {"token": "sk-fake-key"},
        }
        with self.assertRaises(ValueError):
            event_writer.EventV4.upgrade_from(v3_row)


if __name__ == "__main__":
    unittest.main()
