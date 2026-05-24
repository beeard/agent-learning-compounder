"""Tests for serve_dashboard --host safety gate."""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader


ROOT = pathlib.Path(__file__).resolve().parents[2]
# Use the .py symlink in scripts/ so import machinery recognizes the source.
SERVE = ROOT / "scripts" / "serve_dashboard.py"
SERVE_BIN = ROOT / "bin" / "serve_dashboard"


def _load_module():
    """Import serve_dashboard as a module (script lacks .py extension in bin/)."""
    loader = SourceFileLoader("serve_dashboard_under_test", str(SERVE))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class HostValidationUnitTests(unittest.TestCase):
    def setUp(self):
        self.mod = _load_module()

    def test_loopback_ipv4_accepted(self):
        self.assertIsNone(self.mod.validate_host("127.0.0.1", False))

    def test_loopback_ipv6_accepted(self):
        self.assertIsNone(self.mod.validate_host("::1", False))

    def test_localhost_accepted(self):
        self.assertIsNone(self.mod.validate_host("localhost", False))

    def test_localhost_case_insensitive(self):
        self.assertIsNone(self.mod.validate_host("LocalHost", False))

    def test_all_interfaces_refused_without_flag(self):
        msg = self.mod.validate_host("0.0.0.0", False)
        self.assertIsNotNone(msg)
        self.assertIn("0.0.0.0", msg)
        self.assertIn("--insecure-public", msg)

    def test_public_ip_refused_without_flag(self):
        msg = self.mod.validate_host("203.0.113.5", False)
        self.assertIsNotNone(msg)

    def test_all_interfaces_allowed_with_insecure_flag(self):
        self.assertIsNone(self.mod.validate_host("0.0.0.0", True))


class HostValidationCliTests(unittest.TestCase):
    def test_help_mentions_insecure_public(self):
        result = subprocess.run(
            [sys.executable, str(SERVE_BIN), "--help"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--insecure-public", result.stdout)

    def test_cli_refuses_non_loopback_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    str(SERVE_BIN),
                    "--repo", tmp,
                    "--host", "0.0.0.0",
                    "--port", "0",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=15,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("0.0.0.0", result.stderr)
        self.assertIn("--insecure-public", result.stderr)


if __name__ == "__main__":
    unittest.main()
