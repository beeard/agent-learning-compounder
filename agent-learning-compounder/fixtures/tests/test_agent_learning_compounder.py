import json
import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


def run_script(name, *args, input_text=None, cwd=None, env=None):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *map(str, args)],
        input=input_text,
        text=True,
        cwd=cwd or ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def run_script_with_stdin(name, input_text):
    return run_script(name, input_text=input_text)


class AgentLearningCompounderTests(unittest.TestCase):
    def test_extract_sessions_reads_string_and_block_content_and_scrubs_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            transcript = tmp_path / "session.jsonl"
            transcript.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "message": {
                                    "role": "user",
                                    "content": "token ghp_abcdefghijklmnopqrstuvwxyz123456",
                                }
                            }
                        ),
                        json.dumps(
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": [
                                        {"type": "text", "text": "Use pnpm test"},
                                        {"type": "tool_use", "name": "ignored"},
                                    ],
                                }
                            }
                        ),
                    ]
                )
                + "\n"
            )

            result = run_script("extract_sessions.py", "--path", tmp_path)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("user: token [REDACTED:github_pat]", result.stdout)
            self.assertIn("assistant: Use pnpm test", result.stdout)
            self.assertNotIn("abcdefghijklmnopqrstuvwxyz", result.stdout)
            self.assertNotIn("tool_use", result.stdout)

    def test_extract_sessions_scrubs_secret_named_payload_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            transcript = tmp_path / "session.jsonl"
            transcript.write_text(
                json.dumps(
                    {
                        "message": {
                            "role": "assistant",
                            "content": 'input: {"name":"QUICK3_SESSION_TOKEN","text":"b56a950b-6eb1-45b8-a685-4b2fcaa861bc"}',
                        }
                    }
                )
                + "\n"
            )

            result = run_script("extract_sessions.py", "--path", tmp_path)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('"text":"[REDACTED:secret_payload]"', result.stdout)
            self.assertNotIn("b56a950b", result.stdout)

    def test_extract_sessions_scrubs_escaped_secret_payloads_and_secret_put_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            transcript = tmp_path / "session.jsonl"
            transcript.write_text(
                json.dumps(
                    {
                        "message": {
                            "role": "assistant",
                            "content": (
                                'code: {\\"name\\": \\"QUICK3_SESSION_TOKEN\\", '
                                '\\"text\\": \\"b56a950b-6eb1-45b8-a685-4b2fcaa861bc\\"}\n'
                                "command: printf '%s' \"b56a950b-6eb1-45b8-a685-4b2fcaa861bc\" "
                                "| pnpm exec wrangler secret put QUICK3_SESSION_TOKEN"
                            ),
                        }
                    }
                )
                + "\n"
            )

            result = run_script("extract_sessions.py", "--path", tmp_path)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('\\"text\\": \\"[REDACTED:secret_payload]\\"', result.stdout)
            self.assertIn("[REDACTED:secret_uuid]", result.stdout)
            self.assertNotIn("b56a950b", result.stdout)

    def test_scrub_secrets_covers_claude_package_patterns(self):
        private_key = "-----BEGIN PRIVATE KEY-----\nabc123\n-----END PRIVATE KEY-----"
        text = "\n".join(
            [
                "xoxb-123456789012-secret",
                "sk_live_123456789012345678901234",
                "pk_test_123456789012345678901234",
                "npm_123456789012345678901234567890",
                "AIza12345678901234567890123456789012345",
                "eyJaaaaaaaaaaa.eyJbbbbbbbbbbb.ccccccccccccc",
                "api_key=abcdef123456",
                private_key,
            ]
        )

        result = run_script_with_stdin("scrub_secrets.py", text)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[REDACTED:slack_token]", result.stdout)
        self.assertIn("[REDACTED:stripe_secret]", result.stdout)
        self.assertIn("[REDACTED:stripe_public]", result.stdout)
        self.assertIn("[REDACTED:npm_token]", result.stdout)
        self.assertIn("[REDACTED:google_api_key]", result.stdout)
        self.assertIn("[REDACTED:jwt]", result.stdout)
        self.assertIn("[REDACTED:generic_secret_assignment]", result.stdout)
        self.assertIn("[REDACTED:private_key_block]", result.stdout)

    def test_validate_outputs_uses_broad_secret_scrubber(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = pathlib.Path(tmp) / "report.md"
            report.write_text(
                "\n".join(
                    [
                        "# Agent Learning Report",
                        "## confirmed_current",
                        "- source: baseline",
                        "## memory_derived",
                        '- quote: "xoxb-123456789012-secret"',
                        "## needs_verification",
                        "- source: corpus",
                        "## agent_compensation",
                        "- source: baseline",
                    ]
                )
            )

            result = run_script("validate_outputs.py", report)

            self.assertEqual(result.returncode, 1)
            self.assertIn("secret-like content", result.stderr)

    def test_scrub_secrets_lists_session_specific_patterns(self):
        result = run_script("scrub_secrets.py", "--list-patterns")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("secret_payload", result.stdout)
        self.assertIn("secret_uuid", result.stdout)
        self.assertIn("uuid", result.stdout)

    def test_extract_sessions_reads_codex_response_item_payloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            transcript = tmp_path / "codex.jsonl"
            transcript.write_text(
                json.dumps(
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "utfør"}],
                        },
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "Jeg gjør det."}],
                        },
                    }
                )
                + "\n"
            )

            result = run_script("extract_sessions.py", "--path", tmp_path)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("user: utfør", result.stdout)
            self.assertIn("assistant: Jeg gjør det.", result.stdout)

    def test_extract_sessions_can_filter_by_session_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            match = tmp_path / "match.jsonl"
            other = tmp_path / "other.jsonl"
            match.write_text(
                json.dumps(
                    {
                        "type": "session_meta",
                        "payload": {"cwd": "/repo/a"},
                    }
                )
                + "\n"
                + json.dumps({"message": {"role": "user", "content": "keep me"}})
                + "\n"
            )
            other.write_text(
                json.dumps(
                    {
                        "type": "session_meta",
                        "payload": {"cwd": "/repo/b"},
                    }
                )
                + "\n"
                + json.dumps({"message": {"role": "user", "content": "drop me"}})
                + "\n"
            )

            result = run_script("extract_sessions.py", "--path", tmp_path, "--cwd", "/repo/a")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("keep me", result.stdout)
            self.assertNotIn("drop me", result.stdout)

    def test_extract_sessions_can_filter_claude_code_top_level_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            transcript = tmp_path / "claude.jsonl"
            transcript.write_text(
                json.dumps(
                    {
                        "type": "user",
                        "cwd": "/repo/a",
                        "message": {"role": "user", "content": [{"type": "text", "text": "claude keep"}]},
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "type": "user",
                        "cwd": "/repo/b",
                        "message": {"role": "user", "content": [{"type": "text", "text": "claude drop"}]},
                    }
                )
                + "\n"
            )

            result = run_script("extract_sessions.py", "--path", tmp_path, "--cwd", "/repo/a")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("claude keep", result.stdout)
            self.assertNotIn("claude drop", result.stdout)

    def test_extract_sessions_reads_multiple_paths_for_cross_agent_corpus(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            codex = root / "codex"
            claude = root / "claude"
            codex.mkdir()
            claude.mkdir()
            (codex / "codex.jsonl").write_text(
                json.dumps({"type": "session_meta", "payload": {"cwd": "/repo/a"}})
                + "\n"
                + json.dumps({"message": {"role": "user", "content": "codex msg"}})
                + "\n"
            )
            (claude / "claude.jsonl").write_text(
                json.dumps(
                    {
                        "type": "assistant",
                        "cwd": "/repo/a",
                        "message": {"role": "assistant", "content": [{"type": "text", "text": "claude msg"}]},
                    }
                )
                + "\n"
            )

            result = run_script(
                "extract_sessions.py",
                "--path",
                codex,
                "--path",
                claude,
                "--cwd",
                "/repo/a",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("user: codex msg", result.stdout)
            self.assertIn("assistant: claude msg", result.stdout)
            self.assertIn("session_ref=", result.stdout)

    def test_extract_sessions_reads_json_transcript_and_chatgpt_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            transcript = tmp_path / "conversation.json"
            transcript.write_text(
                json.dumps(
                    {
                        "mapping": {
                            "a": {
                                "message": {
                                    "author": {"role": "user"},
                                    "content": {"parts": ["verify this"]},
                                }
                            },
                            "b": {
                                "message": {
                                    "author": {"role": "assistant"},
                                    "content": {"parts": ["checked"]},
                                }
                            },
                        }
                    }
                )
            )

            result = run_script("extract_sessions.py", "--path", tmp_path)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("user: verify this", result.stdout)
            self.assertIn("assistant: checked", result.stdout)
            self.assertIn("session_ref=", result.stdout)

    def test_extract_sessions_sanitizes_uuid_shaped_session_refs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            transcript = tmp_path / "rollout-11111111-2222-4333-8444-555555555555.jsonl"
            transcript.write_text(json.dumps({"message": {"role": "user", "content": "verify"}}) + "\n")

            result = run_script("extract_sessions.py", "--path", tmp_path)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("session_ref=", result.stdout)
            self.assertNotIn("11111111-2222-4333-8444-555555555555", result.stdout)

    def test_extract_sessions_samples_large_corpora_with_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            for index in range(60):
                transcript = tmp_path / f"session-{index:02d}.jsonl"
                transcript.write_text(
                    json.dumps({"message": {"role": "user", "content": f"msg {index:02d}"}}) + "\n"
                )

            result = run_script("extract_sessions.py", "--path", tmp_path, "--max-sessions", "5")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("meta: sampled_sessions", result.stdout)
            self.assertIn("selected=5 total=60", result.stdout)
            self.assertEqual(result.stdout.count("user: msg"), 5)

    def test_build_repo_baseline_collects_repo_sources_of_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            repo.mkdir()
            (repo / "AGENTS.md").write_text("# AGENTS\nRead DESIGN.md first.\n")
            (repo / "package.json").write_text(
                '{"scripts":{"test":"vitest","typecheck":"tsc --noEmit"}}'
            )
            (repo / ".agents").mkdir()
            (repo / ".agents" / "skills").mkdir()
            (repo / ".agents" / "skills" / "example").mkdir()
            (repo / ".agents" / "skills" / "example" / "SKILL.md").write_text(
                "---\nname: example\ndescription: Use when testing.\n---\n"
            )

            result = run_script("build_repo_baseline.py", "--repo", repo)

            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["repo"], str(repo))
            self.assertIn("AGENTS.md", data["source_files"])
            self.assertEqual(data["validation_commands"], ["npm run test", "npm run typecheck"])
            self.assertEqual(data["skills"], [".agents/skills/example/SKILL.md"])
            self.assertEqual(data["source_evidence"][0]["source"], "AGENTS.md:1")
            self.assertIn("package.json:", data["validation_evidence"][0]["source"])
            self.assertEqual(data["skill_evidence"][0]["source"], ".agents/skills/example/SKILL.md:1")

    def test_build_repo_baseline_uses_pnpm_when_lockfile_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp) / "repo"
            repo.mkdir()
            (repo / "package.json").write_text('{"scripts":{"test":"vitest"}}')
            (repo / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")

            result = run_script("build_repo_baseline.py", "--repo", repo)

            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["validation_commands"], ["pnpm test"])

    def test_build_repo_baseline_parses_instruction_rules_and_includes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            repo = root / "repo"
            outside = root / "outside"
            repo.mkdir()
            outside.mkdir()
            included = outside / "AGENTS.md"
            included.write_text(
                "\n".join(
                    [
                        "# Out-of-repo include",
                        "- Never use unvetted third-party tokens in runtime checks.",
                        "- Never edit evergreen files automatically.",
                    ]
                )
                + "\n"
            )
            (repo / "AGENTS.md").write_text(
                "\n".join(
                    [
                        f"@{included}",
                        "## Skill Loading",
                        "- Before substantial work, use the repo-local skill inventory.",
                        "- Casual prose without an operational keyword.",
                    ]
                )
                + "\n"
            )
            (repo / "CLAUDE.md").write_text("- Do not skip validation gates.\n")

            result = run_script("build_repo_baseline.py", "--repo", repo)

            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            facts = "\n".join(item["fact"] for item in data["instruction_evidence"])
            sources = "\n".join(item["source"] for item in data["instruction_evidence"])
            self.assertIn("include rejected", facts)
            self.assertIn("absolute @include paths are not supported", facts)
            self.assertIn("Before substantial work", facts)
            self.assertNotIn("Never use unvetted", facts)
            self.assertIn("Do not skip validation gates", facts)
            self.assertIn("AGENTS.md:1", sources)
            self.assertIn("CLAUDE.md:1", sources)

    def test_build_repo_baseline_runtime_filters_skill_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp) / "repo"
            repo.mkdir()
            repo_agents = repo / ".agents" / "skills"
            repo_claude = repo / ".claude" / "skills"
            (repo_agents / "session-start").mkdir(parents=True)
            (repo_agents / "session-start" / "SKILL.md").write_text(
                "---\nname: session-start\ndescription: Codex skill\n---\n",
                encoding="utf-8",
            )
            (repo_claude / "session-start").mkdir(parents=True)
            (repo_claude / "session-start" / "SKILL.md").write_text(
                "---\nname: session-start\ndescription: Claude skill\n---\n",
                encoding="utf-8",
            )

            codex = run_script("build_repo_baseline.py", "--repo", repo, "--runtime", "codex")
            claude = run_script("build_repo_baseline.py", "--repo", repo, "--runtime", "claude")
            both = run_script("build_repo_baseline.py", "--repo", repo, "--runtime", "all")

            self.assertEqual(codex.returncode, 0, codex.stderr)
            self.assertEqual(claude.returncode, 0, claude.stderr)
            self.assertEqual(both.returncode, 0, both.stderr)

            codex_data = json.loads(codex.stdout)
            claude_data = json.loads(claude.stdout)
            both_data = json.loads(both.stdout)

            self.assertEqual(codex_data["skills"], [".agents/skills/session-start/SKILL.md"])
            self.assertEqual(claude_data["skills"], [".claude/skills/session-start/SKILL.md"])
            self.assertEqual(sorted(both_data["skills"]), [".agents/skills/session-start/SKILL.md", ".claude/skills/session-start/SKILL.md"])

    def test_build_repo_baseline_collects_ci_readme_stack_entrypoints_and_gotchas(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp) / "repo"
            repo.mkdir()
            (repo / "README.md").write_text("# Demo\n\nRuns the shop worker for tests.\n\n## Gotchas\nDo not skip readback.\n")
            (repo / "AGENTS.md").write_text("- Never skip validation.\n")
            (repo / "package.json").write_text(
                json.dumps(
                    {
                        "description": "Demo package",
                        "packageManager": "pnpm@9.0.0",
                        "scripts": {"dev": "vite", "test": "vitest"},
                    }
                )
            )
            (repo / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")
            workflows = repo / ".github" / "workflows"
            workflows.mkdir(parents=True)
            (workflows / "ci.yml").write_text("jobs:\n  test:\n    steps:\n      - run: pnpm test\n")

            result = run_script("build_repo_baseline.py", "--repo", repo)

            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertTrue(data["purpose_evidence"])
            self.assertTrue(data["entrypoint_evidence"])
            self.assertTrue(data["stack_evidence"])
            self.assertTrue(data["gotcha_evidence"])
            self.assertTrue(any(item.get("command") == "pnpm test" and item.get("script") == "ci" for item in data["validation_evidence"]))

    def test_validate_outputs_blocks_secrets_and_unsupported_claims(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = pathlib.Path(tmp) / "bad.md"
            report.write_text(
                "\n".join(
                    [
                        "# Agent Learning Report",
                        "## Unsupported Claims",
                        "- user is weak at architecture.",
                        "## Evidence",
                        "- no source provided",
                        "secret=supersecretvalue",
                    ]
                )
            )

            result = run_script("validate_outputs.py", report)

            self.assertEqual(result.returncode, 1)
            self.assertIn("secret-like content", result.stderr)
            self.assertIn("unsupported claims section is not allowed", result.stderr)
            self.assertIn("psychological or ability claim", result.stderr)

    def test_validate_outputs_subject_names_env_extends_psych_pattern(self):
        """AGENT_LEARNING_SUBJECT_NAMES must extend the psychological-claim pattern."""
        import os as _os
        with tempfile.TemporaryDirectory() as tmp:
            report = pathlib.Path(tmp) / "named.md"
            report.write_text(
                "\n".join(
                    [
                        "# Agent Learning Report",
                        "## confirmed_current",
                        "- [confirmed_current] Lisa er svak paa arkitektur. source: notes.md",
                        "## memory_derived",
                        "## needs_verification",
                        "## agent_compensation",
                        "## self_healing_loop",
                    ]
                )
            )

            # Default pattern: "Lisa" is NOT a subject, so no psych error.
            base_env = {**_os.environ, "AGENT_LEARNING_SUBJECT_NAMES": ""}
            result = run_script("validate_outputs.py", report, env=base_env)
            self.assertNotIn("psychological or ability claim", result.stderr)

            # With env override, "Lisa" becomes a subject and the line fires.
            extended_env = {**_os.environ, "AGENT_LEARNING_SUBJECT_NAMES": "Lisa,Per"}
            result = run_script("validate_outputs.py", report, env=extended_env)
            self.assertIn("psychological or ability claim", result.stderr)

    def test_validate_outputs_requires_bucket_markers_and_verify_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = pathlib.Path(tmp) / "bad-schema.md"
            report.write_text(
                "\n".join(
                    [
                        "# Agent Learning Report",
                        "## confirmed_current",
                        "- Repo baseline has source files. source: baseline",
                        "## memory_derived",
                        "- [memory_derived] repeat_count=7; source: corpus",
                        "## needs_verification",
                        "- Assistant claims need checks. source: corpus",
                        "## agent_compensation",
                        "### domain: git-release",
                        "- marker: agent_compensation",
                        "- repeat_count: 7",
                        "- gate_category: release-gate",
                        "- gate: Inspect git status before commit.",
                        '- quote: "commit"',
                        "## self_healing_loop",
                        "- failure_signal -> candidate_gate -> validation_status -> next_session_load. source: corpus",
                    ]
                )
            )

            result = run_script("validate_outputs.py", report)

            self.assertEqual(result.returncode, 1)
            self.assertIn("confirmed_current bullet missing [confirmed_current]", result.stderr)
            self.assertIn("needs_verification bullet missing [needs_verification]", result.stderr)
            self.assertIn("needs_verification bullet missing verify:", result.stderr)
            self.assertIn("repeat_count must name its unit", result.stderr)
            self.assertIn("gate quote too weak", result.stderr)

    def test_validate_outputs_accepts_strict_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = pathlib.Path(tmp) / "good-schema.md"
            report.write_text(
                "\n".join(
                    [
                        "# Agent Learning Report",
                        "## confirmed_current",
                        "- [confirmed_current] Repo baseline has source files. source: AGENTS.md:1",
                        "## memory_derived",
                        "- [memory_derived] evidence: 2 matching user lines; quote: \"verify live runtime\" source: corpus",
                        "## needs_verification",
                        "- [needs_verification] Assistant claims need checks. verify: rerun live checks before reuse.",
                        "## agent_compensation",
                        "### domain: validation",
                        "- marker: agent_compensation",
                        "- level: 2",
                        "- matching_lines: 2",
                        "- gate_category: validation-check",
                        "- gate: Run validation before claiming completion.",
                        '- quote: "verify live runtime"',
                        "## self_healing_loop",
                        "- failure_signal -> candidate_gate -> validation_status -> next_session_load. source: corpus",
                    ]
                )
            )

            result = run_script("validate_outputs.py", report)

            self.assertEqual(result.returncode, 0, result.stderr)

    def test_validate_outputs_rejects_weak_confirmed_current_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = pathlib.Path(tmp) / "weak-source.md"
            report.write_text(
                "\n".join(
                    [
                        "# Agent Learning Report",
                        "## confirmed_current",
                        "- [confirmed_current] Repo facts discovered. source: baseline",
                        "## memory_derived",
                        "- [memory_derived] Prior correction exists. source: corpus",
                        "## needs_verification",
                        "- [needs_verification] Runtime may drift. verify: run live check.",
                        "## agent_compensation",
                        "### domain: validation",
                        "- gate_category: validation-check",
                        "- gate: Run validation before completion.",
                        "## self_healing_loop",
                        "- failure_signal -> candidate_gate -> validation_status -> next_session_load. source: corpus",
                    ]
                )
            )

            result = run_script("validate_outputs.py", report)

            self.assertEqual(result.returncode, 1)
            self.assertIn("confirmed_current source must name", result.stderr)

    def test_distill_learning_emits_evidence_backed_report_and_dry_run_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            corpus = tmp_path / "corpus.txt"
            baseline = tmp_path / "baseline.json"
            out = tmp_path / "report.md"
            corpus.write_text(
                "\n".join(
                    [
                        "user: whats next",
                        "assistant: I checked AGENTS.md and docs/plans/BACKLOG.md before choosing one task.",
                        "user: ikke spekuler, verifiser",
                        "user: <command-message>compound-engineering:ce-commit-push-pr</command-message>",
                    ]
                )
            )
            baseline.write_text(
                json.dumps(
                    {
                        "repo": "/tmp/repo",
                        "source_files": ["AGENTS.md", "docs/plans/BACKLOG.md"],
                        "instruction_evidence": [
                            {
                                "kind": "rule",
                                "fact": "Instruction rule: Before substantial work, use the repo-local skill inventory.",
                                "source": "AGENTS.md:4",
                            }
                        ],
                        "validation_commands": ["pnpm test"],
                        "skills": [".agents/skills/next-session/SKILL.md"],
                    }
                )
            )

            result = run_script(
                "distill_learning.py",
                "--corpus",
                corpus,
                "--baseline",
                baseline,
                "--output",
                out,
                "--mode",
                "all",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = out.read_text()
            self.assertIn("confirmed_current", report)
            self.assertIn("agent_compensation", report)
            self.assertIn('"ikke spekuler, verifiser"', report)
            self.assertIn("source: AGENTS.md:1", report)
            self.assertIn("Before substantial work, use the repo-local skill inventory", report)
            self.assertIn("source: AGENTS.md:4", report)
            self.assertIn("source: package.json:", report)
            self.assertNotIn("command-message", report)
            self.assertIn("append-only updates: dry-run", result.stdout)

    def test_distill_learning_turns_repeated_failure_signals_into_concrete_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            corpus = tmp_path / "corpus.txt"
            baseline = tmp_path / "baseline.json"
            out = tmp_path / "report.md"
            corpus.write_text(
                "\n".join(
                    [
                        "user: whats next",
                        "user: whats next [session_ref=s1]",
                        "user: ikke spekuler, verifiser live først",
                        "user: sjekk faktisk Cloudflare runtime før du sier deploy er frisk",
                        "user: scope drift, ikke bygg UI i denne pakken",
                        "user: hold deg til do-not-build listen",
                        "user: Quick3 write må ha smoke og readback",
                        "user: Q3 additionalTexts må leses tilbake etter append",
                        "user: Teams/M365 må sjekkes live i tenant før forslag",
                        "user: commit og push når validering passerer",
                    ]
                )
            )
            baseline.write_text(
                json.dumps(
                    {
                        "repo": "/tmp/repo",
                        "source_files": ["AGENTS.md", "docs/plans/BACKLOG.md"],
                        "validation_commands": ["pnpm test", "pnpm typecheck"],
                        "skills": [".agents/skills/session-start/SKILL.md"],
                    }
                )
            )

            result = run_script(
                "distill_learning.py",
                "--corpus",
                corpus,
                "--baseline",
                baseline,
                "--output",
                out,
                "--mode",
                "all",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = out.read_text()
            self.assertIn("## self_healing_loop", report)
            self.assertIn("domain: repo-workflow", report)
            self.assertIn("domain: validation", report)
            self.assertIn("domain: scope-drift", report)
            self.assertNotIn("domain: quick3", report)
            self.assertNotIn("domain: cloudflare", report)
            self.assertNotIn("domain: teams-m365", report)
            self.assertIn("failure_signal", report)
            self.assertIn("matching_lines", report)

    def test_distill_learning_can_use_tm_norge_domain_preset(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            corpus = tmp_path / "corpus.txt"
            baseline = tmp_path / "baseline.json"
            out = tmp_path / "report.md"
            corpus.write_text(
                "\n".join(
                    [
                        "user: whats next",
                        "user: whats next [session_ref=s1]",
                        "user: ikke spekuler, verifiser live først",
                        "user: sjekk faktisk Cloudflare runtime før du sier deploy er frisk",
                        "user: scope drift, ikke bygg UI i denne pakken",
                        "user: hold deg til do-not-build listen",
                        "user: Quick3 write må ha smoke og readback",
                        "user: Q3 additionalTexts må leses tilbake etter append",
                        "user: Teams/M365 må sjekkes live i tenant før forslag",
                        "user: commit og push når validering passerer",
                    ]
                )
            )
            baseline.write_text(
                json.dumps(
                    {
                        "repo": "/tmp/repo",
                        "source_files": ["AGENTS.md", "docs/plans/BACKLOG.md"],
                        "validation_commands": ["pnpm test", "pnpm typecheck"],
                        "skills": [".agents/skills/session-start/SKILL.md"],
                    }
                )
            )

            result = run_script(
                "distill_learning.py",
                "--corpus",
                corpus,
                "--baseline",
                baseline,
                "--output",
                out,
                "--mode",
                "all",
                "--domain-preset",
                "tm-norge",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = out.read_text()
            self.assertIn("domain: external-runtime-truth", report)
            self.assertIn("domain: scope-drift", report)
            self.assertIn("domain: quick3", report)
            self.assertIn("domain: cloudflare", report)
            self.assertIn("domain: teams-m365", report)
            self.assertIn("failure_signal", report)
            self.assertIn("gate_category: live-check", report)
            self.assertIn("gate_category: readback-check", report)
            self.assertIn("matching_lines", report)
            self.assertIn("session_refs: s1", report)
            self.assertGreaterEqual(report.count("- gate:"), 7)

    def test_distill_learning_reads_domain_rules_from_repo_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            repo = tmp_path / "repo"
            repo.mkdir()
            rules = tmp_path / "rules.json"
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
            (repo / ".agent-learning.json").write_text(json.dumps({"domain_rules": str(rules)}), encoding="utf-8")
            corpus = tmp_path / "corpus.txt"
            baseline = tmp_path / "baseline.json"
            out = tmp_path / "report.md"
            corpus.write_text("user: customsignal happened [session_ref=custom-1]\n")
            baseline.write_text(json.dumps({"repo": str(repo), "source_files": [], "validation_commands": [], "skills": []}))

            result = run_script("distill_learning.py", "--corpus", corpus, "--baseline", baseline, "--output", out)

            self.assertEqual(result.returncode, 0, result.stderr)
            report = out.read_text()
            self.assertIn("domain: custom-domain", report)
            self.assertIn("gate_category: custom-gate", report)
            self.assertIn("session_refs: custom-1", report)

    def test_distill_learning_rejects_invalid_domain_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            rules = tmp_path / "rules.json"
            corpus = tmp_path / "corpus.txt"
            baseline = tmp_path / "baseline.json"
            out = tmp_path / "report.md"
            rules.write_text(json.dumps({"schema_version": 1, "rules": [{"domain": "broken"}]}), encoding="utf-8")
            corpus.write_text("user: anything\n")
            baseline.write_text(json.dumps({"repo": "/tmp/repo"}))

            result = run_script(
                "distill_learning.py",
                "--corpus",
                corpus,
                "--baseline",
                baseline,
                "--output",
                out,
                "--domain-rules",
                rules,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("missing", result.stderr)

    def test_distill_learning_reads_prior_report_and_proposes_evergreen_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            personal = tmp_path / "personal"
            reports = personal / "reports" / "agent-learning"
            reports.mkdir(parents=True)
            (personal / "insights.md").write_text("")
            (personal / "learning.md").write_text("")
            (personal / "preferences.md").write_text("I prefer Yarn for JavaScript.\n")
            (reports / "2026-01-01.md").write_text(
                "# Agent Learning Report\n\n## agent_compensation\n### domain: validation\n- level: 2\n- gate_category: validation-check\n- gate: Run validation.\n"
            )
            corpus = tmp_path / "corpus.txt"
            baseline = tmp_path / "baseline.json"
            out = tmp_path / "report.md"
            corpus.write_text("user: verify before completion with pnpm [session_ref=prior-test]\n")
            baseline.write_text(
                json.dumps(
                    {
                        "repo": "/tmp/repo",
                        "source_files": ["AGENTS.md"],
                        "source_evidence": [{"fact": "`AGENTS.md` exists.", "source": "AGENTS.md:1"}],
                        "validation_commands": ["pnpm test", "pnpm lint", "pnpm typecheck", "pnpm build"],
                        "validation_evidence": [{"command": "pnpm test", "script": "test", "source": "package.json:4"}],
                        "skills": [],
                    }
                )
            )

            result = run_script(
                "distill_learning.py",
                "--corpus",
                corpus,
                "--baseline",
                baseline,
                "--output",
                out,
                "--personal",
                personal,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = out.read_text()
            self.assertIn("Prior agent-learning report found", report)
            self.assertIn("level_change: validation: 2 -> 3", report)
            self.assertIn("## proposed_evergreen_diffs", report)
            self.assertIn("evidence_count:", report)

    def test_distill_learning_normalizes_double_quotes_inside_report_quotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            corpus = tmp_path / "corpus.txt"
            baseline = tmp_path / "baseline.json"
            out = tmp_path / "report.md"
            corpus.write_text('user: verify "live runtime" before claiming completion\n')
            baseline.write_text(
                json.dumps(
                    {
                        "repo": "/tmp/repo",
                        "source_files": ["AGENTS.md"],
                        "validation_commands": ["pnpm test"],
                        "skills": [],
                    }
                )
            )

            result = run_script("distill_learning.py", "--corpus", corpus, "--baseline", baseline, "--output", out)

            self.assertEqual(result.returncode, 0, result.stderr)
            report = out.read_text()
            self.assertIn('quote: "verify \'live runtime\' before claiming completion"', report)
            self.assertNotIn('quote: "verify "live runtime"', report)

    def test_distill_learning_write_archives_report_and_appends_personal_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            personal = tmp_path / "personal"
            personal.mkdir()
            (personal / "insights.md").write_text("[2026-05-01] Existing insight.\n")
            (personal / "learning.md").write_text("[2026-05-01] Existing learning.\n")
            corpus = tmp_path / "corpus.txt"
            baseline = tmp_path / "baseline.json"
            out = tmp_path / "report.md"
            corpus.write_text("user: ikke spekuler, verifiser\n")
            baseline.write_text(
                json.dumps(
                    {
                        "repo": "/tmp/repo",
                        "source_files": ["AGENTS.md"],
                        "validation_commands": ["pnpm test"],
                        "skills": [],
                    }
                )
            )

            result = run_script(
                "distill_learning.py",
                "--corpus",
                corpus,
                "--baseline",
                baseline,
                "--output",
                out,
                "--mode",
                "all",
                "--write",
                "--personal",
                personal,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("append-only updates: written", result.stdout)
            self.assertIn("ikke spekuler, verifiser", (personal / "insights.md").read_text())
            # learning.md is now per-gate (>= L2) rather than a generic blurb.
            # The corpus here only has one matching line so no L2+ gate emerges;
            # only the pre-existing line should remain.
            learning_text = (personal / "learning.md").read_text()
            self.assertIn("[2026-05-01] Existing learning.", learning_text)
            self.assertTrue((personal / "reports" / "agent-learning").exists())
            metrics_path = personal / "reports" / "agent-learning" / "metrics.jsonl"
            self.assertTrue(metrics_path.is_file(), "metrics.jsonl should be written on --write")
            metrics_line = metrics_path.read_text().strip().splitlines()[-1]
            metrics = json.loads(metrics_line)
            self.assertIn("totals", metrics)
            self.assertIn("by_level", metrics)
            self.assertEqual(metrics["repo"], "/tmp/repo")

    def test_distill_learning_write_exports_approved_gates_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            personal = tmp_path / "personal"
            personal.mkdir()
            (personal / "insights.md").write_text("[2026-05-01] Existing insight.\n")
            (personal / "learning.md").write_text("[2026-05-01] Existing learning.\n")
            corpus = tmp_path / "corpus.txt"
            baseline = tmp_path / "baseline.json"
            out = tmp_path / "report.md"
            gates = tmp_path / "approved-gates.md"
            corpus.write_text(
                "\n".join(
                    [
                        "user: whats next",
                        "user: ikke spekuler, verifiser",
                        "user: Cloudflare deploy må sjekkes live",
                    ]
                )
            )
            baseline.write_text(
                json.dumps(
                    {
                        "repo": "/tmp/repo",
                        "source_files": ["AGENTS.md"],
                        "validation_commands": ["pnpm test"],
                        "skills": [],
                    }
                )
            )

            result = run_script(
                "distill_learning.py",
                "--corpus",
                corpus,
                "--baseline",
                baseline,
                "--output",
                out,
                "--mode",
                "all",
                "--write",
                "--personal",
                personal,
                "--approved-gates-output",
                gates,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            registry = gates.read_text()
            self.assertIn("# Approved Agent Gates", registry)
            self.assertIn("source_report:", registry)
            self.assertIn("domain: repo-workflow", registry)
            self.assertIn("domain: validation", registry)
            self.assertIn("gate_category:", registry)
            self.assertIn("gate:", registry)
            self.assertNotIn("quote:", registry)

    def test_distill_learning_dry_run_refuses_approved_gates_inside_personal(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            personal = tmp_path / "personal"
            personal.mkdir()
            (personal / "insights.md").write_text("[2026-05-01] Existing insight.\n")
            (personal / "learning.md").write_text("[2026-05-01] Existing learning.\n")
            corpus = tmp_path / "corpus.txt"
            baseline = tmp_path / "baseline.json"
            out = tmp_path / "report.md"
            gates = personal / "reports" / "agent-learning" / "latest-approved-gates.md"
            corpus.write_text("user: whats next\nuser: ikke spekuler, verifiser\n")
            baseline.write_text(
                json.dumps(
                    {
                        "repo": "/tmp/repo",
                        "source_files": ["AGENTS.md"],
                        "validation_commands": ["pnpm test"],
                        "skills": [],
                    }
                )
            )

            result = run_script(
                "distill_learning.py",
                "--corpus",
                corpus,
                "--baseline",
                baseline,
                "--output",
                out,
                "--mode",
                "all",
                "--personal",
                personal,
                "--approved-gates-output",
                gates,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("--approved-gates-output inside --personal requires --write", result.stderr)

    def test_distill_learning_write_requires_explicit_personal_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            corpus = tmp_path / "corpus.txt"
            baseline = tmp_path / "baseline.json"
            out = tmp_path / "report.md"
            corpus.write_text("user: verify before claiming done\n", encoding="utf-8")
            baseline.write_text(
                json.dumps(
                    {
                        "repo": str(tmp_path),
                        "source_files": ["AGENTS.md"],
                        "source_evidence": [{"fact": "`AGENTS.md` exists.", "source": "AGENTS.md:1"}],
                    }
                ),
                encoding="utf-8",
            )

            result = run_script("distill_learning.py", "--corpus", corpus, "--baseline", baseline, "--output", out, "--write")

            self.assertEqual(result.returncode, 1)
            self.assertIn("--write requires --user", result.stderr)
            self.assertIn("AGENT_LEARNING_USER", result.stderr)
            self.assertFalse(out.exists())

    def test_pressure_harness_passes(self):
        result = run_script("run_pressure_tests.py")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("pressure checks passed", result.stdout)

    def test_distill_learning_emits_html_report_alongside_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            corpus = tmp_path / "corpus.txt"
            baseline = tmp_path / "baseline.json"
            out = tmp_path / "report.md"
            corpus.write_text(
                "\n".join(
                    [
                        "user: whats next [session_ref=s1]",
                        "user: ikke spekuler, verifiser live foerst [session_ref=s1]",
                        "user: sjekk faktisk Cloudflare runtime foer du sier deploy er frisk [session_ref=s2]",
                        "user: scope drift, ikke bygg UI i denne pakken [session_ref=s2]",
                        "user: hold deg til do-not-build listen [session_ref=s3]",
                        "user: commit og push naar validering passerer [session_ref=s3]",
                    ]
                )
            )
            baseline.write_text(
                json.dumps(
                    {
                        "repo": "/tmp/repo",
                        "source_files": ["AGENTS.md", "docs/plans/BACKLOG.md"],
                        "validation_commands": ["pnpm test"],
                        "skills": [".agents/skills/session-start/SKILL.md"],
                    }
                )
            )

            result = run_script(
                "distill_learning.py",
                "--corpus", corpus,
                "--baseline", baseline,
                "--output", out,
                "--mode", "all",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            html_path = out.with_suffix(".html")
            self.assertTrue(html_path.exists(), "html report should be written next to .md")
            html = html_path.read_text(encoding="utf-8")
            self.assertIn("<!DOCTYPE html>", html)
            self.assertIn("Agent Learning Report", html)
            self.assertIn("Approved gates", html)
            self.assertIn("Self-healing loop", html)
            self.assertIn("Memory derived", html)
            self.assertIn("Skill health", html)
            self.assertIn("Confirmed current", html)
            self.assertIn("Next agent brief", html)
            self.assertIn('id="report-payload"', html)
            self.assertIn("<svg", html)
            self.assertIn("html:", result.stdout)

    def test_distill_learning_no_html_flag_skips_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            corpus = tmp_path / "corpus.txt"
            baseline = tmp_path / "baseline.json"
            out = tmp_path / "report.md"
            corpus.write_text("user: whats next\n")
            baseline.write_text(json.dumps({"repo": "/tmp/repo"}))
            result = run_script(
                "distill_learning.py",
                "--corpus", corpus,
                "--baseline", baseline,
                "--output", out,
                "--no-html",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(out.with_suffix(".html").exists())

    def test_render_html_report_standalone_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            corpus = tmp_path / "corpus.txt"
            baseline = tmp_path / "baseline.json"
            html_out = tmp_path / "report.html"
            payload_out = tmp_path / "payload.json"
            corpus.write_text("user: whats next\nuser: verifiser live foerst\n")
            baseline.write_text(json.dumps({"repo": "/tmp/repo"}))
            result = run_script(
                "render_html_report.py",
                "--corpus", corpus,
                "--baseline", baseline,
                "--output", html_out,
                "--payload-json", payload_out,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(html_out.exists())
            payload = json.loads(payload_out.read_text(encoding="utf-8"))
            self.assertIn("totals", payload)
            self.assertIn("agent_compensation", payload)
            self.assertEqual(payload["repo"], "/tmp/repo")


if __name__ == "__main__":
    unittest.main()
