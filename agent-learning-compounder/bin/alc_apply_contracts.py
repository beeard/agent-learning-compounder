#!/usr/bin/env python3
"""Shared contracts for the U11 alc_apply CLI.

This file intentionally contains only interface contracts + validators. The
executor implementation belongs to W9b.
"""

from __future__ import annotations

import abc
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None


try:
    from . import recommender_generators
except ImportError:  # pragma: no cover
    import recommender_generators


GENERATORS = recommender_generators.GENERATORS


def _word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text))


def _strip_code_blocks(text: str) -> str:
    return re.sub(r"(?ms)^```.*?^```\\s*$", "", text)


def _read_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    if not content.startswith("---"):
        return {}, content
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content
    front = parts[1].strip()
    body = parts[2]
    if yaml is not None:
        loaded = yaml.safe_load(front) or {}
        if isinstance(loaded, dict):
            return {str(k): v for k, v in loaded.items()}, body
    parsed: dict[str, Any] = {}
    lines = front.splitlines()
    idx = 0
    while idx < len(lines):
        raw = lines[idx]
        if ":" not in raw:
            idx += 1
            continue
        key, value = raw.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not value:
            idx += 1
            block: list[str] = []
            while idx < len(lines) and (lines[idx].startswith("  ") or lines[idx].startswith("\t")):
                block.append(lines[idx].strip())
                idx += 1
            parsed[key] = "\n".join(block)
            continue
        parsed[key] = value.strip().strip("\"'")
        idx += 1
    return parsed, body


def _validate_required_frontmatter(frontmatter: dict[str, Any], errors: list[str]) -> None:
    name = str(frontmatter.get("name", "")).strip()
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,49}", name):
        errors.append("name must match ^[a-z][a-z0-9-]{2,49}$")
    description = str(frontmatter.get("description", "")).strip()
    if not description:
        errors.append("description is required")


AGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{2,49}$")
ALLOWED_COLORS = {"blue", "cyan", "green", "yellow", "red", "magenta"}
ALLOWED_MODELS = {"inherit", "sonnet", "haiku", "opus"}


def _section_present(body: str, heading: str) -> bool:
    return bool(re.search(rf"(?im)^\s*#+\s*{re.escape(heading)}\b", body))


def validate_agent_frontmatter(content: str) -> list[str]:
    errors: list[str] = []
    frontmatter, body = _read_frontmatter(content)
    _validate_required_frontmatter(frontmatter, errors)
    name = str(frontmatter.get("name", "")).strip().lower()
    if name.startswith("helper") or name.startswith("assistant") or name.startswith("agent-"):
        errors.append("avoid generic names like helper/assistant/agent- prefix")
    if not AGENT_NAME_RE.fullmatch(name):
        # keep the error explicit for the unit tests that expect a regex mismatch style
        if not any(e for e in errors if "must match" in e):
            pass
    description = str(frontmatter.get("description", "")).strip()
    if not description.startswith("Use this agent when"):
        errors.append("description must start with 'Use this agent when'")
    example_count = len(re.findall(r"<example>", description, flags=re.IGNORECASE))
    if example_count < 2:
        errors.append("examples must satisfy min 2")
    if example_count > 4:
        errors.append("examples must satisfy max 4")
    color = str(frontmatter.get("color", "")).strip()
    if color not in ALLOWED_COLORS:
        errors.append("color must be one of blue, cyan, green, yellow, red, magenta")
    model = str(frontmatter.get("model", "inherit")).strip() or "inherit"
    if model not in ALLOWED_MODELS:
        errors.append("model must be inherit, sonnet, haiku, or opus")
    plain_body = _strip_code_blocks(body)
    words = _word_count(plain_body)
    if words < 500:
        errors.append("body has min 500 words")
    if words > 3000:
        errors.append("body exceeds max 3000 words")
    for section in ("Role", "Responsibilities", "Process", "Output"):
        if not _section_present(plain_body, section):
            errors.append(f"missing required section: {section}")
    return errors


def validate_skill_frontmatter(content: str) -> list[str]:
    errors: list[str] = []
    frontmatter, _ = _read_frontmatter(content)
    _validate_required_frontmatter(frontmatter, errors)
    if len(str(frontmatter.get("description", ""))) > 1024:
        errors.append("description must be <= 1024 characters")
    return errors


Validator = Callable[[str], list[str]]


@dataclass(frozen=True)
class TargetSpec:
    allowed_roots: list[str]
    max_size: int
    validator: Validator | None = None


DSL_TARGETS: dict[str, TargetSpec] = {
    "skill": TargetSpec(["skills/", "~/.hermes/skills/"], max_size=100_000, validator=validate_skill_frontmatter),
    "agent": TargetSpec(["agents/", "<state>/alc-agents/{dev,test,evals}/", "<personal>/alc-agents/"], max_size=30_000, validator=validate_agent_frontmatter),
    "command": TargetSpec(["commands/"], max_size=10_000, validator=None),
    "hook": TargetSpec(["hooks/"], max_size=10_000, validator=None),
}


@dataclass(frozen=True)
class ApplyResult:
    success: bool
    patch_id: str
    target: str
    sha256_before: str
    sha256_after: str
    event_id: str
    error: str | None = None


@dataclass(frozen=True)
class RevertResult:
    success: bool
    patch_id: str
    target: str
    sha256_before: str
    sha256_after: str
    event_id: str
    error: str | None = None


class ApplyError(RuntimeError):
    """Raised when apply preflight or write execution cannot proceed."""


class RevertError(RuntimeError):
    """Raised when revert preflight or write execution cannot proceed."""


class Executor(abc.ABC):
    @abc.abstractmethod
    def apply(self, op: dict[str, Any]) -> ApplyResult:
        raise NotImplementedError

    @abc.abstractmethod
    def revert(self, patch_id: str) -> RevertResult:
        raise NotImplementedError


def _extract_generator_target_types() -> set[str]:
    target_types: set[str] = set()
    fallback_map = {
        "anomaly_investigate": "skill",
        "skill_routing_review": "skill",
        "model_swap_candidate": "agent",
        "agent_spawn_suggestion": "agent",
        "workflow_chain": None,
    }
    for spec in GENERATORS.values():
        target_type: str | None = None
        output = getattr(spec, "output", None)
        if output is not None:
            if isinstance(output, dict):
                candidate = output.get("target_type")
            else:
                candidate = getattr(output, "target_type", None)
            if isinstance(candidate, str):
                target_type = candidate
        if target_type is None and isinstance(spec, dict):
            kind = spec.get("kind")
            if kind in fallback_map:
                target_type = fallback_map[kind]
        if target_type:
            target_types.add(target_type)
    return target_types


def _validate_generators_subset() -> None:
    missing = _extract_generator_target_types() - set(DSL_TARGETS)
    if missing:
        target = sorted(missing)[0]
        raise ImportError(f"U9 emits target_type={target} not registered in DSL_TARGETS")


def main(argv: list[str] | None = None) -> int:
    _validate_generators_subset()
    return 0


_validate_generators_subset()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
