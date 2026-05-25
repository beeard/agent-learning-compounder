import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
FIXTURES = ROOT / "fixtures" / "eval-fixtures"


def run_script(name, *args, input_text=None):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *map(str, args)],
        input=input_text,
        text=True,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def write_skill(root: pathlib.Path, name: str, description: str = "Use when testing.", body: str = "") -> pathlib.Path:
    path = root / name / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n{body}", encoding="utf-8")
    return path


class SelfHealingRoadmapTests(unittest.TestCase):
    def test_init_creates_portable_state_and_compact_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            state = tmp_path / "state"
            personal = tmp_path / "personal"
            repo.mkdir()
            personal.mkdir()
            (repo / "AGENTS.md").write_text("- Before substantial work, load repo skills.\n", encoding="utf-8")
            (repo / "package.json").write_text(json.dumps({"scripts": {"test": "vitest"}}), encoding="utf-8")
            skill_root = repo / ".agents" / "skills"
            write_skill(skill_root, "session-start")
            write_skill(skill_root, "port-vocab-gate", "Use when packages/ports changes are in scope.")

            result = run_script(
                "init_learning_system.py",
                "--repo",
                repo,
                "--state-dir",
                state,
                "--personal",
                personal,
                "--self-test",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            config = json.loads((state / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["state_version"], 1)
            repo_dirs = list((state / "repos").iterdir())
            self.assertEqual(len(repo_dirs), 1)
            repo_state = repo_dirs[0]
            self.assertTrue((repo_state / "baseline.json").exists())
            self.assertTrue((repo_state / "domain-rules.active.json").exists())
            self.assertTrue((repo_state / "skill-map.json").exists())
            self.assertTrue((repo_state / "improvement-queue.jsonl").exists())
            manifest_path = repo_state / "automation" / "agent-learning-refresh.manifest.json"
            self.assertTrue(manifest_path.exists())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["runner"], "script-only")
            self.assertEqual(manifest["scheduler_pattern"], "external scheduler runs script directly")
            self.assertIn("refresh_learning_state.py", " ".join(manifest["command"]))
            gates = (repo_state / "reports" / "latest-approved-gates.md").read_text(encoding="utf-8")
            self.assertIn("# Approved Agent Gates", gates)
            self.assertIn("domains: none", gates)
            context = (repo_state / "reports" / "latest-skill-context.md").read_text(encoding="utf-8")
            self.assertIn("# Active Skill Context", context)
            self.assertIn("session-start", context)
            self.assertNotIn("raw_prompt", context)

    def test_init_defaults_to_repo_local_state_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            xdg = tmp_path / "xdg-state"
            repo.mkdir()
            write_skill(repo / ".agents" / "skills", "session-start")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "init_learning_system.py"),
                    "--repo",
                    str(repo),
                    "--install-repo-integration",
                    "--self-test",
                ],
                cwd=ROOT,
                env={**os.environ, "XDG_STATE_HOME": str(xdg)},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            config = json.loads((repo / ".agent-learning.json").read_text(encoding="utf-8"))
            self.assertEqual(config["state_dir"], str(repo.resolve() / ".agent-learning"))
            self.assertTrue(pathlib.Path(config["refresh_manifest"]).exists())
            self.assertTrue(pathlib.Path(config["improvement_queue"]).exists())

    def test_init_respects_agent_learning_state_dir_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            override = tmp_path / "override-state"
            repo.mkdir()
            write_skill(repo / ".agents" / "skills", "session-start")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "init_learning_system.py"),
                    "--repo",
                    str(repo),
                    "--install-repo-integration",
                    "--self-test",
                ],
                cwd=ROOT,
                env={**os.environ, "AGENT_LEARNING_STATE_DIR": str(override)},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            config = json.loads((repo / ".agent-learning.json").read_text(encoding="utf-8"))
            self.assertEqual(config["state_dir"], str(override.resolve()))

    def test_init_respects_explicit_state_dir_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            state = tmp_path / "state"
            repo.mkdir()
            write_skill(repo / ".agents" / "skills", "session-start")

            result = run_script(
                "init_learning_system.py",
                "--repo",
                repo,
                "--state-dir",
                state,
                "--install-repo-integration",
                "--self-test",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            config = json.loads((repo / ".agent-learning.json").read_text(encoding="utf-8"))
            self.assertEqual(config["state_dir"], str(state.resolve()))

    def test_init_install_repo_integration_writes_discovery_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            state = tmp_path / "state"
            repo.mkdir()
            write_skill(repo / ".agents" / "skills", "session-start")

            result = run_script(
                "init_learning_system.py",
                "--repo",
                repo,
                "--state-dir",
                state,
                "--install-repo-integration",
                "--self-test",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            config_path = repo / ".agent-learning.json"
            self.assertTrue(config_path.exists())
            config = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(config["schema_version"], 1)
            self.assertEqual(config["state_dir"], str(state.resolve()))
            self.assertTrue(pathlib.Path(config["domain_rules"]).exists())
            self.assertTrue(pathlib.Path(config["latest_approved_gates"]).exists())
            self.assertTrue(pathlib.Path(config["latest_skill_context"]).exists())
            self.assertTrue(pathlib.Path(config["improvement_queue"]).exists())
            self.assertTrue(pathlib.Path(config["refresh_manifest"]).exists())
            self.assertIn("refresh_learning_state.py", " ".join(config["refresh_command"]))
            self.assertEqual(pathlib.Path(config["reports_dir"]).parent.name, config["repo_id"])

    def test_init_repo_integration_gitignores_local_discovery_config(self):
        """Repo-local discovery config contains absolute paths and must stay local."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            state = tmp_path / "state"
            repo.mkdir()
            subprocess.run(["git", "init"], cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            write_skill(repo / ".agents" / "skills", "session-start")

            result = run_script(
                "init_learning_system.py",
                "--repo",
                repo,
                "--state-dir",
                state,
                "--install-repo-integration",
                "--self-test",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((repo / ".agent-learning.json").exists())
            gitignore = (repo / ".gitignore").read_text(encoding="utf-8")
            self.assertIn("/.agent-learning.json", gitignore)
            ignored = subprocess.run(
                ["git", "check-ignore", ".agent-learning.json"],
                cwd=repo,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(ignored.returncode, 0, ignored.stderr)

    def test_init_can_install_custom_domain_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            state = tmp_path / "state"
            rules = tmp_path / "rules.json"
            repo.mkdir()
            write_skill(repo / ".agents" / "skills", "session-start")
            rules.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "rules": [
                            {
                                "domain": "custom-domain",
                                "category": "custom-gate",
                                "patterns": ["customsignal"],
                                "failure_signal": "Custom signal needs a custom gate.",
                                "gate": "Run the custom check before completion.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = run_script(
                "init_learning_system.py",
                "--repo",
                repo,
                "--state-dir",
                state,
                "--domain-rules",
                rules,
                "--install-repo-integration",
                "--self-test",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            config = json.loads((repo / ".agent-learning.json").read_text(encoding="utf-8"))
            active = pathlib.Path(config["domain_rules"])
            payload = json.loads(active.read_text(encoding="utf-8"))
            self.assertEqual(payload["rules"][0]["domain"], "custom-domain")
            self.assertEqual(payload["source"], str(rules))

    def test_init_rejects_invalid_custom_domain_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            state = tmp_path / "state"
            rules = tmp_path / "rules.json"
            repo.mkdir()
            rules.write_text(json.dumps({"schema_version": 1, "rules": [{"domain": "broken"}]}), encoding="utf-8")

            result = run_script(
                "init_learning_system.py",
                "--repo",
                repo,
                "--state-dir",
                state,
                "--domain-rules",
                rules,
                "--self-test",
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("missing", result.stderr)

    def test_init_repo_integration_refuses_tracked_discovery_config(self):
        """Init must not overwrite tracked local config with absolute paths."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            state = tmp_path / "state"
            repo.mkdir()
            subprocess.run(["git", "init"], cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            write_skill(repo / ".agents" / "skills", "session-start")
            config = repo / ".agent-learning.json"
            config.write_text('{"schema_version":0}\n', encoding="utf-8")
            subprocess.run(["git", "add", ".agent-learning.json"], cwd=repo, check=True)

            result = run_script(
                "init_learning_system.py",
                "--repo",
                repo,
                "--state-dir",
                state,
                "--install-repo-integration",
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("tracked by git", result.stderr)
            self.assertEqual(config.read_text(encoding="utf-8"), '{"schema_version":0}\n')

    def test_init_install_hooks_creates_repo_scoped_wrapper_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            state = tmp_path / "state"
            repo.mkdir()
            write_skill(repo / ".agents" / "skills", "session-start")

            result = run_script(
                "init_learning_system.py",
                "--repo",
                repo,
                "--state-dir",
                state,
                "--install-repo-integration",
                "--install-hooks",
                "--self-test",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            config = json.loads((repo / ".agent-learning.json").read_text(encoding="utf-8"))
            hook_command = pathlib.Path(config["hook_command"])
            hook_manifest = pathlib.Path(config["hook_manifest"])
            hook_log = pathlib.Path(config["hook_event_log"])
            self.assertTrue(hook_command.exists())
            self.assertTrue(hook_manifest.exists())
            self.assertEqual(config["hook_input"], "stdin-json")
            manifest = json.loads(hook_manifest.read_text(encoding="utf-8"))
            self.assertIn("InstructionsLoaded", manifest["recommended_events"])
            self.assertIn("AgentDispatchStart", manifest["recommended_events"])
            self.assertEqual(manifest["telemetry"]["agent_dispatch"], True)
            hook_run = subprocess.run(
                [str(hook_command)],
                input=json.dumps({"event": "InstructionsLoaded", "skill": "session-start", "cwd": str(repo)}),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(hook_run.returncode, 0, hook_run.stderr)
            rows = [json.loads(line) for line in hook_log.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(rows[0]["event"], "instructions_loaded")
            self.assertEqual(rows[0]["skill"], "session-start")

    def test_install_runtime_hooks_merges_codex_and_claude_configs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            state = tmp_path / "state"
            repo.mkdir()
            write_skill(repo / ".agents" / "skills", "session-start")
            codex_config = repo / ".codex" / "hooks.json"
            codex_config.parent.mkdir()
            codex_config.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [
                                {
                                    "matcher": "Bash",
                                    "hooks": [{"type": "command", "command": "echo existing"}],
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            init = run_script(
                "init_learning_system.py",
                "--repo",
                repo,
                "--state-dir",
                state,
                "--install-repo-integration",
                "--install-hooks",
            )
            self.assertEqual(init.returncode, 0, init.stderr)

            dry_run = run_script(
                "install_runtime_hooks.py",
                "--repo",
                repo,
                "--runtime",
                "codex",
                "--runtime",
                "claude",
                "--dry-run",
            )
            self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
            self.assertFalse((repo / ".claude" / "settings.local.json").exists())
            self.assertNotIn("install_runtime_hooks", codex_config.read_text(encoding="utf-8"))

            applied = run_script(
                "install_runtime_hooks.py",
                "--repo",
                repo,
                "--runtime",
                "codex",
                "--runtime",
                "claude",
                "--apply",
            )
            second = run_script(
                "install_runtime_hooks.py",
                "--repo",
                repo,
                "--runtime",
                "codex",
                "--runtime",
                "claude",
                "--apply",
            )

            self.assertEqual(applied.returncode, 0, applied.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            codex = json.loads(codex_config.read_text(encoding="utf-8"))
            claude = json.loads((repo / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
            self.assertEqual(codex["hooks"]["PreToolUse"][0]["hooks"][0]["command"], "echo existing")
            codex_commands = json.dumps(codex)
            claude_commands = json.dumps(claude)
            self.assertIn("--runtime codex", codex_commands)
            self.assertIn("--event SessionStart", codex_commands)
            self.assertIn("--runtime claude", claude_commands)
            self.assertIn("--event Stop", claude_commands)
            self.assertEqual(codex_commands.count("install_runtime_hooks"), 5)
            self.assertEqual(claude_commands.count("install_runtime_hooks"), 5)

    def test_install_runtime_hooks_auto_gitignores_repo_scope_configs(self):
        """Repo-scope --apply should add the hook config paths to .gitignore.

        The applied hook config contains an absolute $HOME path to the adapter
        script. If committed, that leaks the operator's home directory. The
        installer auto-appends a .gitignore entry to block the leak.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            state = tmp_path / "state"
            repo.mkdir()
            (repo / ".git").mkdir()  # mark as git repo
            write_skill(repo / ".agents" / "skills", "session-start")
            init = run_script(
                "init_learning_system.py",
                "--repo",
                repo,
                "--state-dir",
                state,
                "--install-repo-integration",
                "--install-hooks",
            )
            self.assertEqual(init.returncode, 0, init.stderr)

            applied = run_script(
                "install_runtime_hooks.py",
                "--repo",
                repo,
                "--runtime",
                "codex",
                "--runtime",
                "claude",
                "--apply",
            )
            self.assertEqual(applied.returncode, 0, applied.stderr)

            gitignore = (repo / ".gitignore").read_text(encoding="utf-8")
            self.assertIn("/.codex/hooks.json", gitignore)
            self.assertIn("/.codex/hooks.json.agent-learning-bak-*", gitignore)
            self.assertIn("/.claude/settings.local.json", gitignore)
            self.assertIn("/.claude/settings.local.json.agent-learning-bak-*", gitignore)

            # Second apply should not duplicate the entries.
            run_script(
                "install_runtime_hooks.py",
                "--repo",
                repo,
                "--runtime",
                "codex",
                "--apply",
            )
            second = (repo / ".gitignore").read_text(encoding="utf-8")
            second_lines = second.splitlines()
            self.assertEqual(second_lines.count("/.codex/hooks.json"), 1)
            self.assertEqual(second_lines.count("/.codex/hooks.json.agent-learning-bak-*"), 1)

    def test_install_runtime_hooks_refuses_tracked_repo_scope_config(self):
        """Repo-scope --apply must not mutate tracked hook configs with local paths."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            state = tmp_path / "state"
            repo.mkdir()
            subprocess.run(["git", "init"], cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            write_skill(repo / ".agents" / "skills", "session-start")
            codex_config = repo / ".codex" / "hooks.json"
            codex_config.parent.mkdir()
            codex_config.write_text('{"hooks":{}}\n', encoding="utf-8")
            subprocess.run(["git", "add", ".codex/hooks.json"], cwd=repo, check=True)
            init = run_script(
                "init_learning_system.py",
                "--repo",
                repo,
                "--state-dir",
                state,
                "--install-repo-integration",
                "--install-hooks",
            )
            self.assertEqual(init.returncode, 0, init.stderr)

            result = run_script(
                "install_runtime_hooks.py",
                "--repo",
                repo,
                "--runtime",
                "codex",
                "--apply",
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("tracked by git", result.stderr)
            self.assertEqual(codex_config.read_text(encoding="utf-8"), '{"hooks":{}}\n')
            gitignore = (repo / ".gitignore").read_text(encoding="utf-8")
            self.assertIn("/.agent-learning.json", gitignore)
            self.assertNotIn("/.codex/hooks.json", gitignore)

    def test_install_runtime_hooks_skips_gitignore_when_not_a_git_repo(self):
        """No .git/ means the installer must not create or modify .gitignore."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            state = tmp_path / "state"
            repo.mkdir()
            write_skill(repo / ".agents" / "skills", "session-start")
            run_script(
                "init_learning_system.py",
                "--repo",
                repo,
                "--state-dir",
                state,
                "--install-repo-integration",
                "--install-hooks",
            )
            run_script(
                "install_runtime_hooks.py",
                "--repo",
                repo,
                "--runtime",
                "codex",
                "--apply",
            )
            self.assertFalse((repo / ".gitignore").exists())

    def test_runtime_hook_adapter_forwards_safe_event_to_shared_collector(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            state = tmp_path / "state"
            repo.mkdir()
            write_skill(repo / ".agents" / "skills", "session-start")
            init = run_script(
                "init_learning_system.py",
                "--repo",
                repo,
                "--state-dir",
                state,
                "--install-repo-integration",
                "--install-hooks",
            )
            self.assertEqual(init.returncode, 0, init.stderr)
            config = json.loads((repo / ".agent-learning.json").read_text(encoding="utf-8"))
            raw = {
                "tool_name": "Bash",
                "tool_input": {"command": "pnpm test", "path": str(repo / "package.json")},
                "agent": {
                    "id": "agent-1",
                    "role": "builder",
                    "backend": "codex-exec",
                    "model": "gpt-5.3-codex-spark",
                    "effort": "low",
                    "sandbox": "workspace-write",
                },
                "task": {
                    "id": "dispatch-1",
                    "write_scope": ["src/app.ts"],
                    "worktree": str(repo / ".worktrees" / "dispatch-1"),
                    "branch": "wt/dispatch-1",
                },
                "prompt": "raw prompt must not persist",
                "tool_output": "raw output must not persist",
                "session_id": "runtime-adapter",
            }

            result = run_script(
                "install_runtime_hooks.py",
                "--adapter",
                "--repo",
                repo,
                "--runtime",
                "codex",
                "--event",
                "PreToolUse",
                input_text=json.dumps(raw),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            rows = [
                json.loads(line)
                for line in pathlib.Path(config["hook_event_log"]).read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(rows[0]["event"], "pre_tool_use")
            self.assertEqual(rows[0]["runtime"], "codex")
            self.assertEqual(rows[0]["tool"], "Bash")
            self.assertEqual(rows[0]["command_class"], "pnpm")
            self.assertEqual(rows[0]["agent_role"], "builder")
            self.assertEqual(rows[0]["agent_backend"], "codex-exec")
            self.assertEqual(rows[0]["agent_model"], "gpt-5.3-codex-spark")
            self.assertEqual(rows[0]["dispatch_id"], "dispatch-1")
            self.assertEqual(rows[0]["agent_write_scope"], ["src/app.ts"])
            self.assertEqual(rows[0]["agent_worktree"], ".worktrees/dispatch-1")
            rendered = json.dumps(rows[0], sort_keys=True)
            self.assertNotIn("raw prompt", rendered)
            self.assertNotIn("raw output", rendered)

    def test_collect_hook_event_appends_scrubbed_bounded_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            repo.mkdir()
            event_log = tmp_path / "hook-events.jsonl"
            raw = {
                "event": "PreToolUse",
                "runtime": "Claude Code",
                "cwd": str(repo),
                "session_id": "11111111-2222-4333-8444-555555555555",
                "tool_name": "Read",
                "path": str(repo / ".agents" / "skills" / "session-start" / "SKILL.md"),
                "prompt": "this raw prompt must not persist",
                "tool_output": "raw output must not persist",
                "payload": {"secret": "ghp_abcdefghijklmnopqrstuvwxyz123456"},
            }

            first = run_script("collect_hook_event.py", "--repo", repo, "--output", event_log, input_text=json.dumps(raw))
            second = run_script(
                "collect_hook_event.py",
                "--repo",
                repo,
                "--output",
                event_log,
                input_text=json.dumps({"event": "UnexpectedFutureHook", "cwd": str(repo), "label": "ok"}),
            )

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            rows = [json.loads(line) for line in event_log.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["event"], "pre_tool_use")
            self.assertEqual(rows[0]["runtime"], "claude-code")
            self.assertEqual(rows[0]["skill"], "session-start")
            self.assertEqual(rows[0]["path"], ".agents/skills/session-start/SKILL.md")
            rendered = "\n".join(json.dumps(row, sort_keys=True) for row in rows)
            self.assertNotIn("raw prompt", rendered)
            self.assertNotIn("raw output", rendered)
            self.assertNotIn("abcdefghijklmnopqrstuvwxyz", rendered)
            self.assertNotIn("11111111-2222-4333-8444-555555555555", rendered)
            self.assertEqual(rows[1]["event"], "unexpected_future_hook")

    def test_collect_hook_event_handles_malformed_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            repo.mkdir()

            result = run_script(
                "collect_hook_event.py",
                "--repo",
                repo,
                "--output",
                tmp_path / "malformed.jsonl",
                "--event",
                "{this is not valid json}",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            rows = [json.loads(line) for line in (tmp_path / "malformed.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(rows[0]["event"], "malformed_json")
            self.assertEqual(rows[0]["runtime"], "collect-hook-event")
            self.assertLessEqual(len(rows[0]["label"]), 80)

    def test_collect_hook_event_rejects_symlink_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            repo.mkdir()
            target = tmp_path / "target.jsonl"
            target.write_text("", encoding="utf-8")
            output = tmp_path / "symlink.jsonl"
            output.symlink_to(target)

            result = run_script(
                "collect_hook_event.py",
                "--repo",
                repo,
                "--output",
                output,
                "--event",
                json.dumps({"event": "PreToolUse", "runtime": "Codex", "cwd": str(repo)}),
            )

            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("is a symlink", result.stderr)

    def test_collect_hook_event_redacts_out_of_repo_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            repo.mkdir()
            outside = tmp_path / "outside" / "SKILL.md"
            outside.parent.mkdir()
            outside.write_text("payload\n", encoding="utf-8")
            out = tmp_path / "events.jsonl"

            result = run_script(
                "collect_hook_event.py",
                "--repo",
                repo,
                "--output",
                out,
                "--event",
                json.dumps(
                    {
                        "event": "PreToolUse",
                        "runtime": "Codex",
                        "cwd": str(repo),
                        "path": str(outside),
                        "command": "read external",
                    }
                ),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertNotEqual(rows[0]["path"], str(outside))
            self.assertTrue(rows[0]["path"].startswith("<outside_repo:"))

    def test_install_runtime_hooks_adapter_rejects_tampered_hook_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            state = tmp_path / "state"
            repo.mkdir()
            write_skill(repo / ".agents" / "skills", "session-start")

            init = run_script(
                "init_learning_system.py",
                "--repo",
                repo,
                "--state-dir",
                state,
                "--install-repo-integration",
                "--install-hooks",
                "--self-test",
            )
            self.assertEqual(init.returncode, 0, init.stderr)
            config_path = repo / ".agent-learning.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["hook_command"] = "/bin/echo"
            config_path.write_text(json.dumps(config, indent=2, sort_keys=True), encoding="utf-8")

            result = run_script(
                "install_runtime_hooks.py",
                "--adapter",
                "--repo",
                repo,
                "--runtime",
                "codex",
                "--event",
                "SessionStart",
                input_text="{}",
            )
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("Configured hook_command", result.stderr)

    def test_install_runtime_hooks_adapter_is_quiet_on_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            state = tmp_path / "state"
            repo.mkdir()
            write_skill(repo / ".agents" / "skills", "session-start")

            init = run_script(
                "init_learning_system.py",
                "--repo",
                repo,
                "--state-dir",
                state,
                "--install-repo-integration",
                "--install-hooks",
                "--self-test",
            )
            self.assertEqual(init.returncode, 0, init.stderr)

            result = run_script(
                "install_runtime_hooks.py",
                "--adapter",
                "--repo",
                repo,
                "--runtime",
                "codex",
                "--event",
                "SessionStart",
                input_text="{}",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")

    def test_refresh_learning_state_updates_context_and_improvement_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            state = tmp_path / "state"
            repo.mkdir()
            (repo / "AGENTS.md").write_text(
                "When scope touches packages/ports/**, use port-vocab-gate.\n",
                encoding="utf-8",
            )
            write_skill(repo / ".agents" / "skills", "session-start")
            write_skill(repo / ".agents" / "skills", "port-vocab-gate", "Use when packages/ports changes are in scope.")

            init = run_script("init_learning_system.py", "--repo", repo, "--state-dir", state, "--install-repo-integration")
            self.assertEqual(init.returncode, 0, init.stderr)
            config = json.loads((repo / ".agent-learning.json").read_text(encoding="utf-8"))
            repo_state = pathlib.Path(config["repo_state_dir"])
            events = repo_state / "hook-events.jsonl"
            events.write_text(
                "\n".join(
                    json.dumps(row)
                    for row in [
                        {"session_id": "s1", "event": "scope", "scope": "packages/ports/a.ts", "cwd": str(repo)},
                        {"session_id": "s1", "event": "instructions_loaded", "skill": "session-start", "cwd": str(repo)},
                        {"session_id": "s1", "event": "user_correction", "outcome": "correction", "cwd": str(repo)},
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            first = run_script("refresh_learning_state.py", "--repo", repo, "--state-dir", state)
            second = run_script("refresh_learning_state.py", "--repo", repo, "--state-dir", state)

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            summary = json.loads(first.stdout)
            self.assertEqual(summary["queued_candidates"], 2)
            usage = json.loads((repo_state / "skill-usage.json").read_text(encoding="utf-8"))
            self.assertIn("port-vocab-gate", usage["missed"])
            context = pathlib.Path(config["latest_skill_context"]).read_text(encoding="utf-8")
            self.assertIn("missed_expected_skill: port-vocab-gate", context)
            queue_lines = pathlib.Path(config["improvement_queue"]).read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(queue_lines), 2)
            queue_text = "\n".join(queue_lines).lower()
            self.assertIn("candidate_adjustment", queue_text)
            self.assertIn("port-vocab-gate", queue_text)
            self.assertNotIn("caused", queue_text)

    def test_map_active_skills_tracks_validity_duplicates_and_missing_resources(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            global_root = tmp_path / "global-skills"
            repo.mkdir()
            (repo / "AGENTS.md").write_text(
                "When scope touches packages/ports/**, use port-vocab-gate.\n", encoding="utf-8"
            )
            write_skill(repo / ".agents" / "skills", "session-start", body="Read references/missing.md when needed.")
            write_skill(repo / ".claude" / "skills", "session-start")
            bad = repo / ".agents" / "skills" / "bad" / "SKILL.md"
            bad.parent.mkdir(parents=True)
            bad.write_text("---\nname: bad\n---\n", encoding="utf-8")
            write_skill(global_root, "port-vocab-gate", "Use when port contracts are touched.")
            output = tmp_path / "skill-map.json"

            result = run_script(
                "map_active_skills.py",
                "--repo",
                repo,
                "--global-skill-root",
                global_root,
                "--output",
                output,
                "--runtime",
                "all",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(data["repo"], str(repo.resolve()))
            self.assertTrue(any(skill["name"] == "session-start" for skill in data["skills"]))
            self.assertTrue(any(dup["name"] == "session-start" for dup in data["duplicates"]))
            self.assertTrue(any(item["name"] == "bad" for item in data["invalid"]))
            self.assertTrue(any(item["skill"] == "session-start" for item in data["missing_dependencies"]))
            session_start = next(skill for skill in data["skills"] if skill["name"] == "session-start" and skill["scope"] == "repo")
            self.assertFalse(session_start["references_ok"])
            self.assertGreater(session_start["priority"], 50)
            self.assertTrue(data["agents_rules"])

    def test_map_active_skills_filters_skill_roots_by_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            global_root = tmp_path / "global-skills"
            repo.mkdir()
            write_skill(repo / ".agents" / "skills", "session-start", "Repo codex skill")
            write_skill(repo / ".claude" / "skills", "session-start", "Repo claude skill")
            write_skill(repo / ".agents" / "skills", "shared")
            write_skill(repo / ".claude" / "skills", "shared")

            output = tmp_path / "codex.json"
            run_script(
                "map_active_skills.py",
                "--repo",
                repo,
                "--global-skill-root",
                global_root,
                "--runtime",
                "codex",
                "--output",
                output,
            )
            codex = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual([row["path"] for row in codex["skills"] if row["name"] == "session-start"], [".agents/skills/session-start/SKILL.md"])

            output = tmp_path / "claude.json"
            run_script(
                "map_active_skills.py",
                "--repo",
                repo,
                "--global-skill-root",
                global_root,
                "--runtime",
                "claude",
                "--output",
                output,
            )
            claude = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual([row["path"] for row in claude["skills"] if row["name"] == "session-start"], [".claude/skills/session-start/SKILL.md"])

            output = tmp_path / "all.json"
            run_script(
                "map_active_skills.py",
                "--repo",
                repo,
                "--global-skill-root",
                global_root,
                "--runtime",
                "all",
                "--output",
                output,
            )
            both = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                sorted(row["path"] for row in both["skills"] if row["name"] == "session-start"),
                [".agents/skills/session-start/SKILL.md", ".claude/skills/session-start/SKILL.md"],
            )

    def test_expected_skill_routing_supports_prompts_and_fixture_eval(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            skill_map = tmp_path / "skill-map.json"
            skill_map.write_text(
                json.dumps(
                    {
                        "repo": str(tmp_path),
                        "skills": [
                            {"name": "session-start", "valid": True},
                            {"name": "port-vocab-gate", "valid": True},
                            {"name": "next-session", "valid": True},
                            {"name": "session-end", "valid": True},
                            {"name": "tm-design", "valid": True},
                            {"name": "agent-learning-compounder", "valid": True},
                        ],
                        "agents_rules": [
                            {"fact": "packages/ports/** must use port-vocab-gate", "source": "AGENTS.md:3"}
                        ],
                    }
                ),
                encoding="utf-8",
            )

            routed = run_script(
                "evaluate_skill_routing.py",
                "--scope",
                "packages/ports/src/contracts.ts",
                "--skill-map",
                skill_map,
            )
            evaluated = run_script(
                "evaluate_skill_routing.py",
                "--fixtures",
                FIXTURES / "skill_routing.json",
                "--skill-map",
                skill_map,
                "--min-precision",
                "0.90",
                "--min-recall",
                "0.90",
            )

            self.assertEqual(routed.returncode, 0, routed.stderr)
            payload = json.loads(routed.stdout)
            self.assertEqual(payload["expected"], ["session-start", "port-vocab-gate"])
            self.assertEqual(payload["missing"], [])
            self.assertEqual(payload["confidence"], "high")
            self.assertEqual(evaluated.returncode, 0, evaluated.stderr)
            metrics = json.loads(evaluated.stdout)
            self.assertGreaterEqual(metrics["case_count"], 12)
            self.assertGreaterEqual(metrics["precision"], 0.90)
            self.assertGreaterEqual(metrics["recall"], 0.90)

    def test_extract_usage_and_impact_report_correlation_not_causality(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            skill_map = tmp_path / "skill-map.json"
            events = tmp_path / "hook-events.jsonl"
            usage = tmp_path / "usage.json"
            impact = tmp_path / "impact.json"
            skill_map.write_text(
                json.dumps(
                    {
                        "repo": str(tmp_path),
                        "skills": [
                            {"name": "session-start", "valid": True},
                            {"name": "port-vocab-gate", "valid": True},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            events.write_text(
                "\n".join(
                    json.dumps(row)
                    for row in [
                        {"session_id": "s1", "event": "scope", "scope": "packages/ports/a.ts"},
                        {"session_id": "s1", "event": "instructions_loaded", "skill": "session-start"},
                        {"session_id": "s1", "event": "instructions_loaded", "skill": "port-vocab-gate"},
                        {"session_id": "s1", "event": "skill_applied", "skill": "port-vocab-gate"},
                        {"session_id": "s2", "event": "scope", "scope": "packages/ports/b.ts"},
                        {"session_id": "s2", "event": "user_correction", "outcome": "correction"},
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            usage_result = run_script("extract_skill_usage.py", "--events", events, "--skill-map", skill_map, "--output", usage)
            impact_result = run_script("evaluate_skill_impact.py", "--usage", usage, "--output", impact)

            self.assertEqual(usage_result.returncode, 0, usage_result.stderr)
            self.assertEqual(impact_result.returncode, 0, impact_result.stderr)
            usage_data = json.loads(usage.read_text(encoding="utf-8"))
            self.assertIn("port-vocab-gate", usage_data["missed"])
            self.assertIn("port-vocab-gate", usage_data["loaded"])
            impact_data = json.loads(impact.read_text(encoding="utf-8"))
            port = next(row for row in impact_data["skills"] if row["skill"] == "port-vocab-gate")
            self.assertEqual(port["expected_sessions"], 2)
            self.assertEqual(port["loaded_sessions"], 1)
            self.assertEqual(port["missed_sessions"], 1)
            self.assertEqual(port["corrections_after_missed"], 1)
            self.assertEqual(port["impact_signal"], "missed_expected_skill_correlates_with_scope_correction")
            self.assertNotIn("caused", json.dumps(impact_data).lower())

    def test_export_skill_context_excludes_raw_payloads_and_secret_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            skill_map = tmp_path / "skill-map.json"
            usage = tmp_path / "usage.json"
            impact = tmp_path / "impact.json"
            output = tmp_path / "latest-skill-context.md"
            skill_map.write_text(
                json.dumps(
                    {
                        "repo": str(tmp_path),
                        "skills": [{"name": "session-start", "valid": True}],
                        "invalid": [{"name": "broken-skill", "path": ".agents/skills/broken/SKILL.md"}],
                    }
                ),
                encoding="utf-8",
            )
            usage.write_text(
                json.dumps(
                    {
                        "expected": ["session-start", "port-vocab-gate"],
                        "loaded": ["session-start"],
                        "missed": ["port-vocab-gate"],
                        "failed": ["session-start"],
                    }
                ),
                encoding="utf-8",
            )
            impact.write_text(
                json.dumps(
                    {
                        "skills": [
                            {
                                "skill": "port-vocab-gate",
                                "impact_signal": "missed_expected_skill_correlates_with_scope_correction",
                                "candidate_adjustment": "Load port-vocab-gate before packages/ports edits.",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = run_script(
                "export_skill_context.py",
                "--skill-map",
                skill_map,
                "--skill-usage",
                usage,
                "--skill-impact",
                impact,
                "--output",
                output,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            context = output.read_text(encoding="utf-8")
            self.assertIn("## required_at_session_start", context)
            self.assertIn("latest-approved-gates.md", context)
            self.assertIn("invalid: .agents/skills/broken/SKILL.md", context)
            self.assertIn("missed_expected_skill: port-vocab-gate", context)
            self.assertIn("loaded_but_not_applied: session-start", context)
            self.assertIn("Load port-vocab-gate before packages/ports edits.", context)
            self.assertNotIn("raw_prompt", context)
            self.assertNotIn("[REDACTED", context)

    def test_distill_write_exports_skill_context_and_report_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            personal = tmp_path / "personal"
            personal.mkdir()
            (personal / "insights.md").write_text("", encoding="utf-8")
            (personal / "learning.md").write_text("", encoding="utf-8")
            corpus = tmp_path / "corpus.txt"
            baseline = tmp_path / "baseline.json"
            report = tmp_path / "report.md"
            skill_map = tmp_path / "skill-map.json"
            usage = tmp_path / "usage.json"
            impact = tmp_path / "impact.json"
            corpus.write_text("user: packages/ports must use the port vocab gate\n", encoding="utf-8")
            baseline.write_text(
                json.dumps(
                    {
                        "repo": str(tmp_path / "repo"),
                        "source_files": ["AGENTS.md"],
                        "source_evidence": [{"fact": "`AGENTS.md` exists.", "source": "AGENTS.md:1"}],
                        "validation_commands": ["pnpm test"],
                        "validation_evidence": [{"command": "pnpm test", "script": "test", "source": "package.json:4"}],
                        "skills": [".agents/skills/session-start/SKILL.md"],
                    }
                ),
                encoding="utf-8",
            )
            skill_map.write_text(
                json.dumps({"skills": [{"name": "session-start", "valid": True}], "invalid": []}),
                encoding="utf-8",
            )
            usage.write_text(
                json.dumps({"expected": ["session-start"], "loaded": [], "missed": ["session-start"], "failed": []}),
                encoding="utf-8",
            )
            impact.write_text(
                json.dumps(
                    {
                        "skills": [
                            {
                                "skill": "session-start",
                                "expected_sessions": 1,
                                "loaded_sessions": 0,
                                "missed_sessions": 1,
                                "impact_signal": "missed_expected_skill",
                                "confidence": "medium",
                                "candidate_adjustment": "Read latest skill context before planning.",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = run_script(
                "distill_learning.py",
                "--corpus",
                corpus,
                "--baseline",
                baseline,
                "--output",
                report,
                "--write",
                "--personal",
                personal,
                "--skill-map",
                skill_map,
                "--skill-usage",
                usage,
                "--skill-impact",
                impact,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            rendered = report.read_text(encoding="utf-8")
            self.assertIn("## skill_inventory", rendered)
            self.assertIn("## skill_usage", rendered)
            self.assertIn("## skill_health", rendered)
            self.assertIn("## skill_compensation", rendered)
            self.assertTrue((personal / "reports" / "agent-learning" / "latest-approved-gates.md").exists())
            context = personal / "reports" / "agent-learning" / "latest-skill-context.md"
            self.assertTrue(context.exists())
            self.assertIn("Read latest skill context before planning.", context.read_text(encoding="utf-8"))

    def test_validator_rejects_raw_hook_payloads_and_causal_skill_overclaims(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = pathlib.Path(tmp) / "bad-skill-health.md"
            report.write_text(
                "\n".join(
                    [
                        "# Agent Learning Report",
                        "## confirmed_current",
                        "- [confirmed_current] Source exists. source: AGENTS.md:1",
                        "## memory_derived",
                        "- [memory_derived] Evidence exists. source: corpus",
                        "## needs_verification",
                        "- [needs_verification] Runtime may drift. verify: rerun validation.",
                        "## agent_compensation",
                        "### domain: validation",
                        "- gate_category: validation-check",
                        "- gate: Run validation.",
                        "## self_healing_loop",
                        "- failure_signal -> candidate_gate -> validation_status -> next_session_load. source: corpus",
                        "## skill_health",
                        "- skill caused failure after raw_hook_payload: {prompt: secret}",
                    ]
                ),
                encoding="utf-8",
            )

            result = run_script("validate_outputs.py", report)

            self.assertEqual(result.returncode, 1)
            self.assertIn("raw hook payload", result.stderr)
            self.assertIn("causal skill overclaim", result.stderr)
            self.assertIn("skill_health bullet missing evidence marker", result.stderr)

    def test_eval_fixtures_cover_at_least_roadmap_target_cases(self):
        classifier = json.loads((FIXTURES / "classifier_precision.json").read_text(encoding="utf-8"))
        routing = json.loads((FIXTURES / "skill_routing.json").read_text(encoding="utf-8"))
        hook_events = [line for line in (FIXTURES / "hook_events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        health = json.loads((FIXTURES / "skill_health.json").read_text(encoding="utf-8"))

        total = len(classifier) + len(routing) + len(hook_events) + len(health["cases"])

        self.assertGreaterEqual(total, 40)


if __name__ == "__main__":
    unittest.main()
