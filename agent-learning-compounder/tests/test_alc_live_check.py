from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader


ROOT = pathlib.Path(__file__).resolve().parents[1]
LIVE_CHECK = ROOT / "bin" / "alc_live_check"

loader = SourceFileLoader("alc_live_check_module", str(LIVE_CHECK))
ALC_LIVE_CHECK = loader.load_module()


class AlcLiveCheckTests(unittest.TestCase):
    def test_help_is_available(self) -> None:
        result = subprocess.run(
            ["python3", str(LIVE_CHECK), "--help"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--repo", result.stdout)
        self.assertIn("--apply-hooks", result.stdout)
        self.assertIn("--serve-dashboard", result.stdout)

    def test_yes_mode_builds_context_without_prompting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = ALC_LIVE_CHECK.parse_args(["--repo", tmp, "--yes", "--no-verify", "--no-apply-hooks"])
            ctx = ALC_LIVE_CHECK.build_context(args)
            self.assertEqual(ctx.repo, pathlib.Path(tmp).resolve())
            self.assertEqual(ctx.runtime, "codex")
            self.assertFalse(ctx.verify)
            self.assertFalse(ctx.apply_hooks)
            self.assertFalse(ctx.serve_dashboard)

    def test_live_check_passes_against_temp_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp) / "repo"
            repo.mkdir()
            (repo / "README.md").write_text("# smoke\n", encoding="utf-8")
            init = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "bin" / "init_learning_system"),
                    "--repo",
                    str(repo),
                    "--runtime",
                    "codex",
                    "--install-repo-integration",
                    "--install-hooks",
                    "--self-test",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(init.returncode, 0, init.stdout + init.stderr)

            result = subprocess.run(
                [
                    sys.executable,
                    str(LIVE_CHECK),
                    "--repo",
                    str(repo),
                    "--runtime",
                    "codex",
                    "--skip-install",
                    "--no-verify",
                    "--no-apply-hooks",
                    "--no-install-deps",
                    "--no-serve-dashboard",
                    "--yes",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("RESULT: PASS", result.stdout)
            self.assertIn("PASS  sqlite:", result.stdout)
            self.assertIn("PASS  static dashboard:", result.stdout)
            self.assertIn("PASS  mcp tools/list:", result.stdout)


if __name__ == "__main__":
    unittest.main()
