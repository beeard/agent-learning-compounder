from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
if str(ROOT / "bin") not in sys.path:
    sys.path.insert(0, str(ROOT / "bin"))

import release_manifest


class ReleaseManifestTests(unittest.TestCase):
    def test_manifest_entries_include_hash_and_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "README.md").write_text("hello\n", encoding="utf-8")
            entries = release_manifest.inspect_tree(root)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].path, "README.md")
        self.assertEqual(entries[0].size, 6)
        self.assertEqual(len(entries[0].sha256), 64)

    def test_release_manifest_records_archive_zip_npm_sections(self) -> None:
        entry = release_manifest.FileEntry("README.md", 6, "0" * 64)
        manifest = release_manifest.build_manifest(
            version="v",
            source_commit="abc",
            archive_root="agent-learning-compounder-v",
            tar_entries=[entry],
            zip_entries=[entry],
            npm_entries=[],
        )
        self.assertEqual(manifest["archive"]["files"][0]["path"], "README.md")
        self.assertEqual(manifest["zip"]["files"][0]["sha256"], "0" * 64)
        self.assertEqual(manifest["npm"]["files"], [])
        self.assertEqual(manifest["source_commit"], "abc")

    def test_dirty_classifier_ignores_pruned_internal_docs(self) -> None:
        self.assertFalse(release_manifest.is_package_affecting_path("docs/plans/example.md"))
        self.assertFalse(release_manifest.is_package_affecting_path("docs/history/example.md"))
        self.assertTrue(release_manifest.is_package_affecting_path("docs/QUICKSTART.md"))
        self.assertTrue(release_manifest.is_package_affecting_path("README.md"))


if __name__ == "__main__":
    unittest.main()
