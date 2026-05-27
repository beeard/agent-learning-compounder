from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVE_SRC = REPO_ROOT / "bin" / "serve_dashboard"

loader = SourceFileLoader("serve_dashboard_module", str(SERVE_SRC))
SERVE = loader.load_module()

if str(REPO_ROOT / "bin") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "bin"))

from dashboard_url_publisher import dashboard_url  # noqa: E402
from state_handle import StateHandle  # noqa: E402


class ServeDashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.repo = root / "repo"
        self.repo.mkdir()
        self.state_root = root / "state"
        (self.repo / ".agent-learning.json").write_text(json.dumps({"state_dir": str(self.state_root)}), encoding="utf-8")
        self.state = StateHandle.for_repo(self.repo)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run_with_fakes(self, argv: list[str], fake_run):
        fake_uvicorn = SimpleNamespace(run=fake_run)
        fake_dashboard = SimpleNamespace(build_app=lambda **kwargs: {"kwargs": kwargs})
        with patch.dict(sys.modules, {"uvicorn": fake_uvicorn, "dashboard": fake_dashboard}):
            return SERVE.main(argv)

    def test_loopback_repo_launch_publishes_marker_around_uvicorn(self) -> None:
        observed: list[str] = []

        def fake_run(app, *, host: str, port: int, log_level: str) -> None:  # noqa: ARG001
            observed.append(dashboard_url(self.repo))

        result = self._run_with_fakes(
            ["--repo", str(self.repo), "--host", "127.0.0.1", "--port", "41031"],
            fake_run,
        )

        self.assertIsNone(result)
        self.assertEqual(observed, ["http://127.0.0.1:41031/"])
        self.assertFalse((self.state.dashboard_dir / "server.json").exists())

    def test_no_repo_launch_does_not_write_project_marker(self) -> None:
        observed = []

        def fake_run(app, *, host: str, port: int, log_level: str) -> None:  # noqa: ARG001
            observed.append((self.state.dashboard_dir / "server.json").exists())

        result = self._run_with_fakes(["--host", "127.0.0.1", "--port", "41032"], fake_run)

        self.assertIsNone(result)
        self.assertEqual(observed, [False])

    def test_non_loopback_without_insecure_public_fails_before_publication(self) -> None:
        calls = []

        def fake_run(app, *, host: str, port: int, log_level: str) -> None:  # noqa: ARG001
            calls.append(host)

        result = self._run_with_fakes(
            ["--repo", str(self.repo), "--host", "0.0.0.0", "--port", "41033"],
            fake_run,
        )

        self.assertEqual(result, 2)
        self.assertEqual(calls, [])
        self.assertFalse((self.state.dashboard_dir / "server.json").exists())

    def test_insecure_public_launch_does_not_publish_non_loopback_url(self) -> None:
        observed = []

        def fake_run(app, *, host: str, port: int, log_level: str) -> None:  # noqa: ARG001
            observed.append((self.state.dashboard_dir / "server.json").exists())

        result = self._run_with_fakes(
            ["--repo", str(self.repo), "--host", "0.0.0.0", "--port", "41034", "--insecure-public"],
            fake_run,
        )

        self.assertIsNone(result)
        self.assertEqual(observed, [False])

    def test_shutdown_cleanup_keeps_replaced_marker(self) -> None:
        replacement_tokens: list[str | None] = []

        def fake_run(app, *, host: str, port: int, log_level: str) -> None:  # noqa: ARG001
            import dashboard_url_publisher

            replacement_tokens.append(
                dashboard_url_publisher.publish_live_url(
                    self.state,
                    host="127.0.0.1",
                    port=41036,
                    surface="fastapi",
                )
            )

        result = self._run_with_fakes(
            ["--repo", str(self.repo), "--host", "127.0.0.1", "--port", "41035"],
            fake_run,
        )

        self.assertIsNone(result)
        self.assertEqual(dashboard_url(self.repo), "http://127.0.0.1:41036/")
        import dashboard_url_publisher

        dashboard_url_publisher.clear_live_url(self.state, replacement_tokens[0])


if __name__ == "__main__":
    unittest.main()
