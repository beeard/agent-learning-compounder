from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

from dashboard_url_publisher import (  # noqa: E402
    DASHBOARD_HTML,
    LEGACY_INDEX_HTML,
    SERVER_MARKER,
    clear_live_url,
    dashboard_url,
    dashboard_url_status,
    marker_path,
    publish_live_url,
)
from state_handle import StateHandle  # noqa: E402


class DashboardUrlPublisherTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_env = {
            "AGENT_LEARNING_STATE_DIR": os.environ.pop("AGENT_LEARNING_STATE_DIR", None),
            "AGENT_LEARNING_USER": os.environ.pop("AGENT_LEARNING_USER", None),
            "AGENT_LEARNING_PERSONAL": os.environ.pop("AGENT_LEARNING_PERSONAL", None),
            "XDG_STATE_HOME": os.environ.pop("XDG_STATE_HOME", None),
        }
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.repo = root / "repo"
        self.repo.mkdir()
        self.state_root = root / "state"
        (self.repo / ".agent-learning.json").write_text(json.dumps({"state_dir": str(self.state_root)}), encoding="utf-8")
        self.state = StateHandle.for_repo(self.repo)
        self.state.dashboard_dir.mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _write_marker(self, payload: object) -> None:
        (self.state.dashboard_dir / SERVER_MARKER).write_text(json.dumps(payload), encoding="utf-8")

    def test_valid_loopback_marker_is_preferred(self) -> None:
        self._write_marker({"url": "http://127.0.0.1:8765/"})

        self.assertEqual(dashboard_url(self.repo), "http://127.0.0.1:8765/")

    def test_loopback_marker_accepts_localhost_and_ipv6(self) -> None:
        for payload, expected in (
            ({"url": "http://localhost:8765/", "host": "LOCALHOST", "port": 8765}, "http://localhost:8765/"),
            ({"url": "http://[::1]:8766/", "host": "::1", "port": 8766}, "http://[::1]:8766/"),
        ):
            with self.subTest(payload=payload):
                self._write_marker(payload)
                self.assertEqual(dashboard_url(self.repo), expected)

    def test_invalid_markers_fall_back_safely(self) -> None:
        (self.state.dashboard_dir / DASHBOARD_HTML).write_text("<html></html>", encoding="utf-8")
        expected = (self.state.dashboard_dir / DASHBOARD_HTML).resolve().as_uri()

        for payload in (
            {"url": "http://0.0.0.0:8765/"},
            {"url": "https://127.0.0.1:8765/"},
            {"url": "not a url"},
            {"url": ""},
            {"url": "http://127.0.0.1:not-a-port/"},
            {},
        ):
            with self.subTest(payload=payload):
                self._write_marker(payload)
                self.assertEqual(dashboard_url(self.repo), expected)

        (self.state.dashboard_dir / SERVER_MARKER).write_text("{", encoding="utf-8")
        self.assertEqual(dashboard_url(self.repo), expected)

    def test_static_fallback_prefers_dashboard_html_then_legacy_index_then_directory(self) -> None:
        self.assertEqual(dashboard_url(self.repo), self.state.dashboard_dir.resolve().as_uri())

        legacy = self.state.dashboard_dir / LEGACY_INDEX_HTML
        legacy.write_text("<html>legacy</html>", encoding="utf-8")
        self.assertEqual(dashboard_url(self.repo), legacy.resolve().as_uri())

        generated = self.state.dashboard_dir / DASHBOARD_HTML
        generated.write_text("<html>generated</html>", encoding="utf-8")
        self.assertEqual(dashboard_url(self.repo), generated.resolve().as_uri())

    def test_publish_writes_loopback_marker_and_clear_only_matching_token(self) -> None:
        first = publish_live_url(self.state, host="127.0.0.1", port=8765, surface="stdlib")
        self.assertIsNotNone(first)
        self.assertEqual(dashboard_url(self.repo), "http://127.0.0.1:8765/")

        second = publish_live_url(self.state, host="127.0.0.1", port=8766, surface="stdlib")
        self.assertIsNotNone(second)
        self.assertFalse(clear_live_url(self.state, first))
        self.assertTrue(marker_path(self.state).exists())
        self.assertEqual(dashboard_url(self.repo), "http://127.0.0.1:8766/")

        self.assertTrue(clear_live_url(self.state, second))
        self.assertFalse(marker_path(self.state).exists())

    def test_publish_refuses_non_loopback_marker(self) -> None:
        token = publish_live_url(self.state, host="0.0.0.0", port=8765, surface="fastapi")

        self.assertIsNone(token)
        self.assertFalse(marker_path(self.state).exists())

    def test_stale_live_marker_falls_back_with_unhealthy_status(self) -> None:
        (self.state.dashboard_dir / DASHBOARD_HTML).write_text("<html></html>", encoding="utf-8")
        self._write_marker({"url": "http://127.0.0.1:8765/", "timestamp": 1})

        self.assertNotEqual(dashboard_url(self.repo), "http://127.0.0.1:8765/")
        status = dashboard_url_status(self.repo)
        self.assertFalse(status["healthy"])
        self.assertIsNone(status["live_url"])


if __name__ == "__main__":
    unittest.main()
