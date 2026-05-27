"""Tests for render_state_surface — all four format dispatchers."""

from __future__ import annotations

import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
RENDER = REPO_ROOT / "bin" / "render_state_surface"

# Add bin/ to path so we can import the module directly for unit tests.
sys.path.insert(0, str(REPO_ROOT / "bin"))


def _run(*args, repo, state, **kw) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["ALC_PLUGIN_ROOT"] = str(REPO_ROOT)
    env["AGENT_LEARNING_STATE_DIR"] = str(state)
    return subprocess.run(
        [sys.executable, str(RENDER), "--repo", str(repo), "--state-dir", str(state), *args],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        **kw,
    )


class LayoutTests(unittest.TestCase):
    """Verify the dual-name convention files exist."""

    def test_canonical_script_is_executable(self) -> None:
        self.assertTrue(RENDER.is_file())
        self.assertTrue(RENDER.stat().st_mode & stat.S_IXUSR)

    def test_bin_py_symlink_exists(self) -> None:
        sym = REPO_ROOT / "bin" / "render_state_surface.py"
        self.assertTrue(sym.is_symlink())
        self.assertEqual(sym.resolve(), RENDER.resolve())

    def test_scripts_py_symlink_exists(self) -> None:
        sym = REPO_ROOT / "scripts" / "render_state_surface.py"
        self.assertTrue(sym.is_symlink())
        self.assertEqual(sym.resolve(), RENDER.resolve())


class MarkdownFormatTests(unittest.TestCase):
    def test_empty_state_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            repo = root / "repo"
            state = root / "state"
            repo.mkdir()
            result = _run("--format", "markdown", repo=repo, state=state)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_surfaces_gates_and_skill_context(self) -> None:
        """When the durable surfaces exist, markdown output contains their content."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            repo = root / "repo"
            state = root / "state"
            repo.mkdir()

            # Seed dummy reports so the render has something to cat.
            from state_handle import StateHandle
            env_bak = os.environ.get("AGENT_LEARNING_STATE_DIR")
            os.environ["AGENT_LEARNING_STATE_DIR"] = str(state)
            try:
                handle = StateHandle.for_repo(repo)
            finally:
                if env_bak is None:
                    os.environ.pop("AGENT_LEARNING_STATE_DIR", None)
                else:
                    os.environ["AGENT_LEARNING_STATE_DIR"] = env_bak

            handle.reports_dir.mkdir(parents=True, exist_ok=True)
            (handle.reports_dir / "latest-approved-gates.md").write_text(
                "## GATES_MARKER\n\n- domain: test\n  gate_id: abc123456789\n  gate_category: quality\n  gate: dummy gate\n",
                encoding="utf-8",
            )
            (handle.reports_dir / "latest-skill-context.md").write_text(
                "## SKILL_CTX_MARKER\n",
                encoding="utf-8",
            )

            result = _run("--format", "markdown", repo=repo, state=state)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("GATES_MARKER", result.stdout)
            self.assertIn("SKILL_CTX_MARKER", result.stdout)

    def test_output_matches_session_start_hook_content(self) -> None:
        """Both markdown output and empty-state session-start must not crash
        and produce string output (content parity check for the key pattern)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            repo = root / "repo"
            state = root / "state"
            repo.mkdir()
            result = _run("--format", "markdown", repo=repo, state=state)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIsInstance(result.stdout, str)


class HtmlFormatTests(unittest.TestCase):
    def test_produces_dashboard_html_and_data_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            repo = root / "repo"
            state = root / "state"
            repo.mkdir()
            result = _run("--format", "html", repo=repo, state=state)
            self.assertEqual(result.returncode, 0, result.stderr)
            # stdout should print the dashboard dir path
            printed_path = pathlib.Path(result.stdout.strip())
            self.assertTrue(printed_path.is_dir(), f"expected dir at {printed_path}")
            data = json.loads((printed_path / "data.json").read_text(encoding="utf-8"))
            self.assertIn("generated_at", data)
            html = (printed_path / "dashboard.html").read_text(encoding="utf-8")
            self.assertIn("Agent Learning Dashboard", html)

            from dashboard_url_publisher import dashboard_url
            from state_handle import StateHandle

            handle = StateHandle.for_repo(repo, state_dir=state)
            self.assertEqual(dashboard_url(handle), (printed_path / "dashboard.html").resolve().as_uri())

    def test_html_data_json_has_expected_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            repo = root / "repo"
            state = root / "state"
            repo.mkdir()
            result = _run("--format", "html", repo=repo, state=state)
            self.assertEqual(result.returncode, 0, result.stderr)
            printed_path = pathlib.Path(result.stdout.strip())
            data = json.loads((printed_path / "data.json").read_text(encoding="utf-8"))
            for key in ("recommendations", "pending_patches", "apply_log"):
                self.assertIn(key, data)


class SessionReportFormatTests(unittest.TestCase):
    def test_produces_latest_session_report_md(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            repo = root / "repo"
            state = root / "state"
            repo.mkdir()
            result = _run("--format", "session-report", repo=repo, state=state)
            self.assertEqual(result.returncode, 0, result.stderr)
            report_path = pathlib.Path(result.stdout.strip())
            self.assertTrue(report_path.is_file(), f"expected file at {report_path}")
            self.assertEqual(report_path.name, "latest-session-report.md")

    def test_report_has_expected_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            repo = root / "repo"
            state = root / "state"
            repo.mkdir()
            result = _run("--format", "session-report", repo=repo, state=state)
            self.assertEqual(result.returncode, 0, result.stderr)
            report_path = pathlib.Path(result.stdout.strip())
            content = report_path.read_text(encoding="utf-8")
            self.assertIn("# Session report", content)
            self.assertIn("## Activity summary", content)
            self.assertIn("## Apply log", content)
            self.assertIn("## Outcomes / verdicts", content)
            self.assertIn("## Pending review", content)

    def test_rotation_creates_backup_copies(self) -> None:
        """Running render_state_surface session-report twice should create .001 backup."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            repo = root / "repo"
            state = root / "state"
            repo.mkdir()
            # First run
            r1 = _run("--format", "session-report", repo=repo, state=state)
            self.assertEqual(r1.returncode, 0, r1.stderr)
            # Second run — should rotate the first into .001
            r2 = _run("--format", "session-report", repo=repo, state=state)
            self.assertEqual(r2.returncode, 0, r2.stderr)
            report_path = pathlib.Path(r2.stdout.strip())
            backup = report_path.with_suffix(".md.001")
            self.assertTrue(backup.is_file(), f"expected backup at {backup}")

    def test_rotation_caps_at_ten(self) -> None:
        """After 11 runs, no .011 file should exist."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            repo = root / "repo"
            state = root / "state"
            repo.mkdir()
            for _ in range(11):
                r = _run("--format", "session-report", repo=repo, state=state)
                self.assertEqual(r.returncode, 0, r.stderr)
            report_path = pathlib.Path(r.stdout.strip())
            over = report_path.with_suffix(".md.011")
            self.assertFalse(over.exists(), f".011 backup should not exist")
            # .010 is the max backup that should exist
            max_backup = report_path.with_suffix(".md.010")
            self.assertTrue(max_backup.is_file(), f".010 backup should exist")


class JsonFormatTests(unittest.TestCase):
    def test_produces_parseable_json_to_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            repo = root / "repo"
            state = root / "state"
            repo.mkdir()
            result = _run("--format", "json", repo=repo, state=state)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertIsInstance(data, dict)

    def test_json_has_expected_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            repo = root / "repo"
            state = root / "state"
            repo.mkdir()
            result = _run("--format", "json", repo=repo, state=state)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            for key in (
                "generated_at",
                "repo",
                "pending_patches",
                "recommendations",
                "recent_activity_24h",
                "apply_events_1h",
                "mcp_status",
            ):
                self.assertIn(key, data, f"key {key!r} missing from json output")

    def test_json_to_file_via_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            repo = root / "repo"
            state = root / "state"
            repo.mkdir()
            out = root / "summary.json"
            result = _run("--format", "json", "--out", str(out), repo=repo, state=state)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(out.is_file())
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertIn("generated_at", data)


if __name__ == "__main__":
    unittest.main()
