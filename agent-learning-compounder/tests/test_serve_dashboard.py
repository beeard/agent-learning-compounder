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
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

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

    def test_static_fallback_serves_repo_dashboard_without_uvicorn(self) -> None:
        observed: list[str] = []
        repo = self.repo

        class FakeServer:
            def __init__(self, server_address, handler_cls):  # noqa: ANN001
                self.server_address = server_address
                self.handler_cls = handler_cls
                self.closed = False

            def serve_forever(self) -> None:
                observed.append(dashboard_url(repo))
                raise KeyboardInterrupt

            def server_close(self) -> None:
                self.closed = True

        self.state.dashboard_dir.mkdir(parents=True, exist_ok=True)
        args = SERVE.parse_args(["--repo", str(self.repo), "--host", "127.0.0.1", "--port", "41037"])
        with (
            patch("render_state_surface.render_html", return_value=self.state.dashboard_dir),
            patch.object(SERVE.http.server, "ThreadingHTTPServer", FakeServer),
        ):
            result = SERVE.serve_static_fallback(args)

        self.assertEqual(result, 0)
        self.assertEqual(observed, ["http://127.0.0.1:41037/"])
        self.assertFalse((self.state.dashboard_dir / "server.json").exists())

    def test_main_falls_back_when_fastapi_dependency_is_missing(self) -> None:
        observed: list[str] = []
        repo = self.repo

        class FakeServer:
            def __init__(self, server_address, handler_cls):  # noqa: ANN001
                self.server_address = server_address
                self.handler_cls = handler_cls

            def serve_forever(self) -> None:
                observed.append(dashboard_url(repo))
                raise KeyboardInterrupt

            def server_close(self) -> None:
                pass

        fake_uvicorn = SimpleNamespace(run=lambda *args, **kwargs: None)
        fake_dashboard = SimpleNamespace(build_app=lambda **kwargs: (_ for _ in ()).throw(ImportError("fastapi required")))
        self.state.dashboard_dir.mkdir(parents=True, exist_ok=True)
        with (
            patch.dict(sys.modules, {"uvicorn": fake_uvicorn, "dashboard": fake_dashboard}),
            patch("render_state_surface.render_html", return_value=self.state.dashboard_dir),
            patch.object(SERVE.http.server, "ThreadingHTTPServer", FakeServer),
        ):
            result = SERVE.main(["--repo", str(self.repo), "--host", "127.0.0.1", "--port", "41038"])

        self.assertEqual(result, 0)
        self.assertEqual(observed, ["http://127.0.0.1:41038/"])

    def test_shared_run_distill_defaults_to_bin_auto_distill_session(self) -> None:
        import dashboard.actions as dashboard_actions

        commands: list[list[str]] = []

        class FakeProc:
            returncode = 0

            def communicate(self, *, timeout: int):  # noqa: ARG002
                return ("", "")

        class ImmediateThread:
            def __init__(self, *, target, daemon: bool) -> None:  # noqa: ANN001, ARG002
                self.target = target

            def start(self) -> None:
                self.target()

        def fake_popen(command, **kwargs):  # noqa: ANN001, ARG001
            commands.append(command)
            return FakeProc()

        with (
            patch.object(dashboard_actions.pathlib.Path, "is_file", return_value=True),
            patch.object(dashboard_actions.subprocess, "Popen", side_effect=fake_popen),
            patch.object(dashboard_actions.threading, "Thread", ImmediateThread),
        ):
            result = dashboard_actions.run_distill(self.state_root)

        self.assertEqual(result["status"], "running")
        self.assertEqual(commands, [[str(REPO_ROOT / "bin" / "auto_distill_session")]])

    def _fastapi_client(self, app):  # noqa: ANN001
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("fastapi test client unavailable")
        return TestClient(app)

    def _build_fastapi_app(self, dashboard_module):  # noqa: ANN001
        if not dashboard_module._FASTAPI_AVAILABLE:
            self.skipTest("fastapi unavailable")
        return dashboard_module.build_app(personal=self.state_root)

    def test_fastapi_distill_delegates_to_dashboard_actions(self) -> None:
        import dashboard
        import dashboard.actions as dashboard_actions

        result = {"job_id": "distill-123", "status": "running"}
        with patch.object(dashboard_actions, "run_distill", return_value=result) as run_distill:
            client = self._fastapi_client(self._build_fastapi_app(dashboard))
            response = client.post("/api/actions/distill")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), result)
        run_distill.assert_called_once()
        args, kwargs = run_distill.call_args
        self.assertEqual(args, (self.state_root.resolve(),))
        self.assertEqual(kwargs, {"script": dashboard.AUTO_DISTILL})

    def test_fastapi_missing_distill_script_returns_503(self) -> None:
        import dashboard
        import dashboard.actions as dashboard_actions

        with patch.object(
            dashboard_actions,
            "run_distill",
            return_value={"status": "missing", "job_id": None, "message": "auto_distill_session script missing"},
        ):
            client = self._fastapi_client(self._build_fastapi_app(dashboard))
            response = client.post("/api/actions/distill")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "auto_distill_session script missing")

    def test_fastapi_jobs_delegate_to_dashboard_actions(self) -> None:
        import dashboard
        import dashboard.actions as dashboard_actions

        jobs = {"jobs": [{"job_id": "distill-123", "status": "running"}]}
        job = {"job_id": "distill-123", "status": "running"}
        with (
            patch.object(dashboard_actions, "list_action_jobs", return_value=jobs) as list_action_jobs,
            patch.object(dashboard_actions, "get_action_job", return_value=job) as get_action_job,
        ):
            client = self._fastapi_client(self._build_fastapi_app(dashboard))
            list_response = client.get("/api/actions/jobs")
            get_response = client.get("/api/actions/jobs/distill-123")

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json(), jobs)
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.json(), job)
        list_action_jobs.assert_called_once_with()
        get_action_job.assert_called_once_with("distill-123")

    def test_fastapi_unknown_job_id_returns_404(self) -> None:
        import dashboard
        import dashboard.actions as dashboard_actions

        with patch.object(
            dashboard_actions,
            "get_action_job",
            return_value={"job_id": "missing", "status": "missing", "messages": ["unknown job"]},
        ):
            client = self._fastapi_client(self._build_fastapi_app(dashboard))
            response = client.get("/api/actions/jobs/missing")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "unknown job")


if __name__ == "__main__":
    unittest.main()
