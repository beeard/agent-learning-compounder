"""Normalize bounded agent-dispatch telemetry.

This module owns the canonical dispatch event shape. Runtime-specific code
should pass raw hook/tool payloads through this module instead of reimplementing
alias mapping or field policy.
"""

from __future__ import annotations

import hashlib
import pathlib
from typing import Any, Callable

from scrub_secrets import scrub


MAX_AGENT_FIELD_LEN = 128
MAX_AGENT_WRITE_SCOPE = 32
MAX_AGENT_WRITE_SCOPE_PATH_LEN = 240

DEFAULT_TELEMETRY_CONFIG = {
    "agent_dispatch": True,
    "agent_dispatch_model": True,
    "agent_dispatch_scope": True,
}


def bounded(value: Any, limit: int = 160) -> str | None:
    if value is None:
        return None
    text = scrub(str(value).replace("\n", " "))
    if "[REDACTED" in text:
        return None
    text = " ".join(text.split())
    return text[:limit] if text else None


def telemetry_config_from_payload(payload: dict[str, Any] | None) -> dict[str, bool]:
    config = dict(DEFAULT_TELEMETRY_CONFIG)
    telemetry = payload.get("telemetry") if isinstance(payload, dict) else None
    if not isinstance(telemetry, dict):
        return config
    for key in config:
        value = telemetry.get(key)
        if isinstance(value, bool):
            config[key] = value
    return config


def _stable_path_token(path: pathlib.Path) -> str:
    token = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]
    return f"<outside_repo:{token}>"


def normalize_path(path_value: Any, repo: pathlib.Path | None) -> str | None:
    if not path_value:
        return None
    path = pathlib.Path(str(path_value)).expanduser()
    if repo and not path.is_absolute():
        path = repo / path
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    if repo:
        try:
            return str(resolved.relative_to(repo.resolve()))
        except ValueError:
            return _stable_path_token(resolved)
    if path.is_absolute():
        return _stable_path_token(resolved)
    return str(path)


def normalize_path_list(paths_value: Any, repo: pathlib.Path | None) -> list[str]:
    if not isinstance(paths_value, list):
        return []
    paths: list[str] = []
    for member in paths_value:
        normalized = normalize_path(member, repo)
        if not normalized:
            continue
        capped = bounded(normalized, MAX_AGENT_WRITE_SCOPE_PATH_LEN)
        if not capped:
            continue
        paths.append(capped)
        if len(paths) >= MAX_AGENT_WRITE_SCOPE:
            break
    return paths


def _nested(raw: dict[str, Any], *keys: str) -> Any:
    value: Any = raw
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def first_present(raw: dict[str, Any], aliases: tuple[str | tuple[str, ...], ...]) -> Any:
    for alias in aliases:
        value = _nested(raw, *alias) if isinstance(alias, tuple) else raw.get(alias)
        if value not in (None, ""):
            return value
    return None


FieldNormalizer = Callable[[Any, pathlib.Path | None], str | list[str] | None]


def _bounded_field(value: Any, repo: pathlib.Path | None) -> str | None:
    del repo
    return bounded(value, MAX_AGENT_FIELD_LEN)


def _bounded_path(value: Any, repo: pathlib.Path | None) -> str | None:
    normalized = normalize_path(value, repo)
    return bounded(normalized, MAX_AGENT_WRITE_SCOPE_PATH_LEN) if normalized else None


def _bounded_path_list(value: Any, repo: pathlib.Path | None) -> list[str]:
    return normalize_path_list(value, repo)


DISPATCH_FIELD_POLICY: tuple[dict[str, Any], ...] = (
    {
        "field": "agent_role",
        "flag": "agent_dispatch",
        "aliases": ("agent_role", "role", "agent_type", ("agent", "role"), ("agent", "type")),
        "normalizer": _bounded_field,
    },
    {
        "field": "agent_backend",
        "flag": "agent_dispatch",
        "aliases": ("agent_backend", "backend", "execution_backend", ("agent", "backend")),
        "normalizer": _bounded_field,
    },
    {
        "field": "agent_id",
        "flag": "agent_dispatch",
        "aliases": ("agent_id", "subagent_id", "worker_id", "child_agent_id", ("agent", "id")),
        "normalizer": _bounded_field,
    },
    {
        "field": "dispatch_id",
        "flag": "agent_dispatch",
        "aliases": ("dispatch_id", "task_id", "job_id", ("task", "id")),
        "normalizer": _bounded_field,
    },
    {
        "field": "agent_mode",
        "flag": "agent_dispatch",
        "aliases": ("agent_mode", "mode", "execution_mode", ("agent", "mode")),
        "normalizer": _bounded_field,
    },
    {
        "field": "parent_correlation_id",
        "flag": "agent_dispatch",
        "aliases": ("parent_correlation_id", "parent_session_id"),
        "normalizer": _bounded_field,
    },
    {
        "field": "agent_model",
        "flag": "agent_dispatch_model",
        "aliases": ("agent_model", "model", "model_id", ("agent", "model")),
        "normalizer": _bounded_field,
    },
    {
        "field": "agent_effort",
        "flag": "agent_dispatch_model",
        "aliases": ("agent_effort", "reasoning_effort", "effort", ("agent", "effort")),
        "normalizer": _bounded_field,
    },
    {
        "field": "agent_sandbox",
        "flag": "agent_dispatch_model",
        "aliases": ("agent_sandbox", "sandbox", ("agent", "sandbox")),
        "normalizer": _bounded_field,
    },
    {
        "field": "agent_write_scope",
        "flag": "agent_dispatch_scope",
        "aliases": ("agent_write_scope", "write_scope", "allowed_write_paths", "allowed_paths", ("task", "write_scope")),
        "normalizer": _bounded_path_list,
    },
    {
        "field": "agent_worktree",
        "flag": "agent_dispatch_scope",
        "aliases": ("agent_worktree", "worktree", ("task", "worktree")),
        "normalizer": _bounded_path,
    },
    {
        "field": "agent_branch",
        "flag": "agent_dispatch_scope",
        "aliases": ("agent_branch", "branch", ("task", "branch")),
        "normalizer": _bounded_field,
    },
)


def normalize_agent_dispatch(
    raw: dict[str, Any],
    repo: pathlib.Path | None,
    telemetry_config: dict[str, bool] | None = None,
) -> dict[str, str | list[str]]:
    telemetry = telemetry_config or DEFAULT_TELEMETRY_CONFIG
    if not telemetry.get("agent_dispatch", True):
        return {}

    normalized: dict[str, str | list[str]] = {}
    for spec in DISPATCH_FIELD_POLICY:
        if not telemetry.get(spec["flag"], True):
            continue
        raw_value = first_present(raw, spec["aliases"])
        value = spec["normalizer"](raw_value, repo)
        if value:
            normalized[spec["field"]] = value
    return normalized
