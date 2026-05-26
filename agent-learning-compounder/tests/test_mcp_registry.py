"""Tests for auto-registered MCP handlers (deepening candidate #01)."""

from __future__ import annotations

import asyncio
import inspect
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"
for _p in (str(BIN), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from alc_mcp.catalog import MCP_TOOLS
from alc_mcp.server import (
    TOOL_HANDLERS,
    _agent_kind,
    _make_handler,
)


def _run(coro):
    return asyncio.run(coro)


class TestMakeHandlerResolvesAllCatalogEntries(unittest.TestCase):
    """Every entry in MCP_TOOLS must resolve to a callable handler."""

    def test_every_catalog_entry_has_a_handler(self):
        for name in MCP_TOOLS:
            self.assertIn(name, TOOL_HANDLERS, f"missing handler for {name!r}")
            self.assertTrue(callable(TOOL_HANDLERS[name]), f"handler for {name!r} is not callable")

    def test_list_capabilities_handler_present(self):
        # list_capabilities is not in MCP_TOOLS but must be in TOOL_HANDLERS
        self.assertIn("list_capabilities", TOOL_HANDLERS)
        self.assertTrue(callable(TOOL_HANDLERS["list_capabilities"]))

    def test_total_handler_count_matches_catalog_plus_list_capabilities(self):
        # 10 catalog tools + list_capabilities = 11
        self.assertEqual(len(TOOL_HANDLERS), len(MCP_TOOLS) + 1)

    def test_make_handler_returns_async_callable(self):
        import asyncio
        for name, spec in MCP_TOOLS.items():
            handler = TOOL_HANDLERS[name]
            self.assertTrue(
                inspect.iscoroutinefunction(handler),
                f"handler for {name!r} is not a coroutine function",
            )


class TestHandlerDispatch(unittest.TestCase):
    """Handlers dispatch correctly to their backing functions."""

    def _fake_repo(self) -> tuple[tempfile.TemporaryDirectory, Path]:
        td = tempfile.TemporaryDirectory()
        repo = Path(td.name) / "repo"
        repo.mkdir(parents=True)
        return td, repo

    def test_get_gates_calls_backing(self):
        td, repo = self._fake_repo()
        try:
            with patch("alc_query.get_gates", return_value=[{"gate": "x"}]) as mock_fn:
                result = _run(TOOL_HANDLERS["get_gates"]({"repo": str(repo), "scope": "tests"}))
            mock_fn.assert_called_once()
            call_kwargs = mock_fn.call_args
            # Second positional arg (or kwarg) should be the scope
            self.assertEqual(result, [{"gate": "x"}])
        finally:
            td.cleanup()

    def test_get_skill_context_calls_backing(self):
        td, repo = self._fake_repo()
        try:
            with patch("alc_query.get_skill_context", return_value="# skill ctx") as mock_fn:
                result = _run(TOOL_HANDLERS["get_skill_context"]({"repo": str(repo)}))
            mock_fn.assert_called_once()
            self.assertEqual(result, "# skill ctx")
        finally:
            td.cleanup()

    def test_get_recommendations_calls_backing(self):
        td, repo = self._fake_repo()
        try:
            with patch("alc_query.get_recommendations", return_value=[]) as mock_fn:
                result = _run(TOOL_HANDLERS["get_recommendations"]({"repo": str(repo)}))
            mock_fn.assert_called_once()
            self.assertEqual(result, [])
        finally:
            td.cleanup()

    def test_list_pending_patches_calls_backing(self):
        td, repo = self._fake_repo()
        try:
            with patch("alc_query.get_pending_patches", return_value=[]) as mock_fn:
                result = _run(TOOL_HANDLERS["list_pending_patches"]({"repo": str(repo)}))
            mock_fn.assert_called_once()
            self.assertEqual(result, [])
        finally:
            td.cleanup()

    def test_get_dashboard_url_calls_backing(self):
        with patch("state_handle.dashboard_url", return_value="http://localhost:8080") as mock_fn:
            result = _run(TOOL_HANDLERS["get_dashboard_url"]({"repo": "/tmp/fake"}))
        mock_fn.assert_called_once_with(repo="/tmp/fake")
        self.assertEqual(result, "http://localhost:8080")

    def test_propose_gate_calls_backing(self):
        td, repo = self._fake_repo()
        try:
            with patch("alc_propose.propose_gate", return_value={"queue_id": "q-1"}) as mock_fn:
                result = _run(TOOL_HANDLERS["propose_gate"]({
                    "repo": str(repo),
                    "domain": "tests",
                    "category": "validation",
                    "gate": "Run tests first.",
                }))
            mock_fn.assert_called_once()
            self.assertEqual(result, {"queue_id": "q-1"})
        finally:
            td.cleanup()

    def test_propose_apply_calls_backing(self):
        td, repo = self._fake_repo()
        try:
            with patch("alc_propose.propose_apply", return_value={"command": "alc apply patch-1"}) as mock_fn:
                result = _run(TOOL_HANDLERS["propose_apply"]({
                    "repo": str(repo),
                    "patch_id": "patch-1",
                }))
            mock_fn.assert_called_once()
            self.assertEqual(result, {"command": "alc apply patch-1"})
        finally:
            td.cleanup()

    def test_list_capabilities_returns_catalog_dicts(self):
        result = _run(TOOL_HANDLERS["list_capabilities"]({"repo": "/tmp/fake"}))
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), len(MCP_TOOLS))
        ids = {item["id"] for item in result}
        expected_ids = {spec.id for spec in MCP_TOOLS.values()}
        self.assertEqual(ids, expected_ids)


class TestReportOutcomeOverride(unittest.TestCase):
    """report_outcome alias mapping and return-value wrapping."""

    def _fake_repo(self) -> tuple[tempfile.TemporaryDirectory, Path]:
        td = tempfile.TemporaryDirectory()
        repo = Path(td.name) / "repo"
        repo.mkdir(parents=True)
        return td, repo

    def test_wraps_return_value(self):
        td, repo = self._fake_repo()
        try:
            with patch("alc_propose.report_outcome", return_value="evt-42") as mock_fn:
                result = _run(TOOL_HANDLERS["report_outcome"]({
                    "repo": str(repo),
                    "recommendation_id": "rec-1",
                    "verdict": "accepted",
                    "reason": "useful",
                }))
            self.assertEqual(result, {"recorded": True, "event_id": "evt-42"})
        finally:
            td.cleanup()

    def test_alias_gate_id_and_outcome(self):
        td, repo = self._fake_repo()
        try:
            with patch("alc_propose.report_outcome", return_value="evt-99") as mock_fn:
                _run(TOOL_HANDLERS["report_outcome"]({
                    "repo": str(repo),
                    "gate_id": "g-1",
                    "outcome": "rejected",
                }))
            args, _kwargs = mock_fn.call_args
            # recommendation_id arg (second positional) should be gate_id value
            self.assertEqual(args[1], "g-1")
            # verdict arg (third positional) should be outcome value
            self.assertEqual(args[2], "rejected")
        finally:
            td.cleanup()

    def test_default_reason_when_missing(self):
        td, repo = self._fake_repo()
        try:
            with patch("alc_propose.report_outcome", return_value="evt-7") as mock_fn:
                _run(TOOL_HANDLERS["report_outcome"]({
                    "repo": str(repo),
                    "recommendation_id": "rec-2",
                    "verdict": "accepted",
                }))
            args, _kwargs = mock_fn.call_args
            self.assertEqual(args[3], "reported via mcp")
        finally:
            td.cleanup()


class TestReportAgentEventOverride(unittest.TestCase):
    """report_agent_event kind normalisation and return-value wrapping."""

    def _fake_repo(self) -> tuple[tempfile.TemporaryDirectory, Path]:
        td = tempfile.TemporaryDirectory()
        repo = Path(td.name) / "repo"
        repo.mkdir(parents=True)
        return td, repo

    def test_normalises_agent_dispatch_complete_kind(self):
        td, repo = self._fake_repo()
        try:
            with patch("alc_propose.report_agent_event", return_value="evt-10") as mock_fn:
                result = _run(TOOL_HANDLERS["report_agent_event"]({
                    "repo": str(repo),
                    "kind": "AgentDispatchComplete",
                    "actor_name": "builder",
                }))
            _args, kwargs = mock_fn.call_args
            # kind param must be normalised (passed as kwarg by factory closure)
            self.assertEqual(kwargs["kind"], "complete")
            self.assertEqual(result["event"], "agent_dispatch_complete")
        finally:
            td.cleanup()

    def test_normalises_agent_dispatch_prefix(self):
        td, repo = self._fake_repo()
        try:
            with patch("alc_propose.report_agent_event", return_value="evt-11") as mock_fn:
                result = _run(TOOL_HANDLERS["report_agent_event"]({
                    "repo": str(repo),
                    "kind": "agent_dispatch_start",
                    "actor_name": "planner",
                }))
            _args, kwargs = mock_fn.call_args
            self.assertEqual(kwargs["kind"], "start")
            self.assertEqual(result["event"], "agent_dispatch_start")
        finally:
            td.cleanup()

    def test_wraps_return_value(self):
        td, repo = self._fake_repo()
        try:
            with patch("alc_propose.report_agent_event", return_value="evt-20"):
                result = _run(TOOL_HANDLERS["report_agent_event"]({
                    "repo": str(repo),
                    "kind": "complete",
                    "actor_name": "tester",
                }))
            self.assertTrue(result["recorded"])
            self.assertEqual(result["event_id"], "evt-20")
        finally:
            td.cleanup()

    def test_defaults_actor_name_to_mcp_caller(self):
        td, repo = self._fake_repo()
        try:
            with patch("alc_propose.report_agent_event", return_value="evt-30") as mock_fn:
                _run(TOOL_HANDLERS["report_agent_event"]({
                    "repo": str(repo),
                    "kind": "complete",
                }))
            _args, kwargs = mock_fn.call_args
            self.assertEqual(kwargs["actor_name"], "mcp_caller")
        finally:
            td.cleanup()

    def test_agent_role_alias_for_actor_name(self):
        td, repo = self._fake_repo()
        try:
            with patch("alc_propose.report_agent_event", return_value="evt-31") as mock_fn:
                _run(TOOL_HANDLERS["report_agent_event"]({
                    "repo": str(repo),
                    "kind": "complete",
                    "agent_role": "reviewer",
                }))
            _args, kwargs = mock_fn.call_args
            self.assertEqual(kwargs["actor_name"], "reviewer")
        finally:
            td.cleanup()

    def test_kind_normalised_via_agent_kind_helper(self):
        # Verify _agent_kind helper is used (whitebox: check via direct helper)
        self.assertEqual(_agent_kind({"kind": "AgentDispatchComplete"}), "complete")
        self.assertEqual(_agent_kind({"kind": "agent_dispatch_review"}), "review")
        self.assertEqual(_agent_kind({"event": "complete"}), "complete")
        self.assertEqual(_agent_kind({}), "complete")


if __name__ == "__main__":
    unittest.main()
