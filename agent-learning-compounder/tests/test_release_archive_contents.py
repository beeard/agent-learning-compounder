from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
if str(ROOT / "bin") not in sys.path:
    sys.path.insert(0, str(ROOT / "bin"))

import release_manifest


class ReleaseArchiveContentsTests(unittest.TestCase):
    def test_excluded_paths_are_detected_after_normalizing_archive_root(self) -> None:
        leaks = release_manifest.find_excluded_paths(
            [
                "agent-learning-compounder-test/scripts/__pycache__/x.pyc",
                "agent-learning-compounder-test/docs/.pytest_cache/CACHEDIR.TAG",
                "agent-learning-compounder-test/agent-learning-compounder/node_modules/x.js",
            ]
        )
        self.assertEqual(
            leaks,
            [
                "agent-learning-compounder/node_modules/x.js",
                "docs/.pytest_cache/CACHEDIR.TAG",
                "scripts/__pycache__/x.pyc",
            ],
        )

    def test_build_release_sanitizes_top_level_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp) / "repo"
            shutil.copytree(REPO_ROOT, repo, ignore=shutil.ignore_patterns(".git"))
            shutil.rmtree(repo / "dist", ignore_errors=True)
            (repo / "scripts" / "__pycache__").mkdir(parents=True, exist_ok=True)
            (repo / "scripts" / "__pycache__" / "x.pyc").write_text("cache", encoding="utf-8")
            (repo / "docs" / ".pytest_cache").mkdir(parents=True, exist_ok=True)
            (repo / "docs" / ".pytest_cache" / "CACHEDIR.TAG").write_text("cache", encoding="utf-8")

            result = subprocess.run(
                [
                    str(repo / "scripts" / "build_release.sh"),
                    "--version",
                    "test-local",
                    "--local-experiment",
                ],
                cwd=repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            with tempfile.TemporaryDirectory() as extract_tmp:
                root = release_manifest.extract_tarball(
                    repo / "dist" / "agent-learning-compounder-test-local.tar.gz",
                    pathlib.Path(extract_tmp),
                )
                entries = release_manifest.inspect_tree(root)
            self.assertEqual(release_manifest.validate_no_excluded(entries), [])
            paths = {entry.path for entry in entries}
            self.assertIn("agent-learning-compounder/dashboard/web/dist/index.html", paths)
            self.assertFalse(any(path.endswith(".tsbuildinfo") for path in paths))


if __name__ == "__main__":
    unittest.main()
