#!/usr/bin/env python3
"""Canonical release metadata for package-visible adapters.

Keep ecosystem-specific spelling here so release surfaces can stay shallow
without independently inventing identity fields.
"""

from __future__ import annotations

from dataclasses import dataclass


PROJECT_NAME = "agent-learning-compounder"


@dataclass(frozen=True)
class Author:
    name: str
    url: str


@dataclass(frozen=True)
class Repository:
    homepage: str
    readme_homepage: str
    git_url: str
    https_url: str
    issues_url: str


@dataclass(frozen=True)
class ReleaseMetadata:
    name: str
    manifest_version: str
    plugin_version: str
    npm_version: str
    marketplace_version: str
    description: str
    author: Author
    repository: Repository
    keywords: tuple[str, ...]
    marketplace_category: str


RELEASE_METADATA = ReleaseMetadata(
    name=PROJECT_NAME,
    manifest_version="0.1.0",
    plugin_version="0.1.0",
    npm_version="0.1.0",
    marketplace_version="0.1.0",
    description=(
        "Distills repo facts, session telemetry, and skill-health signals into "
        "durable, evidence-backed agent memory. Installs as a Codex skill, a "
        "Claude Code plugin, or both."
    ),
    author=Author(name="Tom", url="https://github.com/beeard"),
    repository=Repository(
        homepage="https://github.com/beeard/agent-learning-compounder",
        readme_homepage="https://github.com/beeard/agent-learning-compounder#readme",
        git_url="git+https://github.com/beeard/agent-learning-compounder.git",
        https_url="https://github.com/beeard/agent-learning-compounder",
        issues_url="https://github.com/beeard/agent-learning-compounder/issues",
    ),
    keywords=(
        "agent-learning",
        "agent-memory",
        "telemetry",
        "mcp",
        "codex",
        "claude-code",
        "skills",
        "hooks",
        "plugin",
    ),
    marketplace_category="workflow",
)
