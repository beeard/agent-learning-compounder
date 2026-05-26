#!/usr/bin/env python3
"""Canonical state resolver for agent-learning.

`StateHandle` is the single source of truth for mapping a repo path to all
primary on-disk locations used by ALC.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import re
from dataclasses import dataclass
from typing import Literal


logger = logging.getLogger(__name__)


def _slugify(value: str, fallback: str = "repo") -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-").lower()
    return slug or fallback


def _repo_id(repo: pathlib.Path) -> str:
    resolved = str(repo.expanduser().resolve())
    import hashlib

    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:12]
    return f"{_slugify(pathlib.Path(resolved).name)}-{digest}"


def _read_json_or_none(path: pathlib.Path) -> dict | None:
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _resolve_state_root(
    state_dir: str | pathlib.Path | None = None,
    personal: str | pathlib.Path | None = None,
    repo: str | pathlib.Path | None = None,
) -> tuple[pathlib.Path, str]:
    """Resolve `state_root` using the legacy precedence chain.

    Resolution order:
      1. explicit state_dir argument
      2. AGENT_LEARNING_STATE_DIR env
      3. explicit personal argument
      4. repo/.agent-learning
      5. $XDG_STATE_HOME/agent-learning
      6. ~/.local/state/agent-learning
    """
    if state_dir:
        return pathlib.Path(state_dir).expanduser().resolve(), "legacy_explicit_state_dir"

    env_state = os.environ.get("AGENT_LEARNING_STATE_DIR")
    if env_state:
        return pathlib.Path(env_state).expanduser().resolve(), "legacy_env_state_dir"

    if personal:
        return pathlib.Path(personal).expanduser().resolve() / "reports" / "agent-learning", "legacy_personal"

    if repo is not None:
        return pathlib.Path(repo).expanduser().resolve() / ".agent-learning", "legacy_repo_root"

    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return pathlib.Path(xdg).expanduser().resolve() / "agent-learning", "legacy_xdg"

    return pathlib.Path.home() / ".local" / "state" / "agent-learning", "legacy_home"


def _resolve_repo_state_dir(
    repo: str | pathlib.Path,
    state_dir: str | pathlib.Path | None = None,
    personal: str | pathlib.Path | None = None,
) -> tuple[pathlib.Path, str]:
    resolved, tier = _resolve_state_root(state_dir, personal, repo)
    return resolved / "repos" / _repo_id(pathlib.Path(repo)), tier


def _load_state_root_from_repo_config(repo: pathlib.Path) -> pathlib.Path | None:
    payload = _read_json_or_none(repo / ".agent-learning.json")
    if not payload:
        return None
    state_dir = payload.get("state_dir")
    if not isinstance(state_dir, str) or not state_dir.strip():
        return None

    return pathlib.Path(state_dir).expanduser().resolve()


@dataclass(frozen=True)
class StateHandle:
    """Canonical resolver for a repo-local state surface."""

    repo: pathlib.Path
    state_root: pathlib.Path
    repo_state_dir: pathlib.Path
    reports_dir: pathlib.Path
    dashboard_dir: pathlib.Path
    alc_agents_dirs: dict[Literal["dev", "test", "evals", "personal"], pathlib.Path]
    alc_apply_log: pathlib.Path
    outcomes_json: pathlib.Path
    events_jsonl: pathlib.Path
    events_sqlite: pathlib.Path

    @staticmethod
    def repo_id(repo: pathlib.Path) -> str:
        return _repo_id(repo)

    @staticmethod
    def resolve_state_root(
        state_dir: str | pathlib.Path | None = None,
        personal: str | pathlib.Path | None = None,
        repo: str | pathlib.Path | None = None,
    ) -> tuple[pathlib.Path, str]:
        return _resolve_state_root(state_dir, personal, repo)

    @staticmethod
    def resolve_repo_state_dir(
        repo: str | pathlib.Path,
        state_dir: str | pathlib.Path | None = None,
        personal: str | pathlib.Path | None = None,
    ) -> tuple[pathlib.Path, str]:
        return _resolve_repo_state_dir(repo, state_dir, personal)

    @classmethod
    def for_repo(cls, repo_path: pathlib.Path) -> "StateHandle":
        repo = pathlib.Path(repo_path).expanduser().resolve()

        state_root = _load_state_root_from_repo_config(repo)
        tier = "repo_config_state_dir" if state_root is not None else None

        if state_root is None:
            state_root, tier = _resolve_state_root(repo=repo)

        logger.info("state_handle_state_root_resolved", extra={"repo": str(repo), "tier": tier})

        repo_state = state_root / "repos" / cls.repo_id(repo)
        reports_dir = repo_state / "reports"
        dashboard_dir = repo_state / "dashboard"
        alc_agents_root = repo_state / "alc-agents"

        return cls(
            repo=repo,
            state_root=state_root,
            repo_state_dir=repo_state,
            reports_dir=reports_dir,
            dashboard_dir=dashboard_dir,
            alc_agents_dirs={
                "dev": alc_agents_root / "dev",
                "test": alc_agents_root / "test",
                "evals": alc_agents_root / "evals",
                "personal": state_root / "alc-agents" / "personal",
            },
            alc_apply_log=repo_state / "apply-log.jsonl",
            outcomes_json=repo_state / "outcomes.json",
            events_jsonl=repo_state / "events.jsonl",
            events_sqlite=repo_state / "events.sqlite",
        )


def dashboard_url(repo: str | pathlib.Path) -> str:
    handle = StateHandle.for_repo(pathlib.Path(repo))
    marker = handle.dashboard_dir / "server.json"
    payload = _read_json_or_none(marker)
    if payload:
        url = payload.get("url")
        if isinstance(url, str) and url.startswith(("http://127.0.0.1:", "http://localhost:")):
            return url
    index = handle.dashboard_dir / "index.html"
    return index.resolve().as_uri() if index.exists() else handle.dashboard_dir.resolve().as_uri()
