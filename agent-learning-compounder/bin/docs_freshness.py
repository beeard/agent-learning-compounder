#!/usr/bin/env python3
"""Freshness checks for current release/install documentation."""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
import unittest
from dataclasses import dataclass
from typing import Iterable

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "bin") not in sys.path:
    sys.path.insert(0, str(ROOT / "bin"))

from alc_mcp.catalog import MCP_TOOLS
import release_layout
import release_metadata


CURRENT_VERSION = release_metadata.RELEASE_METADATA.manifest_version
MCP_COUNT = len(MCP_TOOLS)


@dataclass(frozen=True)
class Finding:
    path: str
    message: str

    def render(self) -> str:
        return f"{self.path}: {self.message}"


SOURCE_DOCS = (
    "README.md",
    "CONTEXT.md",
    "docs/QUICKSTART.md",
    "docs/llm-install-prompt.md",
    "CHANGES.md",
    "agent-learning-compounder/skills/alc-core/SKILL.md",
)

STALE_BOOTSTRAP_PATTERNS = (
    re.compile(r"--bootstrap-repo[\s\S]{0,180}auto-detects?\s+[`~./\w\s-]*\.agents[\s\S]{0,80}\.claude", re.I),
    re.compile(r"auto-detects?\s+(?:your\s+)?runtime\s*\(Codex\s*/\s*Claude", re.I),
    re.compile(r"auto-detects?\s+Codex\s+vs\s+Claude", re.I),
)


def test_counts() -> tuple[int, int]:
    loader = unittest.TestLoader()
    smoke = loader.discover(str(ROOT / "tests")).countTestCases()
    fixtures = loader.discover(str(ROOT / "fixtures" / "tests")).countTestCases()
    return smoke, fixtures


def _relative(path: pathlib.Path, root: pathlib.Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _scan_current_status(path: pathlib.Path, text: str, *, enforce_test_counts: bool) -> list[Finding]:
    rel = _relative(path, REPO_ROOT)
    findings: list[Finding] = []

    if rel in {"README.md", "CONTEXT.md"}:
        for version in sorted(set(re.findall(r"2026\.\d{2}\.\d{2}\+review\d+-plus\d+\.\d+", text))):
            if version != CURRENT_VERSION:
                findings.append(Finding(rel, f"current release version {version} does not match {CURRENT_VERSION}"))

    if rel == "README.md":
        expected_badge = f"MCP-{MCP_COUNT}_stdio_tools"
        if expected_badge not in text:
            findings.append(Finding(rel, f"MCP badge must use {MCP_COUNT} stdio tools"))
        for count in re.findall(r"\b(\d+)\s+MCP tools total\b", text):
            if int(count) != MCP_COUNT:
                findings.append(Finding(rel, f"MCP prose says {count} tools, expected {MCP_COUNT}"))

    if rel == "CONTEXT.md":
        expected_catalog = f"M1-M{MCP_COUNT}"
        if expected_catalog not in text:
            findings.append(Finding(rel, f"MCP catalog range must mention {expected_catalog}"))

    if enforce_test_counts and rel in {"README.md", "CONTEXT.md"}:
        smoke, fixtures = test_counts()
        if rel == "README.md":
            expected = f"tests-{smoke}_smoke_%2B_{fixtures}_unit_%2B_4_pressure"
            if expected not in text:
                findings.append(Finding(rel, f"test badge must use {smoke} smoke and {fixtures} unit tests"))
            if f"# {fixtures} unit + integration" not in text:
                findings.append(Finding(rel, f"verify block must use {fixtures} unit + integration tests"))
            if f"# {smoke} post-install smoke" not in text:
                findings.append(Finding(rel, f"verify block must use {smoke} post-install smoke tests"))
        else:
            if f"~{smoke} tests" not in text or f"~{fixtures} tests" not in text:
                findings.append(Finding(rel, f"context test counts must mention ~{smoke} and ~{fixtures}"))

    return findings


def _scan_install_semantics(path: pathlib.Path, text: str) -> list[Finding]:
    rel = _relative(path, REPO_ROOT)
    findings: list[Finding] = []
    for pattern in STALE_BOOTSTRAP_PATTERNS:
        if pattern.search(text):
            findings.append(Finding(rel, "bootstrap/runtime wording implies filesystem auto-detection"))
            break
    if "--bootstrap-repo" in text and "--apply-runtime-hooks" not in text and rel != "CHANGES.md":
        findings.append(Finding(rel, "bootstrap docs must mention --apply-runtime-hooks for hook writes"))
    if "Codex MCP" in text and "not" not in text.lower() and rel != "CHANGES.md":
        findings.append(Finding(rel, "bootstrap docs must not imply automatic Codex MCP registration"))
    return findings


def _scan_audit_doc(path: pathlib.Path, text: str) -> list[Finding]:
    rel = _relative(path, REPO_ROOT)
    first_twenty = "\n".join(text.splitlines()[:20])
    if "Historical status:" in first_twenty or "Superseded by:" in first_twenty:
        return []
    stale_words = re.search(r"\b(current|currently|today|actual|gap|missing|never invoked)\b", text, re.I)
    if stale_words:
        return [Finding(rel, "audit doc with current-state wording needs a historical marker in the first 20 lines")]
    return []


def source_scope_files(root: pathlib.Path = REPO_ROOT) -> list[pathlib.Path]:
    files = [root / rel for rel in SOURCE_DOCS if (root / rel).exists()]
    files.extend(sorted((root / "docs" / "dev").glob("*audit*.md")))
    return files


def release_scope_files(root: pathlib.Path) -> list[pathlib.Path]:
    return sorted(path for path in root.rglob("*.md") if path.is_file())


def scan_source_scope(*, enforce_test_counts: bool = False) -> list[Finding]:
    findings: list[Finding] = []
    for path in source_scope_files():
        text = path.read_text(encoding="utf-8")
        if path.match("*/docs/dev/*audit*.md"):
            findings.extend(_scan_audit_doc(path, text))
            continue
        findings.extend(_scan_current_status(path, text, enforce_test_counts=enforce_test_counts))
        findings.extend(_scan_install_semantics(path, text))
    return findings


def scan_release_scope(root: pathlib.Path, *, enforce_test_counts: bool = False) -> list[Finding]:
    findings: list[Finding] = []
    for internal in ("docs/dev", "docs/plans", "docs/history", "docs/decisions"):
        if (root / internal).exists():
            findings.append(Finding(internal, "internal docs directory must not ship in release artifacts"))
    for path in release_scope_files(root):
        text = path.read_text(encoding="utf-8")
        findings.extend(_scan_current_status(path, text, enforce_test_counts=enforce_test_counts))
        findings.extend(_scan_install_semantics(path, text))
    return findings


def print_findings(findings: Iterable[Finding]) -> int:
    rows = list(findings)
    for finding in rows:
        print(finding.render(), file=sys.stderr)
    return 1 if rows else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--source-scope", action="store_true")
    group.add_argument("--release-scope", action="store_true")
    parser.add_argument("--root", type=pathlib.Path)
    parser.add_argument("--enforce-test-counts", action="store_true")
    args = parser.parse_args()

    if args.source_scope:
        return print_findings(scan_source_scope(enforce_test_counts=args.enforce_test_counts))
    if not args.root:
        parser.error("--release-scope requires --root")
    return print_findings(scan_release_scope(args.root, enforce_test_counts=args.enforce_test_counts))


if __name__ == "__main__":
    raise SystemExit(main())
