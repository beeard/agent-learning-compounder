from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from typing import Any

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

import analyst_run

render_loader = SourceFileLoader(
    "render_unified_report_for_analyst_run_tests",
    str(REPO_ROOT / "scripts" / "render_unified_report.py"),
)
RENDER = render_loader.load_module()


class _State:
    def __init__(self, root: pathlib.Path) -> None:
        self.repo_state_dir = root
        self.events_sqlite = root / "events.sqlite"
        self.outcomes_json = root / "outcomes.json"


class AnalystRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.state = _State(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_run_suite_executes_adapters_in_registry_order_and_writes_artifacts(self) -> None:
        calls: list[str] = []
        writes: list[tuple[str, dict[str, Any]]] = []

        adapters = (
            analyst_run.AnalystAdapter(
                name="patterns",
                artifact_id="patterns",
                run=lambda state, **kwargs: calls.append("patterns") or {"fallback_mode": False},
            ),
            analyst_run.AnalystAdapter(
                name="score",
                artifact_id="recommendations",
                run=lambda state, **kwargs: calls.append("score") or {"fallback_mode": False},
            ),
        )

        def fake_writer(artifact_id: str, payload: dict[str, Any], state: Any) -> pathlib.Path:
            writes.append((artifact_id, payload))
            return self.root / f"{artifact_id}.json"

        results = analyst_run.run_suite(self.state, adapters=adapters, write=fake_writer)

        self.assertEqual(calls, ["patterns", "score"])
        self.assertEqual([result.name for result in results], ["patterns", "score"])
        self.assertEqual([artifact_id for artifact_id, _ in writes], ["patterns", "recommendations"])

    def test_default_suite_preserves_missing_sqlite_fallback_payloads(self) -> None:
        results = analyst_run.run_suite(self.state, write=False)

        self.assertEqual(
            [result.name for result in results],
            ["patterns", "anomalies", "correlations", "score"],
        )
        for result in results:
            self.assertTrue(result.payload["fallback_mode"], result.name)
            self.assertIn("fallback_samples_count", result.payload)

    def test_known_fallback_error_is_local_to_one_adapter(self) -> None:
        adapters = (
            analyst_run.AnalystAdapter(
                name="broken",
                artifact_id="broken",
                run=lambda state, **kwargs: (_ for _ in ()).throw(FileNotFoundError("missing sqlite")),
                fallback=lambda state, error, **kwargs: {
                    "fallback_mode": True,
                    "fallback_samples_count": 0,
                    "error": str(error),
                },
            ),
            analyst_run.AnalystAdapter(
                name="healthy",
                artifact_id="healthy",
                run=lambda state, **kwargs: {"fallback_mode": False},
            ),
        )

        results = analyst_run.run_suite(self.state, adapters=adapters, write=False)

        self.assertEqual([result.name for result in results], ["broken", "healthy"])
        self.assertTrue(results[0].payload["fallback_mode"])
        self.assertFalse(results[1].payload["fallback_mode"])

    def test_unregistered_artifact_error_is_not_swallowed(self) -> None:
        adapter = analyst_run.AnalystAdapter(
            name="unknown",
            artifact_id="missing-artifact",
            run=lambda state, **kwargs: {"fallback_mode": False},
        )

        with self.assertRaises(KeyError):
            analyst_run.run_suite(self.state, adapters=(adapter,))

    def test_unified_report_pipeline_delegates_analyst_suite_to_analyst_run(self) -> None:
        self.state.reports_dir = self.root / "reports"
        corpus = self.root / "corpus.txt"
        baseline = self.root / "baseline.json"

        commands = RENDER._pipeline_commands(self.state, corpus, baseline, "combined")
        analyst_commands = [
            command for command in commands if any("analyst_" in pathlib.Path(part).name for part in command)
        ]

        self.assertEqual(len(analyst_commands), 1)
        self.assertEqual(pathlib.Path(analyst_commands[0][1]).name, "analyst_run.py")


if __name__ == "__main__":
    unittest.main()
