from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
if str(ROOT / "bin") not in sys.path:
    sys.path.insert(0, str(ROOT / "bin"))

import docs_freshness


class DocsFreshnessTests(unittest.TestCase):
    def test_stale_readme_mcp_count_fails(self) -> None:
        text = "12 MCP tools total\n"
        findings = docs_freshness._scan_current_status(REPO_ROOT / "README.md", text, enforce_test_counts=False)
        self.assertTrue(any("MCP" in finding.message for finding in findings))

    def test_bootstrap_auto_filesystem_detection_wording_fails(self) -> None:
        text = "Run ./install.sh --bootstrap-repo \"$PWD\". It auto-detects ~/.agents/ vs ~/.claude/."
        findings = docs_freshness._scan_install_semantics(REPO_ROOT / "docs" / "QUICKSTART.md", text)
        self.assertTrue(any("filesystem auto-detection" in finding.message for finding in findings))

    def test_audit_marker_must_be_near_top(self) -> None:
        stale = "\n".join(["# Audit", "current gap"] + ["x"] * 20 + ["Historical status: old"])
        findings = docs_freshness._scan_audit_doc(REPO_ROOT / "docs" / "dev" / "x-audit.md", stale)
        self.assertEqual(len(findings), 1)
        fresh = "# Audit\n\n> Historical status: superseded by current release controls.\n\ncurrent gap"
        self.assertEqual(docs_freshness._scan_audit_doc(REPO_ROOT / "docs" / "dev" / "x-audit.md", fresh), [])

    def test_release_scope_rejects_internal_docs_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "docs" / "plans").mkdir(parents=True)
            (root / "docs" / "plans" / "plan.md").write_text("# plan\n", encoding="utf-8")
            findings = docs_freshness.scan_release_scope(root)
        self.assertTrue(any("internal docs directory" in finding.message for finding in findings))


if __name__ == "__main__":
    unittest.main()
