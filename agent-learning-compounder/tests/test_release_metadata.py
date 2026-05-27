from __future__ import annotations

import json
import pathlib
import re
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
if str(ROOT / "bin") not in sys.path:
    sys.path.insert(0, str(ROOT / "bin"))

import release_metadata


METADATA = release_metadata.RELEASE_METADATA


def _json(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class ReleaseMetadataTests(unittest.TestCase):
    def test_release_versions_match_canonical_surface_mappings(self) -> None:
        manifest = _json(REPO_ROOT / "MANIFEST.json")
        package = _json(REPO_ROOT / "package.json")
        plugin = _json(ROOT / ".claude-plugin" / "plugin.json")
        marketplace = _json(REPO_ROOT / ".claude-plugin" / "marketplace.json")
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

        expected = {
            "MANIFEST.json": METADATA.manifest_version,
            "package.json": METADATA.npm_version,
            "agent-learning-compounder/.claude-plugin/plugin.json": METADATA.plugin_version,
            ".claude-plugin/marketplace.json": METADATA.marketplace_version,
        }
        actual = {
            "MANIFEST.json": manifest["version"],
            "package.json": package["version"],
            "agent-learning-compounder/.claude-plugin/plugin.json": plugin["version"],
            ".claude-plugin/marketplace.json": marketplace["metadata"]["version"],
        }
        mismatches = {
            surface: {"expected": expected[surface], "actual": actual[surface]}
            for surface in expected
            if actual[surface] != expected[surface]
        }
        self.assertEqual(mismatches, {})
        self.assertIn(METADATA.manifest_version, readme)
        self.assertIn(METADATA.manifest_version.replace("+", "%2B").replace("-", "--"), readme)

    def test_package_plugin_and_marketplace_identity_fields_match(self) -> None:
        package = _json(REPO_ROOT / "package.json")
        plugin = _json(ROOT / ".claude-plugin" / "plugin.json")
        marketplace = _json(REPO_ROOT / ".claude-plugin" / "marketplace.json")
        marketplace_plugin = marketplace["plugins"][0]

        self.assertEqual(package["name"], METADATA.name)
        self.assertEqual(plugin["name"], METADATA.name)
        self.assertEqual(marketplace["name"], METADATA.name)
        self.assertEqual(marketplace_plugin["name"], METADATA.name)

        self.assertEqual(package["description"], METADATA.description)
        self.assertEqual(plugin["description"], METADATA.description)
        self.assertEqual(marketplace_plugin["description"], METADATA.description)

        self.assertEqual(package["author"], {"name": METADATA.author.name, "url": METADATA.author.url})
        self.assertEqual(plugin["author"], {"name": METADATA.author.name, "url": METADATA.author.url})
        self.assertEqual(marketplace["owner"], {"name": METADATA.author.name, "url": METADATA.author.url})
        self.assertEqual(marketplace_plugin["author"], {"name": METADATA.author.name, "url": METADATA.author.url})

        self.assertEqual(package["homepage"], METADATA.repository.readme_homepage)
        self.assertEqual(plugin["homepage"], METADATA.repository.homepage)
        self.assertEqual(marketplace_plugin["homepage"], METADATA.repository.homepage)
        self.assertEqual(package["repository"], {"type": "git", "url": METADATA.repository.git_url})
        self.assertEqual(plugin["repository"], METADATA.repository.https_url)
        self.assertEqual(package["bugs"], {"url": METADATA.repository.issues_url})

    def test_keyword_and_tag_sets_match_canonical_metadata(self) -> None:
        package = _json(REPO_ROOT / "package.json")
        plugin = _json(ROOT / ".claude-plugin" / "plugin.json")
        marketplace = _json(REPO_ROOT / ".claude-plugin" / "marketplace.json")
        marketplace_plugin = marketplace["plugins"][0]

        expected = list(METADATA.keywords)
        self.assertEqual(package["keywords"], expected)
        self.assertEqual(plugin["keywords"], expected)
        self.assertEqual(marketplace_plugin["tags"], expected)
        self.assertEqual(marketplace_plugin["category"], METADATA.marketplace_category)

    def test_readme_has_no_stale_release_family_mentions(self) -> None:
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        versions = set(re.findall(r"2026\.\d{2}\.\d{2}\+review\d+-plus\d+\.\d+", readme))
        self.assertEqual(versions, {METADATA.manifest_version})


if __name__ == "__main__":
    unittest.main()
