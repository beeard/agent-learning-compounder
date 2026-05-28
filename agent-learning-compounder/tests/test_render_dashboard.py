from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader


ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN_DIR = ROOT / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

loader = SourceFileLoader("render_dashboard_module", str(BIN_DIR / "render_dashboard"))
RENDER = loader.load_module()


class RenderDashboardTests(unittest.TestCase):
    def test_default_bundle_is_present_and_renderable(self) -> None:
        self.assertTrue(RENDER.DEFAULT_BUNDLE.exists())
        with tempfile.TemporaryDirectory() as tmp:
            personal = pathlib.Path(tmp)
            latest = RENDER.render(personal, RENDER.DEFAULT_BUNDLE, history_limit=5)

            self.assertEqual(latest.name, "latest-dashboard.html")
            html = latest.read_text(encoding="utf-8")
            self.assertIn('"personal_root"', html)
            self.assertNotIn('{"_placeholder":true}', html)


if __name__ == "__main__":
    unittest.main()
