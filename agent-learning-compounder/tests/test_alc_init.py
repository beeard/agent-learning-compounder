from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ALC_INIT = REPO_ROOT / "bin" / "alc_init"


def _run(args: list[str], cwd: pathlib.Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ALC_INIT), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def _seed_target_repo(root: pathlib.Path, *, with_tests: bool = True, framework: str = "react") -> None:
    """Create a minimal target repo that detect_repo() can profile."""
    (root / ".git").mkdir(parents=True)
    pkg = {
        "name": "target-app",
        "version": "1.0.0",
        "dependencies": {framework: "^18.0.0"},
    }
    (root / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "index.ts").write_text("export const x = 1;\n", encoding="utf-8")
    (root / "src" / "app.tsx").write_text("export {};\n", encoding="utf-8")
    if with_tests:
        (root / "tests").mkdir()
        (root / "tests" / "app.test.ts").write_text("it('works', () => {});\n", encoding="utf-8")


class AlcInitTests(unittest.TestCase):
    def test_writes_session_context_with_expected_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            repo = root / "target"
            state = root / "state"
            _seed_target_repo(repo)

            proc = _run(["--repo", str(repo), "--state-dir", str(state),
                         "--skip-mcp-smoke", "--quiet"])
            self.assertEqual(proc.returncode, 0, proc.stderr)

            summary = json.loads(proc.stdout)
            self.assertEqual(summary["repo"], str(repo))
            self.assertEqual(summary["state_root"], str(state))
            self.assertTrue(summary["profile"]["has_tests"])
            self.assertTrue(summary["profile"]["has_git"])
            self.assertIn("react", summary["profile"]["frameworks"])
            self.assertIn("typescript", summary["profile"]["languages"])
            self.assertEqual(summary["mcp"]["status"], "skipped")

            context = pathlib.Path(summary["session_context"])
            self.assertTrue(context.is_file())
            body = context.read_text(encoding="utf-8")
            self.assertIn("# Session context", body)
            self.assertIn("typescript", body)
            self.assertIn("react", body)
            self.assertIn("`skipped`", body)
            self.assertIn("Compound-engineering playbook", body)
            # CE playbook content (not the stub from Phase 3) is now present.
            self.assertIn("`/ce-brainstorm`", body)
            self.assertIn("`/ce-plan`", body)
            self.assertIn("`/ce-work`", body)
            self.assertIn("`/ce-simplify-code`", body)
            self.assertIn("`/improve-codebase-architecture`", body)
            # react → kieran-typescript persona pairing
            self.assertIn("ce-kieran-typescript-reviewer", body)
            # ce_plugin_installed appears in JSON summary
            self.assertIn("ce_plugin_installed", proc.stdout)

    def test_idempotent_across_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            repo = root / "target"
            state = root / "state"
            _seed_target_repo(repo)

            proc1 = _run(["--repo", str(repo), "--state-dir", str(state),
                          "--skip-mcp-smoke", "--quiet"])
            self.assertEqual(proc1.returncode, 0, proc1.stderr)
            ctx = pathlib.Path(json.loads(proc1.stdout)["session_context"])
            digest1 = hashlib.sha256(ctx.read_bytes()).hexdigest()

            proc2 = _run(["--repo", str(repo), "--state-dir", str(state),
                          "--skip-mcp-smoke", "--quiet"])
            self.assertEqual(proc2.returncode, 0, proc2.stderr)
            digest2 = hashlib.sha256(ctx.read_bytes()).hexdigest()
            self.assertEqual(digest1, digest2,
                             "session-context content drifted between idempotent runs")

    def test_missing_mcp_returns_nonzero_with_unavailable_status(self) -> None:
        # Simulate "mcp not importable" by running alc_init under a Python that
        # cannot find mcp. We do this by isolating sys.path: launch a fresh
        # interpreter with PYTHONPATH limited so `import mcp` fails.
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            repo = root / "target"
            state = root / "state"
            _seed_target_repo(repo)

            env = os.environ.copy()
            env["PYTHONPATH"] = str(REPO_ROOT / "bin")
            env["PYTHONNOUSERSITE"] = "1"
            # Use sys.executable but with a -I (isolated) flag: no user site,
            # no environment-injected paths. mcp won't import.
            proc = subprocess.run(
                [sys.executable, "-I", str(ALC_INIT),
                 "--repo", str(repo), "--state-dir", str(state), "--quiet"],
                text=True, capture_output=True, check=False, env=env,
            )
            # Exit code 1 because mcp is unavailable; context file should still
            # be written so the user sees the state.
            self.assertEqual(proc.returncode, 1, proc.stderr)
            summary = json.loads(proc.stdout)
            self.assertIn(summary["mcp"]["status"], {"unavailable", "no_tools", "error"})
            self.assertTrue(pathlib.Path(summary["session_context"]).is_file())

    def test_skip_mcp_smoke_returns_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            repo = root / "target"
            state = root / "state"
            _seed_target_repo(repo, with_tests=False, framework="vue")

            proc = _run(["--repo", str(repo), "--state-dir", str(state),
                         "--skip-mcp-smoke", "--quiet"])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            summary = json.loads(proc.stdout)
            self.assertIn("vue", summary["profile"]["frameworks"])
            self.assertFalse(summary["profile"]["has_tests"])


if __name__ == "__main__":
    unittest.main()
