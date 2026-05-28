#!/usr/bin/env python3
"""Repo profile and documentation-contract vocabulary for first-run setup."""

from __future__ import annotations

import json
import os
import pathlib
from typing import Any

# Prefixes that mark a skill as part of the compound-engineering family or
# adjacent workflow tooling worth tracking.
CE_SKILL_PREFIXES = (
    "ce-",
    "compound-engineering:",
    "improve-codebase-architecture",
    "to-prd",
    "to-issues",
)

DOC_CONTRACT = [
    ("STRATEGY.md", ["STRATEGY.md"], "ce-strategy", "anchor"),
    ("Repo guide", ["AGENTS.md", "CLAUDE.md", "GEMINI.md"], None, "anchor"),
    ("ARCHITECTURE.md", ["ARCHITECTURE.md", "docs/ARCHITECTURE.md"],
        "improve-codebase-architecture", "architecture"),
    ("CONTEXT.md", ["CONTEXT.md", "context.md"],
        "ce-agent-native-architecture", "architecture"),
    ("ADRs", ["docs/adr", "docs/adrs", "docs/decisions"],
        "improve-codebase-architecture", "architecture"),
    ("Brainstorms", ["docs/brainstorms"], "ce-brainstorm", "workflow"),
    ("Plans", ["docs/plans"], "ce-plan", "workflow"),
]

EXT_TO_LANG = {
    ".py": "python", ".rb": "ruby", ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
    ".go": "go", ".rs": "rust", ".java": "java", ".kt": "kotlin",
    ".swift": "swift", ".cs": "csharp", ".php": "php", ".clj": "clojure",
    ".ex": "elixir", ".exs": "elixir", ".erl": "erlang", ".scala": "scala",
    ".lua": "lua", ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".sql": "sql", ".vue": "vue", ".svelte": "svelte",
}

SKIP_DIRS = {
    "node_modules", "__pycache__", ".git", ".venv", "venv", "dist", "build",
    ".next", ".nuxt", ".cache", "vendor", "target", ".pytest_cache",
    ".agent-learning", "coverage", ".mypy_cache", ".ruff_cache",
}


def detect(repo: pathlib.Path) -> dict[str, Any]:
    """Profile the host repo. Read-only; bounded traversal."""
    profile: dict[str, Any] = {
        "name": repo.name,
        "abspath": str(repo),
        "has_git": (repo / ".git").is_dir(),
        "languages": {},
        "frameworks": [],
        "has_tests": False,
        "has_frontend": False,
        "monorepo": False,
        "package_managers": [],
    }

    ext_counts: dict[str, int] = {}
    for _dirpath, dirnames, filenames in os.walk(repo):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fname in filenames:
            ext = pathlib.Path(fname).suffix.lower()
            if ext:
                ext_counts[ext] = ext_counts.get(ext, 0) + 1

    for ext, count in ext_counts.items():
        lang = EXT_TO_LANG.get(ext)
        if lang:
            profile["languages"][lang] = profile["languages"].get(lang, 0) + count

    frameworks = profile["frameworks"]
    package_managers = profile["package_managers"]
    if (repo / "Gemfile").is_file():
        package_managers.append("bundler")
        if (repo / "config" / "application.rb").is_file():
            frameworks.append("rails")
    if (repo / "package.json").is_file():
        package_managers.append("npm")
        try:
            pkg = json.loads((repo / "package.json").read_text(encoding="utf-8"))
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            for key, label in (
                ("next", "nextjs"), ("react", "react"), ("vue", "vue"),
                ("svelte", "svelte"), ("@sveltejs/kit", "sveltekit"),
                ("express", "express"), ("fastify", "fastify"),
                ("hono", "hono"), ("@cloudflare/workers-types", "cloudflare-workers"),
            ):
                if key in deps:
                    frameworks.append(label)
            if not frameworks or frameworks == ["node"]:
                frameworks.append("node")
        except Exception:
            pass
    if (repo / "pyproject.toml").is_file():
        package_managers.append("pip/poetry/uv")
        try:
            text = (repo / "pyproject.toml").read_text(encoding="utf-8", errors="ignore").lower()
            if "fastapi" in text:
                frameworks.append("fastapi")
            if "flask" in text:
                frameworks.append("flask")
            if "django" in text:
                frameworks.append("django")
        except Exception:
            pass
    if (repo / "manage.py").is_file():
        frameworks.append("django")
    if (repo / "wrangler.toml").is_file() or (repo / "wrangler.jsonc").is_file():
        frameworks.append("cloudflare-workers")
    if (repo / "Cargo.toml").is_file():
        package_managers.append("cargo")
    if (repo / "go.mod").is_file():
        package_managers.append("go-modules")
    if (repo / "pom.xml").is_file():
        package_managers.append("maven")
    if (repo / "build.gradle").is_file() or (repo / "build.gradle.kts").is_file():
        package_managers.append("gradle")

    for tdir in ("tests", "test", "spec", "__tests__"):
        if (repo / tdir).is_dir():
            profile["has_tests"] = True
            break

    frontend_frameworks = {"react", "vue", "svelte", "sveltekit", "nextjs"}
    if any(f in frontend_frameworks for f in frameworks):
        profile["has_frontend"] = True

    if (repo / "pnpm-workspace.yaml").is_file() or (repo / "lerna.json").is_file():
        profile["monorepo"] = True
    if (repo / "packages").is_dir() and (repo / "package.json").is_file():
        profile["monorepo"] = True
    if (repo / "apps").is_dir() and (repo / "package.json").is_file():
        profile["monorepo"] = True

    profile["frameworks"] = sorted(set(frameworks))
    profile["package_managers"] = sorted(set(package_managers))
    return profile


def doc_contract_rows(repo: pathlib.Path) -> list[dict[str, Any]]:
    """Probe the host repo for the documents ALC's playbook expects."""
    rows: list[dict[str, Any]] = []
    for label, paths, generator, tier in DOC_CONTRACT:
        found = None
        for relpath in paths:
            candidate = repo / relpath
            if candidate.exists():
                found = relpath
                break
        rows.append({
            "label": label,
            "paths_checked": paths,
            "found": found,
            "generator": generator,
            "tier": tier,
        })
    return rows


def ce_usage_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Shape alc_query CE usage rows into ce_playbook's usage-count input."""
    return {
        str(row["actor_name"]): int(row["count"])
        for row in rows
        if row.get("actor_name")
    }
