from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "bin"))

import ce_playbook  # noqa: E402


CE_PLAYBOOK = REPO_ROOT / "bin" / "ce_playbook"


def _run(args: list[str], stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CE_PLAYBOOK), *args],
        input=stdin, text=True, capture_output=True, check=False,
    )


class PersonaSelectionTests(unittest.TestCase):
    def test_rails_picks_dhh_reviewer(self):
        self.assertEqual(
            ce_playbook.pick_persona({"frameworks": ["rails"]}),
            "ce-dhh-rails-reviewer",
        )

    def test_nextjs_picks_kieran_typescript(self):
        self.assertEqual(
            ce_playbook.pick_persona({"frameworks": ["nextjs", "react"]}),
            "ce-kieran-typescript-reviewer",
        )

    def test_python_only_falls_back_to_language(self):
        self.assertEqual(
            ce_playbook.pick_persona({"languages": {"python": 100, "shell": 5}}),
            "ce-kieran-python-reviewer",
        )

    def test_empty_profile_returns_none(self):
        self.assertIsNone(ce_playbook.pick_persona({}))


class RenderTests(unittest.TestCase):
    def test_rails_renders_dhh_persona_and_simplify_hint(self):
        body = ce_playbook.render(
            {"frameworks": ["rails"], "languages": {"ruby": 200}, "has_tests": True},
            ce_installed=True,
        )
        self.assertIn("`ce-dhh-rails-reviewer`", body)
        self.assertIn("fat-controller", body)
        # CE installed → no install banner
        self.assertNotIn("Compound-engineering plugin not detected", body)

    def test_nextjs_monorepo_no_tests_warns_about_tests(self):
        body = ce_playbook.render(
            {
                "frameworks": ["nextjs", "react"],
                "languages": {"typescript": 500},
                "has_tests": False,
                "has_frontend": True,
                "monorepo": True,
            },
            ce_installed=True,
        )
        self.assertIn("`ce-kieran-typescript-reviewer`", body)
        self.assertIn("Monorepo:", body)
        self.assertIn("no top-level `tests/`", body)
        self.assertIn("Especially valuable in monorepos", body)
        self.assertIn("hook extraction", body)

    def test_ce_not_installed_includes_install_banner(self):
        body = ce_playbook.render(
            {"frameworks": ["rails"], "languages": {"ruby": 100}},
            ce_installed=False,
        )
        self.assertIn("Compound-engineering plugin not detected", body)
        self.assertIn("/plugin marketplace add EveryInc/compound-engineering-plugin", body)
        # Hints still render below the banner
        self.assertIn("`/ce-brainstorm`", body)
        self.assertIn("`/ce-plan`", body)

    def test_all_five_commands_present(self):
        body = ce_playbook.render({"frameworks": [], "languages": {"go": 50}}, ce_installed=True)
        for cmd in ("/ce-brainstorm", "/ce-plan", "/ce-work", "/ce-simplify-code", "/improve-codebase-architecture"):
            self.assertIn(f"`{cmd}`", body, f"missing {cmd}")

    def test_go_language_gets_interface_boundary_hint(self):
        body = ce_playbook.render({"frameworks": [], "languages": {"go": 200}}, ce_installed=True)
        self.assertIn("interface boundaries", body)


class DetectCETests(unittest.TestCase):
    def test_detects_marketplace_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_home = pathlib.Path(tmp)
            (fake_home / ".claude" / "plugins" / "marketplaces"
                / "compound-engineering-plugin").mkdir(parents=True)
            self.assertTrue(ce_playbook.detect_ce_installed(home=fake_home))

    def test_returns_false_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(ce_playbook.detect_ce_installed(home=pathlib.Path(tmp)))

    def test_detects_codex_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_home = pathlib.Path(tmp)
            (fake_home / ".agents" / "skills" / "compound-engineering").mkdir(parents=True)
            self.assertTrue(ce_playbook.detect_ce_installed(home=fake_home))


class CliTests(unittest.TestCase):
    def test_cli_reads_profile_from_stdin(self):
        payload = json.dumps({"profile": {"frameworks": ["rails"], "languages": {"ruby": 100}}})
        result = _run(["--profile", "-", "--ce-installed", "no"], stdin=payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ce-dhh-rails-reviewer", result.stdout)
        self.assertIn("Compound-engineering plugin not detected", result.stdout)

    def test_cli_reads_profile_from_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload_path = pathlib.Path(tmp) / "profile.json"
            payload_path.write_text(json.dumps({
                "profile": {"frameworks": ["nextjs", "react"], "languages": {"typescript": 300}}
            }), encoding="utf-8")
            result = _run(["--profile", str(payload_path), "--ce-installed", "yes"])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("ce-kieran-typescript-reviewer", result.stdout)


if __name__ == "__main__":
    unittest.main()
