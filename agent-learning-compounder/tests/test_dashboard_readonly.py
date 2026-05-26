from __future__ import annotations

import json
import pathlib
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from importlib.machinery import SourceFileLoader
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVER_SRC = REPO_ROOT / "skills" / "alc-dashboard" / "server.py"
RENDER_SRC = REPO_ROOT / "scripts" / "render_unified_report.py"

server_loader = SourceFileLoader("alc_dashboard_server", str(SERVER_SRC))
SERVER = server_loader.load_module()

render_loader = SourceFileLoader("render_unified_report", str(RENDER_SRC))
RENDER = render_loader.load_module()

if str(REPO_ROOT / "bin") not in __import__("sys").path:
    __import__("sys").path.insert(0, str(REPO_ROOT / "bin"))

from state_handle import StateHandle


def _start_server(repo: pathlib.Path, state: pathlib.Path | None, port: int = 0):
    try:
        httpd, selected = SERVER.create_server(repo=repo, state=state, host="127.0.0.1", port=port)
    except OSError as exc:
        raise unittest.SkipTest(f"network unavailable: {exc}") from exc
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, selected, thread


def _http_get(url: str, method: str = "GET"):
    req = urllib.request.Request(url, method=method)
    try:
        return urllib.request.urlopen(req, timeout=5)
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        msg = str(reason)
        # Skip in sandboxes that block loopback HTTP (codex-style sandboxes; some CI envs).
        if isinstance(reason, ConnectionRefusedError) or "Connection refused" in msg or "Network is unreachable" in msg:
            raise unittest.SkipTest(f"loopback HTTP unavailable: {msg}") from exc
        raise


def _server_url(port: int, path: str) -> str:
    return f"http://127.0.0.1:{port}{path}"


class DashboardReadonlyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self.temp.name) / "repo"
        self.repo.mkdir()
        self.state = StateHandle.for_repo(self.repo)
        self.state.repo_state_dir.mkdir(parents=True, exist_ok=True)
        self.state.reports_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_post_routes_return_405(self) -> None:
        httpd, port, thread = _start_server(self.repo, self.state.repo_state_dir)
        try:
            with self.assertRaises(urllib.error.HTTPError) as captured:
                with _http_get(_server_url(port, "/"), method="POST"):
                    pass
            self.assertEqual(captured.exception.code, 405)
        finally:
            httpd.shutdown()
            thread.join(timeout=2)
            httpd.server_close()

    def test_get_root_contains_sections_and_payload_markers(self) -> None:
        (self.state.reports_dir / "recommendations.json").write_text("[]", encoding="utf-8")
        patches = self.state.repo_state_dir / "patches"
        patches.mkdir(parents=True, exist_ok=True)
        (patches / "p-quick-fix.json").write_text(
            json.dumps({"patch_id": "p-quick-fix", "title": "Small drift fix"}, sort_keys=True),
            encoding="utf-8",
        )

        httpd, port, thread = _start_server(self.repo, self.state.repo_state_dir)
        try:
            with _http_get(_server_url(port, "/")) as response:
                body = response.read().decode("utf-8")
            self.assertEqual(response.status, 200)
            self.assertIn("Recommendations", body)
            self.assertIn("Pending patches", body)
            self.assertIn("Anomalies", body)
            self.assertIn("Patterns", body)
            self.assertIn("Correlations", body)
            self.assertIn("Apply log", body)
            self.assertIn("Gates & insights", body)
            self.assertIn("Suggestions", body)
            self.assertIn('meta name="viewport"', body)
            self.assertIn('role="tablist"', body)
            self.assertIn('role="tab"', body)
            self.assertIn("bin/alc_apply --patch p-quick-fix --write", body)
            self.assertIn("bin/alc_apply --mark-deferred p-quick-fix", body)
            self.assertIn("bin/alc_apply --mark-rejected p-quick-fix", body)
        finally:
            httpd.shutdown()
            thread.join(timeout=2)
            httpd.server_close()

    def test_get_data_json_returns_section_keys(self) -> None:
        httpd, port, thread = _start_server(self.repo, self.state.repo_state_dir)
        try:
            with _http_get(_server_url(port, "/data.json")) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status, 200)
            for key in (
                "recommendations",
                "pending_patches",
                "anomalies",
                "patterns",
                "correlations",
                "apply_log",
                "gates_and_insights",
                "suggestions",
                "sections",
            ):
                self.assertIn(key, payload)
            self.assertEqual(payload["recommendations"], [])
            self.assertEqual(payload["pending_patches"], [])
        finally:
            httpd.shutdown()
            thread.join(timeout=2)
            httpd.server_close()

    def test_static_assets_served_and_local(self) -> None:
        httpd, port, thread = _start_server(self.repo, self.state.repo_state_dir)
        try:
            with _http_get(_server_url(port, "/static/app.js")) as response:
                appjs = response.read().decode("utf-8")
                self.assertEqual(response.status, 200)
            with _http_get(_server_url(port, "/static/alpine.min.js")) as response:
                alpine = response.read().decode("utf-8")
                self.assertEqual(response.status, 200)
            self.assertIn("function renderDashboard", appjs)
            self.assertIn("window.Alpine", alpine)
        finally:
            httpd.shutdown()
            thread.join(timeout=2)
            httpd.server_close()

        with self.assertRaises(urllib.error.HTTPError):
            _http_get(_server_url(port, "/static/missing.js"))

    def test_free_port_allocation_when_8765_occupied(self) -> None:
        fake_httpd = SimpleNamespace(server_close=lambda: None, serve_forever=lambda: None)

        def fake_build_server(handler_class, host, requested_port, state):  # noqa: ARG001
            if requested_port == 8765:
                raise OSError(98, "Address already in use")
            return fake_httpd, 41000

        with patch.object(SERVER, "_build_server", side_effect=fake_build_server):
            httpd, port, thread = _start_server(self.repo, self.state.repo_state_dir, port=8765)
            try:
                self.assertNotEqual(port, 8765)
            finally:
                httpd.shutdown()
                thread.join(timeout=2)
                httpd.server_close()

    def test_render_unified_report_launches_http_url(self) -> None:
        baseline = self.state.repo_state_dir / "seed" / "baseline.json"
        baseline.parent.mkdir(parents=True, exist_ok=True)
        baseline.write_text("{}", encoding="utf-8")

        fake_httpd = SimpleNamespace(server_close=lambda: None, serve_forever=lambda: None)

        opened_urls: list[str] = []
        def fake_open(url: str, new: int = 0):
            opened_urls.append(url)
            return True

        def fake_create_server(**kwargs):
            return fake_httpd, 41020

        with patch.object(RENDER, "_run_command", return_value=subprocess.CompletedProcess(args=[], returncode=0)):
            with patch.object(RENDER, "_load_dashboard_server", return_value=SimpleNamespace(create_server=fake_create_server)):
                with patch.object(RENDER, "webbrowser", SimpleNamespace(open=fake_open)):
                    with tempfile.TemporaryDirectory() as td:
                        corpus = pathlib.Path(td) / "corpus"
                        corpus.mkdir()
                        (corpus / "hook-events.jsonl").write_text("[]", encoding="utf-8")
                        code = RENDER.run_unified_report(
                            repo=self.repo,
                            state=self.state.repo_state_dir,
                            baseline=baseline,
                            corpus=corpus,
                            serve=False,
                        )

        self.assertEqual(code, 0)
        self.assertEqual(len(opened_urls), 1)
        self.assertTrue(opened_urls[0].startswith("http://127.0.0.1:"))
        self.assertNotIn("file://", opened_urls[0])


if __name__ == "__main__":
    unittest.main()
