from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

import repo_profile


def _seed_repo(root: pathlib.Path) -> None:
    (root / ".git").mkdir()
    (root / "package.json").write_text(
        json.dumps(
            {
                "dependencies": {
                    "react": "^18.0.0",
                    "@cloudflare/workers-types": "^4.0.0",
                }
            }
        ),
        encoding="utf-8",
    )
    (root / "pnpm-workspace.yaml").write_text("packages:\n  - apps/*\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "app.tsx").write_text("export {};\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "app.test.ts").write_text("it('works', () => {});\n", encoding="utf-8")


class RepoProfileTests(unittest.TestCase):
    def test_detect_returns_existing_profile_vocabulary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp)
            _seed_repo(repo)

            profile = repo_profile.detect(repo)

            self.assertEqual(profile["name"], repo.name)
            self.assertEqual(profile["abspath"], str(repo))
            self.assertTrue(profile["has_git"])
            self.assertTrue(profile["has_tests"])
            self.assertTrue(profile["has_frontend"])
            self.assertTrue(profile["monorepo"])
            self.assertIn("typescript", profile["languages"])
            self.assertIn("react", profile["frameworks"])
            self.assertIn("cloudflare-workers", profile["frameworks"])
            self.assertIn("npm", profile["package_managers"])

    def test_doc_contract_rows_preserve_labels_paths_generators_and_tiers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp)
            (repo / "docs" / "plans").mkdir(parents=True)
            (repo / "AGENTS.md").write_text("# guide\n", encoding="utf-8")

            rows = repo_profile.doc_contract_rows(repo)

            by_label = {row["label"]: row for row in rows}
            self.assertEqual(by_label["Repo guide"]["found"], "AGENTS.md")
            self.assertEqual(by_label["Repo guide"]["generator"], None)
            self.assertEqual(by_label["Repo guide"]["tier"], "anchor")
            self.assertEqual(by_label["Plans"]["found"], "docs/plans")
            self.assertEqual(by_label["Plans"]["generator"], "ce-plan")
            self.assertEqual(by_label["STRATEGY.md"]["paths_checked"], ["STRATEGY.md"])
            self.assertIsNone(by_label["STRATEGY.md"]["found"])

    def test_ce_usage_counts_shapes_alc_query_rows_for_playbook(self) -> None:
        rows = [
            {"actor_name": "ce-work", "count": 3},
            {"actor_name": "ce-plan", "count": 2},
            {"actor_name": "", "count": 7},
        ]

        self.assertEqual(repo_profile.ce_usage_counts(rows), {"ce-work": 3, "ce-plan": 2})


if __name__ == "__main__":
    unittest.main()
