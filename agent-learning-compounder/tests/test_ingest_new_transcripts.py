import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"


def run_script(name: str, *args: object, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    args = [str(BIN_DIR / name), *map(str, args)]
    return subprocess.run(
        [sys.executable, *args],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


def _write_rows(path: pathlib.Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


class IngestNewTranscriptsTests(unittest.TestCase):
    def test_first_run_with_empty_cursor_ingests_all_and_writes_cursor(self):
        with tempfile.TemporaryDirectory() as tmp:
            with tempfile.TemporaryDirectory() as state_tmp:
                claude_root = pathlib.Path(tmp) / ".claude" / "projects"
                codex_root = pathlib.Path(tmp) / ".codex" / "sessions"
                claude_root.mkdir(parents=True)
                codex_root.mkdir(parents=True)
                _write_rows(
                    claude_root / "session.jsonl",
                    [
                        {
                            "type": "user",
                            "sessionId": "s1",
                            "uuid": "u-1",
                            "timestamp": "2026-05-26T01:00:00+00:00",
                            "message": {"role": "user"},
                        },
                        {
                            "type": "assistant",
                            "sessionId": "s1",
                            "uuid": "a-1",
                            "timestamp": "2026-05-26T01:01:00+00:00",
                            "message": {"role": "assistant"},
                        },
                    ],
                )

                env = {**dict(os.environ), "AGENT_LEARNING_STATE_DIR": str(state_tmp)}
                first = run_script(
                    "ingest_new_transcripts.py",
                    "--claude-dir",
                    str(claude_root),
                    "--codex-dir",
                    str(codex_root),
                    env=env,
                )
                self.assertEqual(first.returncode, 0, first.stderr)

                state = pathlib.Path(state_tmp)
                rows = [
                    json.loads(line)
                    for line in (state / "events.jsonl").read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
                self.assertEqual(len(rows), 2)
                cursor = (state / ".transcript-cursor").read_text(encoding="utf-8").strip()
                self.assertTrue(cursor)

    def test_second_run_ingests_only_events_after_cursor(self):
        with tempfile.TemporaryDirectory() as tmp:
            with tempfile.TemporaryDirectory() as state_tmp:
                claude_root = pathlib.Path(tmp) / ".claude" / "projects"
                codex_root = pathlib.Path(tmp) / ".codex" / "sessions"
                claude_root.mkdir(parents=True)
                codex_root.mkdir(parents=True)
                transcript = claude_root / "session.jsonl"
                _write_rows(
                    transcript,
                    [
                        {
                            "type": "user",
                            "sessionId": "s1",
                            "uuid": "u-1",
                            "timestamp": "2026-05-26T02:00:00+00:00",
                            "message": {"role": "user"},
                        },
                        {
                            "type": "assistant",
                            "sessionId": "s1",
                            "uuid": "a-1",
                            "timestamp": "2026-05-26T02:01:00+00:00",
                            "message": {"role": "assistant"},
                        },
                    ],
                )

                env = {**dict(os.environ), "AGENT_LEARNING_STATE_DIR": str(state_tmp)}
                first = run_script(
                    "ingest_new_transcripts.py",
                    "--claude-dir",
                    str(claude_root),
                    "--codex-dir",
                    str(codex_root),
                    env=env,
                )
                self.assertEqual(first.returncode, 0, first.stderr)

                with transcript.open("a", encoding="utf-8") as fh:
                    fh.write(
                        "\n".join(
                            json.dumps(row)
                            for row in [
                                {
                                    "type": "user",
                                    "sessionId": "s1",
                                    "uuid": "u-2",
                                    "timestamp": "2026-05-26T02:05:00+00:00",
                                    "message": {"role": "user"},
                                },
                                {
                                    "type": "assistant",
                                    "sessionId": "s1",
                                    "uuid": "a-2",
                                    "timestamp": "2026-05-26T02:06:00+00:00",
                                    "message": {"role": "assistant"},
                                },
                            ]
                        )
                        + "\n"
                    )

                second = run_script(
                    "ingest_new_transcripts.py",
                    "--claude-dir",
                    str(claude_root),
                    "--codex-dir",
                    str(codex_root),
                    env=env,
                )
                self.assertEqual(second.returncode, 0, second.stderr)
                state = pathlib.Path(state_tmp)
                rows = [
                    json.loads(line)
                    for line in (state / "events.jsonl").read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
                self.assertEqual(len(rows), 4)
                self.assertTrue(rows[-1].get("ts") >= rows[0].get("ts"))


if __name__ == "__main__":
    unittest.main()
