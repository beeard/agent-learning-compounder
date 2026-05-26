from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
SCRIPT = BIN_DIR / "alc_invoke"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

import state_handle

import alc_invoke


DESCRIPTION_PREFIX = "Use this agent when reviewing archived context and synthesizing a concise recommendation."
BODY_BLOCK = (
    "This section describes a robust, practical role and process that can be executed repeatedly across many cases. "
    "The agent performs careful analysis, preserves quality constraints, and returns structured guidance with examples. "
    "It reasons step by step, checks assumptions, and records actionable outcomes in plain language. "
) * 10


def _make_agent_text(name: str, model: str = "sonnet") -> str:
    return textwrap.dedent(
        f"""
        ---
        name: {name}
        description: {DESCRIPTION_PREFIX} <example>Example one</example> <example>Example two</example>
        color: blue
        model: {model}
        ---

        # Role

        {BODY_BLOCK}

        ## Responsibilities

        {BODY_BLOCK}

        ## Process

        {BODY_BLOCK}

        ## Output

        {BODY_BLOCK}
        """
    ).strip()


class AlcInvokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.state_root = self.root / "state"

        os.environ["AGENT_LEARNING_STATE_DIR"] = str(self.state_root)

        self.env = os.environ.copy()
        self.env["AGENT_LEARNING_STATE_DIR"] = str(self.state_root)
        self.env["PYTHONPATH"] = str(BIN_DIR) + os.pathsep + self.env.get("PYTHONPATH", "")
        self.env.pop("CLAUDE_PLUGIN_ROOT", None)
        self.env.pop("CODEX_PLUGIN_ROOT", None)
        self.env.pop("CODEX_HOME", None)
        self.env.pop("AGENT_LEARNING_PERSONAL", None)
        self.env.pop("AGENT_LEARNING_USER", None)

        self.handle = state_handle.StateHandle.for_repo(self.repo)
        for directory in self.handle.alc_agents_dirs.values():
            directory.mkdir(parents=True, exist_ok=True)

        self.valid_agent = self.handle.alc_agents_dirs["dev"] / "recall.md"
        self.valid_agent.write_text(_make_agent_text("recall-agent"), encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()
        os.environ.pop("AGENT_LEARNING_STATE_DIR", None)

    @property
    def events_path(self) -> pathlib.Path:
        return self.handle.events_jsonl

    def _run(self, args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, str(SCRIPT), *args]
        payload = self.env.copy() if env is None else env
        return subprocess.run(
            command,
            text=True,
            capture_output=True,
            cwd=self.repo,
            env=payload,
            check=False,
        )

    def _read_events(self) -> list[dict[str, object]]:
        if not self.events_path.exists():
            return []
        rows: list[dict[str, object]] = []
        for line in self.events_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
        return rows

    def _base_args(self, agent: str = "dev/recall.md") -> list[str]:
        return ["--agent", agent, "--task", "Summarize the root cause for this issue."]

    def _read_output_file(self, path: pathlib.Path) -> str:
        return path.read_text(encoding="utf-8")

    def _write_agent(self, rel: str, name: str = "dev-helper", age: int | None = None) -> pathlib.Path:
        target = self.handle.alc_agents_dirs["dev"] / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_make_agent_text(name), encoding="utf-8")
        if age is not None:
            now = time.time()
            old = now - (age * 24 * 3600)
            os.utime(target, (old, old))
        return target

    def test_invoke_valid_agent_returns_structured_result(self) -> None:
        out_file = self.root / "agent_output.txt"
        proc = self._run([*self._base_args(), "--output", str(out_file), "--model", "haiku"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)

        self.assertEqual(payload["agent"], "recall-agent")
        self.assertEqual(payload["model_used"], "haiku")
        self.assertEqual(payload["task"], "Summarize the root cause for this issue.")
        self.assertGreater(len(payload["output"]), 0)
        self.assertEqual(payload["event_ids"], sorted(payload["event_ids"]))
        self.assertTrue(out_file.exists())
        self.assertEqual(self._read_output_file(out_file), payload["output"])

        events = self._read_events()
        self.assertGreaterEqual(len(events), 2)
        start_events = [event for event in events if event.get("event") == "subagent_invoke_start"]
        end_events = [event for event in events if event.get("event") == "subagent_invoke_end"]
        self.assertTrue(start_events)
        self.assertTrue(end_events)
        start_event = start_events[-1]
        end_event = end_events[-1]
        self.assertEqual(start_event["event"], "subagent_invoke_start")
        self.assertEqual(end_event["event"], "subagent_invoke_end")
        self.assertEqual(end_event["parent_event_id"], start_event["event_id"])
        payload_hash = hashlib.sha256(b"Summarize the root cause for this issue.").hexdigest()[:16]
        self.assertEqual(start_event["payload"]["task_prompt_hash"], payload_hash)
        self.assertNotIn("Summarize the root cause", str(start_event["payload"]))

    def test_missing_agent(self) -> None:
        proc = self._run(["--agent", "dev/missing.md", "--task", "noop"])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("agent not found at dev/missing.md", proc.stderr)

    def test_invalid_frontmatter_is_rejected(self) -> None:
        bad = self.handle.alc_agents_dirs["dev"] / "invalid.md"
        bad_text = _make_agent_text("bad-agent").replace(
            DESCRIPTION_PREFIX,
            "Bad description without required prefix.",
        )
        bad.write_text(bad_text, encoding="utf-8")
        proc = self._run(["--agent", "dev/invalid.md", "--task", "noop"])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("description must start with 'Use this agent when'", proc.stderr)

    def test_cleanup_removes_older_dev_agents(self) -> None:
        fresh = self._write_agent("fresh.md", age=1)
        self._write_agent("stale.md", age=60)
        self._run(self._base_args())
        self.assertTrue(fresh.exists())
        self.assertFalse((self.handle.alc_agents_dirs["dev"] / "stale.md").exists())

    def test_test_and_evals_archives_not_cleaned(self) -> None:
        test_agent = self.handle.alc_agents_dirs["test"] / "old-test.md"
        eval_agent = self.handle.alc_agents_dirs["evals"] / "old-evals.md"
        test_agent.write_text(_make_agent_text("test-old"), encoding="utf-8")
        eval_agent.write_text(_make_agent_text("eval-old"), encoding="utf-8")
        stale = time.time() - (60 * 24 * 3600)
        os.utime(test_agent, (stale, stale))
        os.utime(eval_agent, (stale, stale))

        proc = self._run(self._base_args())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(test_agent.exists())
        self.assertTrue(eval_agent.exists())

    def test_personal_archive_accessible(self) -> None:
        personal = self.root / "personal"
        (personal / "alc-agents").mkdir(parents=True, exist_ok=True)
        personal_agent = personal / "alc-agents" / "from-personal.md"
        personal_agent.write_text(_make_agent_text("personal-agent"), encoding="utf-8")

        env = self.env.copy()
        env["AGENT_LEARNING_PERSONAL"] = str(personal)

        proc = self._run(["--agent", "from-personal.md", "--task", "check personal"], env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["agent"], "personal-agent")

    def test_sandbox_depth_is_forwarded_to_exec_sandbox(self) -> None:
        with mock.patch("alc_invoke.subprocess.run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess(
                args=("exec",),
                returncode=0,
                stdout=json.dumps(
                    {
                        "stdout": str(self.root / "mock-stdout.txt"),
                        "stderr": str(self.root / "mock-stderr.txt"),
                        "event_id": "evt-mock",
                    }
                ),
                stderr="",
            )
            stdout_file = self.root / "mock-stdout.txt"
            stdout_file.write_text("mock output", encoding="utf-8")
            state = state_handle.StateHandle.for_repo(self.repo)
            result = alc_invoke.invoke(
                repo=self.repo,
                agent_ref="dev/recall.md",
                task="depth test",
                sandbox_depth=4,
            )
            self.assertEqual(result["model_used"], "sonnet")
            call_args = run_mock.call_args.args[0]
            self.assertIn("--depth", call_args)
            depth_index = call_args.index("--depth")
            self.assertEqual(call_args[depth_index + 1], "5")


if __name__ == "__main__":
    unittest.main()
