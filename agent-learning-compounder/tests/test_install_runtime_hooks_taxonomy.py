from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN_DIR = ROOT / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

import install_runtime_hooks

SCRIPT = ROOT / "bin" / "install_runtime_hooks.py"
EVENT_SOURCES = ROOT / "skills" / "alc-core" / "references" / "event-sources.json"
EVENT_SOURCES_SCHEMA = ROOT / "skills" / "alc-core" / "references" / "event-sources.schema.json"


def _make_repo(root: pathlib.Path) -> pathlib.Path:
    repo = root / "repo"
    repo.mkdir()
    fake_command = repo / "agent-learning-hook"
    fake_command.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_command.chmod(0o700)
    state_dir = root / "state"
    (repo / ".agent-learning.json").write_text(
        json.dumps(
            {
                "hook_command": str(fake_command),
                "repo_state_dir": str(state_dir),
            }
        ),
        encoding="utf-8",
    )
    return repo


def _run_install(repo: pathlib.Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        cwd=str(repo),
        env=run_env,
    )


def _load_commands(path: pathlib.Path) -> list[str]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    commands: list[str] = []
    for event_rows in payload.get("hooks", {}).values():
        if not isinstance(event_rows, list):
            continue
        for row in event_rows:
            if not isinstance(row, dict):
                continue
            for hook in row.get("hooks", []):
                if isinstance(hook, dict) and isinstance(hook.get("command"), str):
                    commands.append(hook["command"])
    return commands


class InstallRuntimeHooksTaxonomyTests(unittest.TestCase):
    def test_default_events_includes_new_claude_events(self) -> None:
        for event in ("SubagentStop", "SessionEnd", "Notification", "PreCompact"):
            self.assertIn(event, install_runtime_hooks.DEFAULT_EVENTS)

    def test_event_sources_json_loads_and_validates(self) -> None:
        rows = install_runtime_hooks._load_event_sources()
        schema = install_runtime_hooks._load_schema(EVENT_SOURCES_SCHEMA)
        self.assertEqual(schema.get("type"), "array")
        self.assertIsInstance(rows, list)
        self.assertGreater(len(rows), 0)

    def test_install_runtime_hooks_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = _make_repo(tmp_path)
            first = _run_install(repo, "--runtime", "codex", "--runtime", "claude", "--apply")
            self.assertEqual(first.returncode, 0, first.stderr)
            codex = repo / ".codex" / "hooks.json"
            claude = repo / ".claude" / "settings.local.json"
            first_codex = json.loads(codex.read_text(encoding="utf-8"))
            first_claude = json.loads(claude.read_text(encoding="utf-8"))

            second = _run_install(repo, "--runtime", "codex", "--runtime", "claude", "--apply")
            self.assertEqual(second.returncode, 0, second.stderr)

            second_codex = json.loads(codex.read_text(encoding="utf-8"))
            second_claude = json.loads(claude.read_text(encoding="utf-8"))
            self.assertEqual(first_codex, second_codex)
            self.assertEqual(first_claude, second_claude)

    def test_install_runtime_hooks_appends_only_new_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = _make_repo(tmp_path)
            custom_sources = tmp_path / "event-sources.json"
            rows = json.loads(EVENT_SOURCES.read_text(encoding="utf-8"))
            rows.append({"runtime": "codex", "name": "CustomHookEvent", "normalized": "custom_hook_event"})
            custom_sources.write_text(json.dumps(rows), encoding="utf-8")

            env = {
                "ALC_EVENT_SOURCES_PATH": str(custom_sources),
                "ALC_EVENT_SOURCES_SCHEMA_PATH": str(EVENT_SOURCES_SCHEMA),
            }
            first = _run_install(repo, "--runtime", "codex", "--apply", env=env)
            self.assertEqual(first.returncode, 0, first.stderr)
            codex = repo / ".codex" / "hooks.json"
            before_commands = _load_commands(codex)

            second = _run_install(
                repo,
                "--runtime",
                "codex",
                "--event",
                "CustomHookEvent",
                "--apply",
                env=env,
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            after_commands = _load_commands(codex)

            self.assertEqual(len(after_commands), len(before_commands) + 1)
            added_commands = [command for command in after_commands if "--event CustomHookEvent" in command]
            self.assertEqual(len(added_commands), 1)
            for command in before_commands:
                self.assertIn(command, after_commands)

    def test_install_runtime_hooks_user_scope_stays_on_user_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = _make_repo(tmp_path)
            home = tmp_path / "user-home"

            env = {
                "HOME": str(home),
            }
            result = _run_install(
                repo,
                "--runtime",
                "claude",
                "--scope",
                "user",
                "--apply",
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((home / ".claude" / "settings.json").exists())
            self.assertFalse((repo / ".claude" / "settings.local.json").exists())

    def test_install_runtime_hooks_releases_config_paths_via_topology(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = _make_repo(tmp_path)
            result = _run_install(repo, "--runtime", "claude", "--runtime", "codex", "--apply")
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads((repo / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
            codex_payload = json.loads((repo / ".codex" / "hooks.json").read_text(encoding="utf-8"))

            self.assertIn("Stop", payload.get("hooks", {}))
            self.assertIn("Stop", codex_payload.get("hooks", {}))

    def test_install_runtime_hooks_rejects_malformed_event_sources(self) -> None:
        malformed_rows = [
            [
                {"runtime": "claude", "name": "PreToolUse"},
            ],
            [
                {"runtime": "claude", "name": 123, "normalized": "pre_tool_use"},
            ],
            [
                {
                    "runtime": "claude",
                    "name": "PreToolUse",
                    "normalized": "pre_tool_use",
                    "extra": "unexpected",
                }
            ],
        ]

        for rows in malformed_rows:
            with self.subTest(rows=rows):
                with tempfile.TemporaryDirectory() as tmp:
                    tmp_path = pathlib.Path(tmp)
                    repo = _make_repo(tmp_path)
                    bad_sources = tmp_path / "event-sources-bad.json"
                    bad_sources.write_text(json.dumps(rows), encoding="utf-8")
                    env = {
                        "ALC_EVENT_SOURCES_PATH": str(bad_sources),
                        "ALC_EVENT_SOURCES_SCHEMA_PATH": str(EVENT_SOURCES_SCHEMA),
                    }
                    result = _run_install(repo, "--runtime", "codex", "--apply", env=env)
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertIn("row 0", (result.stdout + result.stderr).lower())
                    self.assertFalse((repo / ".codex" / "hooks.json").exists())
                    self.assertFalse((repo / ".claude" / "settings.local.json").exists())
