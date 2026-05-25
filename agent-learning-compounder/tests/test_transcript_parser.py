import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

import transcript_parser


class TranscriptParserTests(unittest.TestCase):
    def _write(self, directory: pathlib.Path, name: str, rows: list[dict]) -> pathlib.Path:
        path = directory / name
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        return path

    def test_parse_claude_jsonl_user_assistant_tool_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            transcript = self._write(
                root,
                "session.jsonl",
                [
                    {
                        "type": "user",
                        "sessionId": "session-1",
                        "uuid": "u-001",
                        "timestamp": "2026-05-26T00:00:00+00:00",
                        "message": {"role": "user"},
                    },
                    {
                        "type": "assistant",
                        "sessionId": "session-1",
                        "uuid": "a-001",
                        "timestamp": "2026-05-26T00:01:00+00:00",
                        "message": {"role": "assistant"},
                    },
                    {
                        "type": "tool_use",
                        "sessionId": "session-1",
                        "uuid": "tu-001",
                        "toolUseID": "tool-call-1",
                        "timestamp": "2026-05-26T00:01:30+00:00",
                    },
                    {
                        "type": "tool_result",
                        "sessionId": "session-1",
                        "uuid": "tr-001",
                        "parentUuid": "tu-001",
                        "timestamp": "2026-05-26T00:01:40+00:00",
                    },
                ],
            )

            rows = list(transcript_parser.parse_claude_transcript(transcript))
            self.assertEqual([row["event"] for row in rows], ["client_message", "agent_message", "tool_use", "tool_result"])
            self.assertEqual(len(rows[0]["correlation_chain"]), 1)
            self.assertEqual(rows[0]["correlation_chain"][0]["role"], "session")
            self.assertEqual(rows[0]["correlation_chain"][0]["id"], "session-1")
            self.assertEqual(rows[-1]["correlation_chain"][0]["role"], "session")
            self.assertEqual(rows[-1]["correlation_chain"][1]["role"], "parent")
            self.assertEqual(rows[-1]["correlation_chain"][1]["id"], "tu-001")

    def test_parse_codex_transcript_uses_same_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            transcript = self._write(
                root,
                "session.jsonl",
                [
                    {
                        "type": "SubagentStart",
                        "sessionId": "codex-1",
                        "uuid": "c-001",
                        "timestamp": "2026-05-26T01:00:00+00:00",
                    },
                    {
                        "type": "assistant",
                        "sessionId": "codex-1",
                        "uuid": "c-002",
                        "timestamp": "2026-05-26T01:01:00+00:00",
                    },
                    {
                        "type": "assistant",
                        "message": {"role": "assistant", "content": "answer"},
                        "sessionId": "codex-1",
                        "uuid": "c-003",
                        "timestamp": "2026-05-26T01:01:30+00:00",
                    },
                ],
            )

            rows = list(transcript_parser.parse_codex_transcript(transcript))
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[0]["event"], "subagent_start")
            self.assertEqual(rows[1]["runtime"], "codex")
            self.assertIn({"role": "session", "id": "codex-1"}, rows[0]["correlation_chain"])
            self.assertEqual(rows[2]["event"], "agent_message")


if __name__ == "__main__":
    unittest.main()
