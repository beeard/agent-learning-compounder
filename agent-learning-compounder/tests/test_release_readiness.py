from __future__ import annotations

import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "bin") not in sys.path:
    sys.path.insert(0, str(ROOT / "bin"))

import release_manifest
import validate_release_ready


class ReleaseReadinessTests(unittest.TestCase):
    def test_inventory_mismatch_reports_missing_extra_and_changed(self) -> None:
        left = [
            release_manifest.FileEntry("a.txt", 1, "a" * 64),
            release_manifest.FileEntry("changed.txt", 1, "b" * 64),
        ]
        right = [
            release_manifest.FileEntry("b.txt", 1, "a" * 64),
            release_manifest.FileEntry("changed.txt", 1, "c" * 64),
        ]
        with self.assertRaisesRegex(RuntimeError, "tar/zip inventories differ"):
            validate_release_ready._assert_same(left, right)

    def test_inventory_match_passes(self) -> None:
        entries = [release_manifest.FileEntry("a.txt", 1, "a" * 64)]
        validate_release_ready._assert_same(entries, entries)


if __name__ == "__main__":
    unittest.main()
