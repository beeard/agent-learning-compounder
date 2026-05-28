"""Unit tests for session_context_render — pure synthesizer functions.

These tests cover the render helpers in isolation. Integration-level tests
(full alc_init flow, file-system writes, alc_query calls) remain in
test_alc_init.py.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "bin"))

from session_context_render import (  # noqa: E402
    render_ce_usage_md,
    render_doc_contract_md,
    render_runtime_summary_md,
    render_session_context,
)


class RenderRuntimeSummaryMdTests(unittest.TestCase):
    def test_empty_summary_returns_fallback_prose(self) -> None:
        result = render_runtime_summary_md({})
        self.assertIn("No durable runtime history yet", result)
        self.assertIn("hooks fire", result)

    def test_all_zero_totals_returns_fallback(self) -> None:
        summary = {
            "actors": {"total": 0, "by_actor_kind": []},
            "applies": [],
            "outcomes": [],
            "recommendations": [],
            "pending_patches": [],
        }
        result = render_runtime_summary_md(summary)
        self.assertIn("No durable runtime history yet", result)

    def test_populated_actors_renders_activity_line(self) -> None:
        summary = {
            "actors": {
                "total": 10,
                "by_actor_kind": [
                    {"actor_kind": "skill", "count": 7, "unique_actors": 3},
                    {"actor_kind": "hook", "count": 3, "unique_actors": 1},
                ],
            },
            "applies": [],
            "outcomes": [],
            "recommendations": [],
            "pending_patches": [],
        }
        result = render_runtime_summary_md(summary)
        self.assertIn("Activity (7d)", result)
        self.assertIn("10 events", result)
        self.assertIn("skill", result)
        self.assertIn("hook", result)

    def test_applies_renders_patch_breakdown(self) -> None:
        summary = {
            "actors": {"total": 0, "by_actor_kind": []},
            "applies": [
                {"event": "patch_applied"},
                {"event": "patch_applied"},
                {"event": "patch_rejected"},
            ],
            "outcomes": [],
            "recommendations": [],
            "pending_patches": [],
        }
        result = render_runtime_summary_md(summary)
        self.assertIn("Patches (7d)", result)
        self.assertIn("applied", result)
        self.assertIn("rejected", result)

    def test_recs_and_pending_renders_awaiting_review(self) -> None:
        summary = {
            "actors": {"total": 0, "by_actor_kind": []},
            "applies": [],
            "outcomes": [],
            "recommendations": [{"id": "r1"}],
            "pending_patches": [{"id": "p1"}, {"id": "p2"}],
        }
        result = render_runtime_summary_md(summary)
        self.assertIn("Awaiting review", result)
        self.assertIn("1 recommendation(s)", result)
        self.assertIn("2 pending patch(es)", result)

    def test_outcomes_renders_judge_verdicts(self) -> None:
        summary = {
            "actors": {"total": 0, "by_actor_kind": []},
            "applies": [],
            "outcomes": [{"id": "o1"}, {"id": "o2"}],
            "recommendations": [],
            "pending_patches": [],
        }
        result = render_runtime_summary_md(summary)
        self.assertIn("Judge verdicts (7d)", result)
        self.assertIn("2 event(s)", result)


class RenderCeUsageMdTests(unittest.TestCase):
    def test_empty_list_returns_fallback(self) -> None:
        result = render_ce_usage_md([])
        self.assertIn("No tracked invocations", result)
        self.assertIn("compound-engineering", result)

    def test_rows_render_skill_names_and_counts(self) -> None:
        rows = [
            {"actor_name": "ce-plan", "count": 5, "last_used_ts": "2026-05-20T10:00:00"},
            {"actor_name": "ce-work", "count": 3, "last_used_ts": "2026-05-18T08:30:00"},
        ]
        result = render_ce_usage_md(rows)
        self.assertIn("`ce-plan`", result)
        self.assertIn("5×", result)
        self.assertIn("2026-05-20", result)
        self.assertIn("`ce-work`", result)
        self.assertIn("3×", result)

    def test_capped_at_15_with_overflow_note(self) -> None:
        rows = [
            {"actor_name": f"ce-skill-{i}", "count": i + 1, "last_used_ts": "2026-01-01T00:00:00"}
            for i in range(20)
        ]
        result = render_ce_usage_md(rows)
        lines = result.strip().splitlines()
        # 15 skill lines + 1 overflow note
        self.assertEqual(len(lines), 16)
        self.assertIn("5 more", result)
        self.assertIn("alc_query.get_skill_usage_summary", result)

    def test_missing_last_used_ts_renders_question_mark(self) -> None:
        rows = [{"actor_name": "ce-brainstorm", "count": 1, "last_used_ts": None}]
        result = render_ce_usage_md(rows)
        self.assertIn("last ?", result)


class RenderDocContractMdTests(unittest.TestCase):
    def _make_rows(self, *, found: bool) -> list[dict]:
        return [
            {
                "label": "STRATEGY.md",
                "paths_checked": ["STRATEGY.md"],
                "found": "STRATEGY.md" if found else None,
                "generator": "ce-strategy",
                "tier": "anchor",
            },
            {
                "label": "Repo guide",
                "paths_checked": ["AGENTS.md", "CLAUDE.md"],
                "found": "CLAUDE.md" if found else None,
                "generator": None,
                "tier": "anchor",
            },
            {
                "label": "ARCHITECTURE.md",
                "paths_checked": ["ARCHITECTURE.md"],
                "found": "ARCHITECTURE.md" if found else None,
                "generator": "improve-codebase-architecture",
                "tier": "architecture",
            },
        ]

    def test_all_present_shows_tick_marks(self) -> None:
        result = render_doc_contract_md(self._make_rows(found=True), ce_installed=False)
        self.assertIn("✓", result)
        self.assertNotIn("missing", result)
        self.assertIn("**Anchors:**", result)
        self.assertIn("**Architecture:**", result)

    def test_missing_with_ce_installed_shows_generate_hint(self) -> None:
        result = render_doc_contract_md(self._make_rows(found=False), ce_installed=True)
        self.assertIn("✗", result)
        self.assertIn("missing", result)
        self.assertIn("generate via `/ce-strategy`", result)
        self.assertIn("generate via `/improve-codebase-architecture`", result)

    def test_missing_without_ce_shows_manual_fallback(self) -> None:
        result = render_doc_contract_md(self._make_rows(found=False), ce_installed=False)
        self.assertIn("install compound-engineering", result)
        self.assertIn("write manually", result)
        # Should NOT show bare "generate via" without the install step
        self.assertNotIn("generate via `/ce-strategy`", result)

    def test_row_without_generator_shows_no_hint(self) -> None:
        rows = [
            {
                "label": "Repo guide",
                "paths_checked": ["AGENTS.md", "CLAUDE.md"],
                "found": None,
                "generator": None,
                "tier": "anchor",
            }
        ]
        result = render_doc_contract_md(rows, ce_installed=True)
        self.assertIn("missing", result)
        self.assertNotIn("generate via", result)
        self.assertNotIn("install compound-engineering", result)

    def test_tiers_are_grouped_with_headers(self) -> None:
        rows = [
            {"label": "STRATEGY.md", "paths_checked": ["STRATEGY.md"],
             "found": None, "generator": "ce-strategy", "tier": "anchor"},
            {"label": "ARCHITECTURE.md", "paths_checked": ["ARCHITECTURE.md"],
             "found": None, "generator": "improve-codebase-architecture", "tier": "architecture"},
            {"label": "Plans", "paths_checked": ["docs/plans"],
             "found": None, "generator": "ce-plan", "tier": "workflow"},
        ]
        result = render_doc_contract_md(rows, ce_installed=False)
        self.assertIn("**Anchors:**", result)
        self.assertIn("**Architecture:**", result)
        self.assertIn("**Workflow surfaces:**", result)


class RenderSessionContextTests(unittest.TestCase):
    def _minimal_profile(self) -> dict:
        return {
            "name": "myrepo",
            "abspath": "/home/user/myrepo",
            "languages": {"python": 42},
            "frameworks": ["fastapi"],
            "package_managers": ["pip/poetry/uv"],
            "has_tests": True,
            "has_frontend": False,
            "monorepo": False,
            "has_git": True,
        }

    def _minimal_mcp(self) -> dict:
        return {"status": "green", "tools": ["get_gates", "report_outcome"], "error": None}

    def test_includes_all_top_level_headers(self) -> None:
        result = render_session_context(self._minimal_profile(), self._minimal_mcp())
        self.assertIn("# Session context — agent-learning-compounder", result)
        self.assertIn("## Freshness", result)
        self.assertIn("## Repo profile", result)
        self.assertIn("## ALC MCP status", result)
        self.assertIn("## Runtime summary", result)
        self.assertIn("## Documentation contract", result)
        self.assertIn("## CE-family skill usage", result)
        self.assertIn("## Compound-engineering playbook", result)

    def test_workspace_facts_render_when_present(self) -> None:
        result = render_session_context(
            self._minimal_profile(),
            self._minimal_mcp(),
            workspace_facts={"branch": "dev", "dirty_state": "2 files", "active_plan": "plan.md"},
        )
        self.assertIn("Branch", result)
        self.assertIn("dev", result)
        self.assertIn("plan.md", result)

    def test_profile_fields_rendered(self) -> None:
        result = render_session_context(self._minimal_profile(), self._minimal_mcp())
        self.assertIn("python (42)", result)
        self.assertIn("fastapi", result)
        self.assertIn("pip/poetry/uv", result)
        self.assertIn("myrepo", result)
        self.assertIn("/home/user/myrepo", result)

    def test_mcp_tools_listed(self) -> None:
        result = render_session_context(self._minimal_profile(), self._minimal_mcp())
        self.assertIn("`get_gates`", result)
        self.assertIn("`report_outcome`", result)

    def test_mcp_error_included(self) -> None:
        mcp = {"status": "no_tools", "tools": [], "error": "server timed out"}
        result = render_session_context(self._minimal_profile(), mcp)
        self.assertIn("server timed out", result)

    def test_optional_sections_use_passed_content(self) -> None:
        result = render_session_context(
            self._minimal_profile(),
            self._minimal_mcp(),
            playbook_md="## My playbook",
            runtime_md="- **Activity (7d):** 5 events",
            ce_usage_md="- `ce-plan` — 3×",
            doc_contract_md="**Anchors:** ✓",
        )
        self.assertIn("## My playbook", result)
        self.assertIn("Activity (7d)", result)
        self.assertIn("`ce-plan`", result)
        self.assertIn("**Anchors:**", result)

    def test_empty_optional_sections_show_fallbacks(self) -> None:
        result = render_session_context(self._minimal_profile(), self._minimal_mcp())
        self.assertIn("_Not computed._", result)
        self.assertIn("_Doc contract not checked._", result)
        self.assertIn("_No playbook generated._", result)

    def test_no_languages_shows_none_detected(self) -> None:
        profile = self._minimal_profile()
        profile["languages"] = {}
        result = render_session_context(profile, self._minimal_mcp())
        self.assertIn("_none detected_", result)

    def test_output_is_string(self) -> None:
        result = render_session_context(self._minimal_profile(), self._minimal_mcp())
        self.assertIsInstance(result, str)
        self.assertTrue(result.startswith("# Session context"))


if __name__ == "__main__":
    unittest.main()
