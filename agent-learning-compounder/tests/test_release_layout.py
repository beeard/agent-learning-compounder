from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
if str(ROOT / "bin") not in sys.path:
    sys.path.insert(0, str(ROOT / "bin"))

import release_layout


def _json(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class ReleaseLayoutTests(unittest.TestCase):
    def test_build_release_adapter_reads_top_level_layout_from_module(self) -> None:
        script = (REPO_ROOT / "scripts" / "build_release.sh").read_text(encoding="utf-8")
        self.assertIn("release_layout.py", script)
        self.assertIn("--shell top-files", script)
        self.assertIn("--shell top-dirs", script)
        self.assertIn("--shell build-pruned-paths", script)

        for key, expected in {
            "top-files": release_layout.SHIPPED_TOP_LEVEL_FILES,
            "top-dirs": release_layout.SHIPPED_TOP_LEVEL_DIRS,
            "build-pruned-paths": release_layout.BUILD_PRUNED_PATHS,
        }.items():
            result = subprocess.run(
                ["python3", str(ROOT / "bin" / "release_layout.py"), "--shell", key],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip().split(), list(expected))

    def test_sanitizer_declares_canonical_exclusions(self) -> None:
        script = (REPO_ROOT / "scripts" / "sanitize_skill_tree.sh").read_text(encoding="utf-8")
        dir_match = re.search(r"^SANITIZE_DIR_EXCLUDES='([^']+)'", script, re.MULTILINE)
        file_match = re.search(r"^SANITIZE_FILE_EXCLUDES='([^']+)'", script, re.MULTILINE)
        self.assertIsNotNone(dir_match)
        self.assertIsNotNone(file_match)
        self.assertEqual(tuple(dir_match.group(1).split()), release_layout.SANITIZER_DIR_EXCLUSIONS)
        self.assertEqual(tuple(file_match.group(1).split()), release_layout.SANITIZER_FILE_EXCLUSIONS)

    def test_sanitizer_behavior_matches_layout_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "agent-learning-compounder"
            root.mkdir()
            for directory in release_layout.SANITIZER_DIR_EXCLUSIONS:
                target = root / "nested" / directory
                target.mkdir(parents=True, exist_ok=True)
                (target / "leak.txt").write_text("cache", encoding="utf-8")
            for pattern in release_layout.SANITIZER_FILE_EXCLUSIONS:
                name = "sample.pyc" if "*" in pattern else pattern
                target = root / "nested" / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("cache", encoding="utf-8")
            survivor_dir = root / "nested" / "source-data"
            survivor_dir.mkdir(parents=True, exist_ok=True)
            survivor_file = survivor_dir / "keep.txt"
            survivor_file.write_text("keep", encoding="utf-8")

            command = (
                f". {REPO_ROOT / 'scripts' / 'sanitize_skill_tree.sh'} && "
                f"sanitize_skill_tree {root}"
            )
            result = subprocess.run(
                ["sh", "-c", command],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            leaked = [
                path.relative_to(root)
                for path in root.rglob("*")
                if release_layout.is_sanitizer_excluded(path.relative_to(root))
            ]
            self.assertEqual(leaked, [])
            self.assertTrue(survivor_file.exists())

    def test_package_and_manifest_policy_match_layout_module(self) -> None:
        package = _json(REPO_ROOT / "package.json")
        manifest = _json(REPO_ROOT / "MANIFEST.json")

        self.assertEqual(package["files"], list(release_layout.NPM_FILES))
        self.assertEqual(manifest["required_docs"], list(release_layout.REQUIRED_DOCS))
        self.assertEqual(
            manifest["excluded_from_package"],
            list(release_layout.MANIFEST_EXCLUDED_FROM_PACKAGE),
        )

    def test_release_file_iterator_uses_canonical_exclusions(self) -> None:
        files = release_layout.iter_release_files(REPO_ROOT)
        rendered = {path.as_posix() for path in files}
        self.assertTrue(rendered)
        self.assertIn("README.md", rendered)
        self.assertIn("agent-learning-compounder/AGENTS.md", rendered)
        self.assertNotIn("docs/dev/architecture-review-closeout-2026-05-27.md", rendered)
        self.assertFalse(any("__pycache__" in path for path in rendered))
        self.assertFalse(any(path.endswith(".pyc") for path in rendered))
        self.assertFalse(any("/.pytest_cache/" in path for path in rendered))


if __name__ == "__main__":
    unittest.main()
