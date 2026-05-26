"""Unit tests for alc_next_action.next_action synthesiser.

Covers:
  - Each intent (start, next, end, recap, leftoff, auto)
  - Priority ladder (pending_patches > rejects > stale recs > recent applies > idle)
  - Output schema validity (all required keys, correct types)
  - Signals block is bucketed (ints/str/None — never lists or dicts-of-rows)
  - Side-effect: JSON file written to the correct path, parseable, schema-conformant
  - Idempotency: calling twice with the same state produces identical JSON on disk
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"
for _p in (str(BIN), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import alc_next_action as mod
from state_handle import StateHandle


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state(tmp_dir: Path) -> StateHandle:
    """Return a minimal StateHandle whose reports_dir lives under tmp_dir."""
    repo = tmp_dir / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    return StateHandle.for_repo(repo)


def _empty_signals():
    return {
        "pending_patches": 0,
        "_first_patch_id": None,
        "pending_recommendations": 0,
        "recent_applies_7d": 0,
        "recent_verdicts_7d": {"approve": 0, "reject": 0, "modify": 0},
        "last_activity_iso": None,
    }


def _call_with_signals(tmp_dir: Path, signals: dict, intent: str = "auto") -> dict:
    """Call next_action with patched signal collection."""
    state = _make_state(tmp_dir)
    with patch.object(mod, "_collect_signals", return_value=signals):
        return mod.next_action(state, intent=intent)


# ---------------------------------------------------------------------------
# Schema validation helper
# ---------------------------------------------------------------------------

_REQUIRED_TOP = {"intent", "headline", "rationale", "suggested", "alternatives", "signals"}
_REQUIRED_SUGGESTED = {"skill", "args", "prompt"}
_REQUIRED_SIGNALS = {
    "pending_patches", "pending_recommendations", "recent_applies_7d",
    "recent_verdicts_7d", "last_activity_iso",
}
_VALID_INTENTS = {"start", "next", "end", "recap", "leftoff", "auto"}


def _assert_schema(tc: unittest.TestCase, result: dict, label: str = "") -> None:
    prefix = f"{label}: " if label else ""
    tc.assertIsInstance(result, dict, f"{prefix}result must be a dict")

    for key in _REQUIRED_TOP:
        tc.assertIn(key, result, f"{prefix}missing key {key!r}")

    tc.assertIn(result["intent"], _VALID_INTENTS, f"{prefix}invalid intent {result['intent']!r}")
    tc.assertIsInstance(result["headline"], str, f"{prefix}headline must be str")
    tc.assertTrue(result["headline"], f"{prefix}headline must be non-empty")
    tc.assertIsInstance(result["rationale"], str, f"{prefix}rationale must be str")
    tc.assertTrue(result["rationale"], f"{prefix}rationale must be non-empty")

    suggested = result["suggested"]
    tc.assertIsInstance(suggested, dict, f"{prefix}suggested must be a dict")
    for k in _REQUIRED_SUGGESTED:
        tc.assertIn(k, suggested, f"{prefix}suggested missing key {k!r}")
    tc.assertIsInstance(suggested["prompt"], str, f"{prefix}suggested.prompt must be str")

    alts = result["alternatives"]
    tc.assertIsInstance(alts, list, f"{prefix}alternatives must be a list")
    tc.assertLessEqual(len(alts), 3, f"{prefix}alternatives must have at most 3 entries")
    for i, alt in enumerate(alts):
        tc.assertIsInstance(alt, dict, f"{prefix}alternative[{i}] must be dict")
        tc.assertIn("skill", alt, f"{prefix}alternative[{i}] missing 'skill'")
        tc.assertIn("rationale", alt, f"{prefix}alternative[{i}] missing 'rationale'")

    signals = result["signals"]
    tc.assertIsInstance(signals, dict, f"{prefix}signals must be a dict")
    for k in _REQUIRED_SIGNALS:
        tc.assertIn(k, signals, f"{prefix}signals missing key {k!r}")
    tc.assertIsInstance(signals["pending_patches"], int, f"{prefix}signals.pending_patches must be int")
    tc.assertIsInstance(signals["pending_recommendations"], int, f"{prefix}signals.pending_recommendations must be int")
    tc.assertIsInstance(signals["recent_applies_7d"], int, f"{prefix}signals.recent_applies_7d must be int")
    tc.assertIsInstance(signals["recent_verdicts_7d"], dict, f"{prefix}signals.recent_verdicts_7d must be dict")
    # last_activity_iso: str or None — never a list/dict
    lai = signals["last_activity_iso"]
    tc.assertIn(type(lai), (str, type(None)), f"{prefix}last_activity_iso must be str or None")

    verdicts = signals["recent_verdicts_7d"]
    for vk in ("approve", "reject", "modify"):
        tc.assertIn(vk, verdicts, f"{prefix}verdicts missing key {vk!r}")
        tc.assertIsInstance(verdicts[vk], int, f"{prefix}verdicts[{vk!r}] must be int")


# ---------------------------------------------------------------------------
# Intent dispatch tests
# ---------------------------------------------------------------------------

class TestIntentNormalisation(unittest.TestCase):

    def test_start_intent(self):
        self.assertEqual(mod._normalise_intent("start"), "start")

    def test_next_intent(self):
        self.assertEqual(mod._normalise_intent("next"), "next")

    def test_end_intent(self):
        self.assertEqual(mod._normalise_intent("end"), "end")

    def test_recap_intent(self):
        self.assertEqual(mod._normalise_intent("recap"), "recap")

    def test_leftoff_intent(self):
        self.assertEqual(mod._normalise_intent("leftoff"), "leftoff")

    def test_auto_intent(self):
        self.assertEqual(mod._normalise_intent("auto"), "auto")

    def test_aliases(self):
        self.assertEqual(mod._normalise_intent("begin"), "start")
        self.assertEqual(mod._normalise_intent("continue"), "next")
        self.assertEqual(mod._normalise_intent("finish"), "end")
        self.assertEqual(mod._normalise_intent("summary"), "recap")
        self.assertEqual(mod._normalise_intent("left-off"), "leftoff")

    def test_unknown_falls_back_to_auto(self):
        self.assertEqual(mod._normalise_intent("giberrish"), "auto")

    def test_none_falls_back_to_auto(self):
        self.assertEqual(mod._normalise_intent(None), "auto")

    def test_case_insensitive(self):
        self.assertEqual(mod._normalise_intent("START"), "start")
        self.assertEqual(mod._normalise_intent("End"), "end")


class TestEachIntentProducesSchemaConformantOutput(unittest.TestCase):
    """Each intent must return a result matching the schema."""

    def _run(self, intent: str, signals: dict | None = None) -> dict:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        return _call_with_signals(Path(td.name), signals or _empty_signals(), intent=intent)

    def test_start_schema(self):
        result = self._run("start")
        _assert_schema(self, result, "start")
        self.assertEqual(result["intent"], "start")

    def test_next_schema(self):
        result = self._run("next")
        _assert_schema(self, result, "next")
        self.assertEqual(result["intent"], "next")

    def test_end_schema(self):
        result = self._run("end")
        _assert_schema(self, result, "end")
        self.assertEqual(result["intent"], "end")

    def test_recap_schema(self):
        result = self._run("recap")
        _assert_schema(self, result, "recap")
        self.assertEqual(result["intent"], "recap")

    def test_leftoff_schema(self):
        result = self._run("leftoff")
        _assert_schema(self, result, "leftoff")
        self.assertEqual(result["intent"], "leftoff")

    def test_auto_schema(self):
        result = self._run("auto")
        _assert_schema(self, result, "auto")
        self.assertEqual(result["intent"], "auto")


# ---------------------------------------------------------------------------
# Priority ladder tests
# ---------------------------------------------------------------------------

class TestPriorityLadder(unittest.TestCase):

    def _td(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        return Path(td.name)

    # Rung 1: pending patches → suggest ce-doc-review
    def test_rung1_pending_patches_suggests_doc_review(self):
        signals = _empty_signals()
        signals["pending_patches"] = 2
        signals["_first_patch_id"] = "patch-abc"
        result = _call_with_signals(self._td(), signals, intent="start")
        _assert_schema(self, result, "rung1")
        self.assertEqual(result["suggested"]["skill"], "ce-doc-review")
        self.assertEqual(result["suggested"]["args"], "patch-abc")

    def test_rung1_single_patch_noun_singular(self):
        signals = _empty_signals()
        signals["pending_patches"] = 1
        signals["_first_patch_id"] = "patch-001"
        result = _call_with_signals(self._td(), signals, intent="next")
        self.assertIn("1 pending patch", result["headline"])

    def test_rung1_multiple_patches_noun_plural(self):
        signals = _empty_signals()
        signals["pending_patches"] = 3
        signals["_first_patch_id"] = "patch-xyz"
        result = _call_with_signals(self._td(), signals, intent="auto")
        self.assertIn("3 pending patches", result["headline"])

    # Rung 2: rejected verdicts (no pending patches)
    def test_rung2_recent_rejects_no_patches(self):
        signals = _empty_signals()
        signals["recent_verdicts_7d"]["reject"] = 2
        result = _call_with_signals(self._td(), signals, intent="start")
        _assert_schema(self, result, "rung2")
        self.assertIn("2", result["headline"])
        self.assertIn("reject", result["headline"].lower())

    def test_rung2_single_rejection_noun_singular(self):
        signals = _empty_signals()
        signals["recent_verdicts_7d"]["reject"] = 1
        result = _call_with_signals(self._td(), signals, intent="start")
        self.assertIn("rejection", result["headline"].lower())

    # Rung 3: stale recommendations (≥4)
    def test_rung3_stale_recommendations(self):
        signals = _empty_signals()
        signals["pending_recommendations"] = 5
        result = _call_with_signals(self._td(), signals, intent="start")
        _assert_schema(self, result, "rung3")
        self.assertEqual(result["suggested"]["skill"], "alc-report")
        self.assertIn("5", result["headline"])

    def test_rung3_threshold_is_4(self):
        """3 recommendations should NOT trigger rung3."""
        signals = _empty_signals()
        signals["pending_recommendations"] = 3
        result = _call_with_signals(self._td(), signals, intent="start")
        # Should fall through to rung4 (recent_applies=0) then rung5 (idle)
        self.assertEqual(result["suggested"]["skill"], "ce-brainstorm")

    # Rung 4: recent applies without plan
    def test_rung4_recent_applies_no_rejects(self):
        signals = _empty_signals()
        signals["recent_applies_7d"] = 3
        result = _call_with_signals(self._td(), signals, intent="start")
        _assert_schema(self, result, "rung4")
        self.assertEqual(result["suggested"]["skill"], "ce-plan")

    # Rung 5: idle state
    def test_rung5_idle_suggests_brainstorm(self):
        result = _call_with_signals(self._td(), _empty_signals(), intent="start")
        _assert_schema(self, result, "rung5")
        self.assertEqual(result["suggested"]["skill"], "ce-brainstorm")
        # Alternatives may be empty or short for idle state
        self.assertLessEqual(len(result["alternatives"]), 3)

    def test_rung5_quiet_rationale_acknowledges_state(self):
        result = _call_with_signals(self._td(), _empty_signals(), intent="start")
        # Rationale should acknowledge the quiet state
        self.assertIn("no pending", result["rationale"].lower())

    # Priority ordering: rung1 > rung2
    def test_rung1_wins_over_rung2(self):
        signals = _empty_signals()
        signals["pending_patches"] = 1
        signals["_first_patch_id"] = "p-1"
        signals["recent_verdicts_7d"]["reject"] = 5
        result = _call_with_signals(self._td(), signals, intent="start")
        self.assertEqual(result["suggested"]["skill"], "ce-doc-review")

    # Priority ordering: rung2 > rung3
    def test_rung2_wins_over_rung3(self):
        signals = _empty_signals()
        signals["recent_verdicts_7d"]["reject"] = 3
        signals["pending_recommendations"] = 10
        result = _call_with_signals(self._td(), signals, intent="start")
        self.assertIn("reject", result["headline"].lower())

    # Priority ordering: rung3 > rung4
    def test_rung3_wins_over_rung4(self):
        signals = _empty_signals()
        signals["pending_recommendations"] = 4
        signals["recent_applies_7d"] = 5
        result = _call_with_signals(self._td(), signals, intent="start")
        self.assertEqual(result["suggested"]["skill"], "alc-report")


# ---------------------------------------------------------------------------
# Signals block tests — must never be raw rows
# ---------------------------------------------------------------------------

class TestSignalsBlockTypes(unittest.TestCase):

    def _td(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        return Path(td.name)

    def _result_with_real_collect(self, intent: str = "auto") -> dict:
        """Call with real _collect_signals (mocking alc_query returns)."""
        state = _make_state(self._td())
        with (
            patch("alc_query.get_pending_patches", return_value=[]),
            patch("alc_query.get_recommendations", return_value=[]),
            patch("alc_query.get_apply_log", return_value=[]),
            patch("alc_query.get_outcomes", return_value=[]),
        ):
            return mod.next_action(state, intent=intent)

    def test_signals_pending_patches_is_int(self):
        result = self._result_with_real_collect()
        self.assertIsInstance(result["signals"]["pending_patches"], int)

    def test_signals_pending_recommendations_is_int(self):
        result = self._result_with_real_collect()
        self.assertIsInstance(result["signals"]["pending_recommendations"], int)

    def test_signals_recent_applies_7d_is_int(self):
        result = self._result_with_real_collect()
        self.assertIsInstance(result["signals"]["recent_applies_7d"], int)

    def test_signals_verdicts_values_are_ints(self):
        result = self._result_with_real_collect()
        verdicts = result["signals"]["recent_verdicts_7d"]
        for k, v in verdicts.items():
            self.assertIsInstance(v, int, f"verdicts[{k!r}] must be int, got {type(v)}")

    def test_signals_last_activity_iso_is_str_or_none(self):
        result = self._result_with_real_collect()
        lai = result["signals"]["last_activity_iso"]
        self.assertIn(type(lai), (str, type(None)))

    def test_signals_never_contains_lists_of_dicts(self):
        """Signals must be flat counts — no raw rows."""
        result = self._result_with_real_collect()
        for k, v in result["signals"].items():
            self.assertNotIsInstance(v, list, f"signals[{k!r}] must not be a list (raw rows forbidden)")

    def test_pending_patches_count_reflects_query_result(self):
        state = _make_state(self._td())
        patches = [
            {"patch_id": "p-1", "status": "pending", "ts": "2026-05-20T10:00:00Z"},
            {"patch_id": "p-2", "status": "pending", "ts": "2026-05-21T10:00:00Z"},
        ]
        with (
            patch("alc_query.get_pending_patches", return_value=patches),
            patch("alc_query.get_recommendations", return_value=[]),
            patch("alc_query.get_apply_log", return_value=[]),
            patch("alc_query.get_outcomes", return_value=[]),
        ):
            result = mod.next_action(state, intent="auto")
        self.assertEqual(result["signals"]["pending_patches"], 2)


# ---------------------------------------------------------------------------
# Side-effect / cache file tests
# ---------------------------------------------------------------------------

class TestCacheFile(unittest.TestCase):

    def _td(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        return Path(td.name)

    def _run_and_get_cache(self, td: Path, intent: str = "auto", signals: dict | None = None) -> dict:
        state = _make_state(td)
        sigs = signals or _empty_signals()
        with patch.object(mod, "_collect_signals", return_value=sigs):
            result = mod.next_action(state, intent=intent)
        cache_path = state.reports_dir / "latest-next-action.json"
        return result, cache_path

    def test_cache_file_is_written(self):
        td = self._td()
        result, cache_path = self._run_and_get_cache(td)
        self.assertTrue(cache_path.exists(), "cache file must be written")

    def test_cache_file_is_parseable_json(self):
        td = self._td()
        _result, cache_path = self._run_and_get_cache(td)
        parsed = json.loads(cache_path.read_text(encoding="utf-8"))
        self.assertIsInstance(parsed, dict)

    def test_cache_file_schema_conformant(self):
        td = self._td()
        _result, cache_path = self._run_and_get_cache(td)
        parsed = json.loads(cache_path.read_text(encoding="utf-8"))
        _assert_schema(self, parsed, "cache_file")

    def test_cache_file_matches_returned_result(self):
        td = self._td()
        result, cache_path = self._run_and_get_cache(td)
        parsed = json.loads(cache_path.read_text(encoding="utf-8"))
        # Both should be equivalent (modulo sort_keys serialisation)
        self.assertEqual(
            json.loads(json.dumps(result, sort_keys=True)),
            json.loads(json.dumps(parsed, sort_keys=True)),
        )

    def test_cache_file_is_under_reports_dir(self):
        td = self._td()
        state = _make_state(td)
        expected_path = state.reports_dir / "latest-next-action.json"
        with patch.object(mod, "_collect_signals", return_value=_empty_signals()):
            mod.next_action(state, intent="auto")
        self.assertTrue(expected_path.exists())

    def test_idempotent_identical_json(self):
        """Calling twice with same signals produces byte-identical cache content."""
        td = self._td()
        state = _make_state(td)
        signals = _empty_signals()
        signals["pending_patches"] = 1
        signals["_first_patch_id"] = "p-idempotent"

        with patch.object(mod, "_collect_signals", return_value=signals):
            mod.next_action(state, intent="start")
        cache_path = state.reports_dir / "latest-next-action.json"
        first_content = cache_path.read_bytes()

        with patch.object(mod, "_collect_signals", return_value=signals):
            mod.next_action(state, intent="start")
        second_content = cache_path.read_bytes()

        self.assertEqual(first_content, second_content, "cache file must be byte-identical on repeated identical calls")

    def test_cache_overwritten_on_subsequent_calls(self):
        """A second call with different signals updates the cache."""
        td = self._td()
        state = _make_state(td)
        cache_path = state.reports_dir / "latest-next-action.json"

        signals_a = _empty_signals()
        signals_a["pending_patches"] = 0

        signals_b = _empty_signals()
        signals_b["pending_patches"] = 3
        signals_b["_first_patch_id"] = "p-new"

        with patch.object(mod, "_collect_signals", return_value=signals_a):
            mod.next_action(state, intent="start")
        content_a = cache_path.read_text(encoding="utf-8")

        with patch.object(mod, "_collect_signals", return_value=signals_b):
            mod.next_action(state, intent="start")
        content_b = cache_path.read_text(encoding="utf-8")

        self.assertNotEqual(content_a, content_b)
        parsed_b = json.loads(content_b)
        self.assertEqual(parsed_b["signals"]["pending_patches"], 3)


# ---------------------------------------------------------------------------
# End intent
# ---------------------------------------------------------------------------

class TestEndIntent(unittest.TestCase):

    def _td(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        return Path(td.name)

    def test_end_with_applies_suggests_commit(self):
        signals = _empty_signals()
        signals["recent_applies_7d"] = 2
        result = _call_with_signals(self._td(), signals, intent="end")
        _assert_schema(self, result, "end/applies")
        self.assertIn("commit", result["suggested"]["skill"].lower())

    def test_end_with_pending_no_applies_suggests_session_report(self):
        signals = _empty_signals()
        signals["pending_patches"] = 1
        result = _call_with_signals(self._td(), signals, intent="end")
        _assert_schema(self, result, "end/pending")
        self.assertEqual(result["suggested"]["skill"], "session-report")

    def test_end_quiet_state_suggests_session_report(self):
        result = _call_with_signals(self._td(), _empty_signals(), intent="end")
        _assert_schema(self, result, "end/quiet")
        self.assertEqual(result["suggested"]["skill"], "session-report")


# ---------------------------------------------------------------------------
# Recap intent
# ---------------------------------------------------------------------------

class TestRecapIntent(unittest.TestCase):

    def _td(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        return Path(td.name)

    def test_recap_no_activity(self):
        result = _call_with_signals(self._td(), _empty_signals(), intent="recap")
        _assert_schema(self, result, "recap/idle")
        self.assertIn("no activity", result["headline"].lower())

    def test_recap_with_applies_and_verdicts(self):
        signals = _empty_signals()
        signals["recent_applies_7d"] = 3
        signals["recent_verdicts_7d"]["approve"] = 2
        signals["recent_verdicts_7d"]["reject"] = 1
        signals["last_activity_iso"] = "2026-05-25T14:00:00+00:00"
        result = _call_with_signals(self._td(), signals, intent="recap")
        _assert_schema(self, result, "recap/active")
        self.assertIn("3", result["headline"])

    def test_recap_suggests_alc_report(self):
        signals = _empty_signals()
        signals["recent_applies_7d"] = 1
        result = _call_with_signals(self._td(), signals, intent="recap")
        self.assertEqual(result["suggested"]["skill"], "alc-report")


# ---------------------------------------------------------------------------
# Leftoff intent
# ---------------------------------------------------------------------------

class TestLeftoffIntent(unittest.TestCase):

    def _td(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        return Path(td.name)

    def test_leftoff_no_activity_suggests_init(self):
        result = _call_with_signals(self._td(), _empty_signals(), intent="leftoff")
        _assert_schema(self, result, "leftoff/empty")
        # Should suggest initialisation or brainstorm
        self.assertIsNotNone(result["suggested"]["skill"])

    def test_leftoff_with_pending_patch(self):
        signals = _empty_signals()
        signals["pending_patches"] = 2
        signals["_first_patch_id"] = "patch-left"
        signals["recent_applies_7d"] = 1
        result = _call_with_signals(self._td(), signals, intent="leftoff")
        _assert_schema(self, result, "leftoff/pending")
        self.assertEqual(result["suggested"]["skill"], "ce-doc-review")
        self.assertEqual(result["suggested"]["args"], "patch-left")


# ---------------------------------------------------------------------------
# Auto intent
# ---------------------------------------------------------------------------

class TestAutoIntent(unittest.TestCase):

    def _td(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        return Path(td.name)

    def test_auto_with_pending_patches_resolves_start_like(self):
        signals = _empty_signals()
        signals["pending_patches"] = 1
        signals["_first_patch_id"] = "p-auto"
        result = _call_with_signals(self._td(), signals, intent="auto")
        _assert_schema(self, result, "auto/patches")
        self.assertEqual(result["suggested"]["skill"], "ce-doc-review")

    def test_auto_idle_resolves_brainstorm(self):
        result = _call_with_signals(self._td(), _empty_signals(), intent="auto")
        _assert_schema(self, result, "auto/idle")
        self.assertEqual(result["suggested"]["skill"], "ce-brainstorm")

    def test_auto_with_recent_applies_resolves_start_like(self):
        signals = _empty_signals()
        signals["recent_applies_7d"] = 2
        result = _call_with_signals(self._td(), signals, intent="auto")
        _assert_schema(self, result, "auto/applies")
        # rung4 → suggest ce-plan
        self.assertEqual(result["suggested"]["skill"], "ce-plan")


# ---------------------------------------------------------------------------
# MCP / catalog integration (light)
# ---------------------------------------------------------------------------

class TestMCPCatalogEntry(unittest.TestCase):

    def test_next_action_in_catalog(self):
        from alc_mcp.catalog import MCP_TOOLS
        self.assertIn("next_action", MCP_TOOLS)

    def test_next_action_catalog_id(self):
        from alc_mcp.catalog import MCP_TOOLS
        self.assertEqual(MCP_TOOLS["next_action"].id, "M11")

    def test_next_action_backing_module(self):
        from alc_mcp.catalog import MCP_TOOLS
        self.assertEqual(MCP_TOOLS["next_action"].backing, "alc_next_action.next_action")


if __name__ == "__main__":
    unittest.main()
