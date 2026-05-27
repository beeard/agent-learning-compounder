"""Cross-runtime session_id handling — UUIDs hash to stable distinct tokens.

Pre-fix: Claude Code (and any other runtime) passing a UUID-shaped
session_id collapsed to the literal string ``"session"``, meaning every
event in events.sqlite shared one session_id and the read surfaces
couldn't distinguish sessions. This regression test pins the new
hash-don't-drop behavior so the bug can't silently come back.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BIN = REPO_ROOT / "bin"
COLLECT = BIN / "collect_hook_event"


class SessionIdHashing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.tmp.name)
        self.log_path = self.state_dir / "hook-events.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def _emit(self, payload):
        env = {**os.environ, "AGENT_LEARNING_STATE_DIR": str(self.state_dir)}
        proc = subprocess.run(
            [str(COLLECT), "--output", str(self.log_path)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return [json.loads(line) for line in self.log_path.read_text().splitlines()]

    # ---- direct unit tests on safe_session ---------------------------------

    def _safe_session(self, value):
        if str(BIN) not in sys.path:
            sys.path.insert(0, str(BIN))
        # import lazily so module-level state can't leak between tests
        import importlib
        mod = importlib.import_module("collect_hook_event")
        return mod.safe_session(value)

    def test_safe_session_empty_returns_sentinel(self):
        self.assertEqual(self._safe_session(None), "session")
        self.assertEqual(self._safe_session(""), "session")
        self.assertEqual(self._safe_session("   "), "session")

    def test_safe_session_uuid_hashes_to_stable_prefixed_token(self):
        # Claude Code session_id shape
        uuid = "12345678-abcd-4123-89ab-1234567890ab"
        token = self._safe_session(uuid)
        self.assertTrue(token.startswith("s_"), f"expected s_-prefixed hash, got {token!r}")
        self.assertEqual(len(token), 14)  # "s_" + 12 hex chars
        # Determinism: same UUID always hashes to same token (otherwise
        # session-grouping queries against events.sqlite would scatter).
        self.assertEqual(token, self._safe_session(uuid))

    def test_safe_session_distinct_uuids_produce_distinct_tokens(self):
        # The bug we're regressing: two real sessions used to both
        # collapse to "session" — sqlite couldn't distinguish them.
        uuid_a = "11111111-aaaa-4111-89aa-111111111111"
        uuid_b = "22222222-bbbb-4222-89bb-222222222222"
        self.assertNotEqual(
            self._safe_session(uuid_a),
            self._safe_session(uuid_b),
            "distinct UUIDs must produce distinct tokens",
        )

    def test_safe_session_non_uuid_slug_path_unchanged(self):
        # Codex / other runtimes may pass a slug-shaped session id.
        # That path is unchanged by the fix — still slugified.
        token = self._safe_session("My Session Title 42")
        self.assertEqual(token, "my-session-title-42")

    def test_safe_session_idempotent_on_hashed_token(self):
        # replay_hook_events.normalize re-runs safe_session against rows
        # that ALREADY went through it. Without idempotency, the second
        # pass slugs the underscore in s_xxxx → s-xxxx, breaking the
        # group-by-session_id query in events.sqlite.
        uuid = "12345678-abcd-4123-89ab-1234567890ab"
        once = self._safe_session(uuid)
        twice = self._safe_session(once)
        self.assertEqual(once, twice, "second pass must not mangle the hashed token")
        self.assertTrue(twice.startswith("s_"))

    def test_safe_session_idempotent_on_session_sentinel(self):
        # The "session" sentinel must also survive a second pass without
        # getting slugged into "session" (no-op happens to coincide here,
        # but the test pins the intent).
        self.assertEqual(self._safe_session("session"), "session")

    def test_safe_session_uuid_never_leaks_raw_value(self):
        uuid = "abcdef01-2345-4678-89ab-cdef01234567"
        token = self._safe_session(uuid)
        self.assertNotIn(uuid, token)
        self.assertNotIn("abcdef01", token, "raw uuid prefix must not appear")

    # ---- end-to-end through the CLI ----------------------------------------

    def test_e2e_uuid_session_id_lands_as_hashed_token(self):
        rows = self._emit({
            "event": "PreToolUse",
            "tool": "Bash",
            "session_id": "12345678-abcd-4123-89ab-1234567890ab",
        })
        self.assertTrue(rows[-1]["session_id"].startswith("s_"))
        self.assertNotEqual(rows[-1]["session_id"], "session")

    def test_e2e_two_uuids_remain_distinguishable(self):
        rows_a = self._emit({
            "event": "PreToolUse", "tool": "Bash",
            "session_id": "11111111-aaaa-4111-89aa-111111111111",
        })
        rows_b = self._emit({
            "event": "PreToolUse", "tool": "Bash",
            "session_id": "22222222-bbbb-4222-89bb-222222222222",
        })
        self.assertNotEqual(rows_a[-1]["session_id"], rows_b[-1]["session_id"])


if __name__ == "__main__":
    unittest.main()
