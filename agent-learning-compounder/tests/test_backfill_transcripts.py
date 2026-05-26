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


class BackfillTranscriptsTests(unittest.TestCase):
    def test_backfill_with_since_produces_stable_ids_and_scrubs_sensitive_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = pathlib.Path(tmp)
            claude_root = tmp_root / ".claude" / "projects"
            codex_root = tmp_root / ".codex" / "sessions"
            claude_root.mkdir(parents=True)
            codex_root.mkdir(parents=True)

            for session_id in range(5):
                rows = [
                    {
                        "type": "user",
                        "sessionId": f"session-{session_id}",
                        "uuid": f"u-{session_id}-1",
                            "path": f"{tmp_root}/repo/{session_id}/artifact.txt",
                        "timestamp": f"2026-05-26T10:0{session_id}:00+00:00",
                        "message": {"role": "user", "content": "safe content"},
                    },
                    {
                        "type": "assistant",
                        "sessionId": f"session-{session_id}",
                        "uuid": f"a-{session_id}-1",
                            "path": f"{tmp_root}/repo/{session_id}/artifact.txt",
                        "timestamp": f"2026-05-26T10:0{session_id}:10+00:00",
                        "message": {"role": "assistant"},
                    },
                ]
                _write_rows(claude_root / f"session-{session_id}.jsonl", rows)

            # One malformed line and one secret-bearing line in explicit codex payload.
            _write_rows(
                codex_root / "legacy.jsonl",
                [
                    {
                        "type": "assistant",
                        "sessionId": "secret",
                        "uuid": "s-1",
                        "path": f"{tmp_root}/secrets/key.txt",
                        "timestamp": "2026-05-26T10:20:00+00:00",
                        "payload": {"token": "sk-ant-xxx"},
                    },
                ],
            )
            (codex_root / "legacy.jsonl").write_text(
                (codex_root / "legacy.jsonl").read_text(encoding="utf-8") + "{not json}\n",
                encoding="utf-8",
            )

            with tempfile.TemporaryDirectory() as state_tmp:
                env = {
                    **dict(os.environ),
                    "AGENT_LEARNING_STATE_DIR": str(state_tmp),
                }
                first = run_script(
                    "backfill_transcripts.py",
                    "--since",
                    "30d",
                    "--claude-dir",
                    str(claude_root),
                    "--codex-dir",
                    str(codex_root),
                    env=env,
                )
                self.assertEqual(first.returncode, 0, first.stderr)

                event_log = pathlib.Path(state_tmp) / "events.jsonl"
                rows = [json.loads(line) for line in event_log.read_text(encoding="utf-8").splitlines() if line.strip()]
                self.assertEqual(len(rows), 11)
                ids_first = [row["event_id"] for row in rows]
                self.assertTrue(all("sk-ant-" not in line for line in event_log.read_text(encoding="utf-8").splitlines()))
                self.assertTrue(all(not str(row.get("path", "")).startswith("/tmp/") for row in rows))

                with tempfile.TemporaryDirectory() as state_tmp2:
                    env2 = {
                        **dict(os.environ),
                        "AGENT_LEARNING_STATE_DIR": str(state_tmp2),
                    }
                    second = run_script(
                        "backfill_transcripts.py",
                        "--since",
                        "30d",
                        "--claude-dir",
                        str(claude_root),
                        "--codex-dir",
                        str(codex_root),
                        env=env2,
                    )
                    self.assertEqual(second.returncode, 0, second.stderr)
                    rows2 = [
                        json.loads(line)
                        for line in (pathlib.Path(state_tmp2) / "events.jsonl").read_text(encoding="utf-8").splitlines()
                        if line.strip()
                    ]
                    ids_second = [row["event_id"] for row in rows2]
                    self.assertEqual(sorted(ids_first), sorted(ids_second))

    def test_backfill_malformed_lines_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = pathlib.Path(tmp)
            with tempfile.TemporaryDirectory() as state_tmp:
                claude_root = tmp_root / ".claude" / "projects"
                codex_root = pathlib.Path(tempfile.mkdtemp())
                claude_root.mkdir(parents=True)
                good = claude_root / "session-good.jsonl"
                good.write_text(
                    '{"type":"user","sessionId":"s1","uuid":"u1","timestamp":"2026-05-26T10:00:00+00:00","message":{"role":"user"}}\n',
                    encoding="utf-8",
                )
                bad = claude_root / "session-bad.jsonl"
                bad.write_text("{not-json}\n", encoding="utf-8")

                env = {**dict(os.environ), "AGENT_LEARNING_STATE_DIR": str(state_tmp)}
                result = run_script(
                    "backfill_transcripts.py",
                    "--since",
                    "30d",
                    "--claude-dir",
                    str(claude_root),
                    "--codex-dir",
                    str(codex_root),
                    env=env,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                rows = [
                    json.loads(line)
                    for line in (pathlib.Path(state_tmp) / "events.jsonl").read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["event"], "client_message")


if __name__ == "__main__":
    unittest.main()
