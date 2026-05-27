#!/usr/bin/env python3
"""Registry-backed artifact writer for U6.

`write_artifact(artifact_id, payload, state_handle)` enforces:
- artifact exists in merged contracts
- template path is valid and state-local
- payload serialization format
- max-size contract
"""

from __future__ import annotations

import json
import os
import pathlib
import re
from collections.abc import Mapping
from typing import Any

from state_handle import atomic_write_text

WILDCARD_RE = re.compile(r"[\\*\\?\[]")

REQUIRED_FIELDS = {
    "id",
    "path_template",
    "producer",
    "consumers",
    "surface_in_dashboard",
    "format",
    "lifecycle",
}
REQUIRED_LIFECYCLE_FIELDS = {
    "create",
    "read",
    "update",
    "delete_or_retention",
    "owner",
    "states",
    "max_age",
    "max_count",
    "cleanup_command",
}


def contracts_dir() -> pathlib.Path:
    override = os.environ.get("ALC_DATA_CONTRACTS_DIR")
    root = pathlib.Path(__file__).resolve().parents[1]
    return pathlib.Path(override) if override else root / "data-contracts"


def _read_json(path: pathlib.Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"invalid contract format in {path}; expected object")
    return payload


def _iter_contract_files(base: pathlib.Path) -> list[pathlib.Path]:
    contract_file = base / "base.json"
    if not contract_file.exists():
        raise FileNotFoundError(f"missing base contracts: {contract_file}")
    manifests = base / "manifests"
    files = [contract_file]
    if manifests.exists():
        files.extend(sorted(manifests.glob("*.json")))
    return files


def _validate_entry(entry: Mapping[str, Any], source: pathlib.Path) -> None:
    missing = REQUIRED_FIELDS.difference(entry.keys())
    if missing:
        raise ValueError(f"malformed contract entry in {source}: missing fields {sorted(missing)}")
    if not isinstance(entry["id"], str) or not entry["id"].strip():
        raise ValueError(f"malformed contract entry in {source}: id must be non-empty string")
    if not isinstance(entry["path_template"], str) or not entry["path_template"].strip():
        raise ValueError(f"malformed contract entry in {source}: path_template must be non-empty string")
    if not isinstance(entry["producer"], str) or not entry["producer"].strip():
        raise ValueError(f"malformed contract entry in {source}: producer must be non-empty string")
    if not isinstance(entry["consumers"], list) or not all(isinstance(item, str) for item in entry["consumers"]):
        raise ValueError(f"malformed contract entry in {source}: consumers must be list[str]")
    if not isinstance(entry["surface_in_dashboard"], bool):
        raise ValueError(f"malformed contract entry in {source}: surface_in_dashboard must be bool")
    if not isinstance(entry["format"], str) or not entry["format"].strip():
        raise ValueError(f"malformed contract entry in {source}: format must be non-empty string")
    if not isinstance(entry["lifecycle"], Mapping):
        raise ValueError(f"malformed contract entry in {source}: lifecycle must be object")
    missing_lifecycle = REQUIRED_LIFECYCLE_FIELDS.difference(entry["lifecycle"].keys())
    if missing_lifecycle:
        raise ValueError(
            f"malformed contract entry in {source}: lifecycle missing {sorted(missing_lifecycle)}"
        )
    max_size = entry.get("max_size")
    if max_size is not None and not isinstance(max_size, int):
        raise ValueError(f"malformed contract entry in {source}: max_size must be int")


def load_contracts(base_dir: pathlib.Path | None = None) -> list[dict[str, Any]]:
    root = base_dir or contracts_dir()
    contracts: list[dict[str, Any]] = []
    for path in _iter_contract_files(root):
        data = _read_json(path)
        artifacts = data.get("artifacts")
        if not isinstance(artifacts, list):
            raise ValueError(f"invalid contract payload in {path}; expected 'artifacts' list")
        for index, entry in enumerate(artifacts):
            if not isinstance(entry, Mapping):
                raise ValueError(f"invalid artifact entry in {path}[{index}]")
            _validate_entry(entry, path)
            normalized = dict(entry)
            normalized["_source"] = str(path)
            contracts.append(normalized)
    return contracts


def merged_registry(base_dir: pathlib.Path | None = None) -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for entry in load_contracts(base_dir):
        artifact_id = str(entry["id"]).strip()
        if artifact_id in seen:
            raise ValueError(f"artifact_id '{artifact_id}' declared multiple times")
        seen.add(artifact_id)
        normalized = dict(entry)
        normalized.pop("_source", None)
        registry[artifact_id] = normalized
    return registry


def registrations(base_dir: pathlib.Path | None = None) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for entry in load_contracts(base_dir):
        artifact_id = str(entry["id"]).strip()
        grouped.setdefault(artifact_id, []).append(str(entry["_source"]))
    return grouped


_REGISTRY = merged_registry()


def _state_root(state_handle: Any) -> pathlib.Path:
    if isinstance(state_handle, (str, os.PathLike)):
        return pathlib.Path(state_handle).expanduser().resolve()
    if hasattr(state_handle, "repo_state_dir"):
        value = state_handle.repo_state_dir
        if callable(value):
            value = value()
        if value:
            return pathlib.Path(value).expanduser().resolve()
    if hasattr(state_handle, "state_root"):
        value = state_handle.state_root
        if callable(value):
            value = value()
        if value:
            return pathlib.Path(value).expanduser().resolve()
    if hasattr(state_handle, "state_dir"):
        value = state_handle.state_dir
        if callable(value):
            value = value()
        if value:
            return pathlib.Path(value).expanduser().resolve()
    if hasattr(state_handle, "repo_state"):
        value = state_handle.repo_state
        if callable(value):
            value = value()
        if value:
            return pathlib.Path(value).expanduser().resolve()
    raise TypeError("state_handle must provide repo_state_dir, state_root, state_dir, or repo_state")


def _resolve_template(template: str, state_root: pathlib.Path, state_handle: Any) -> str:
    values = {
        "state_dir": str(state_root),
        "repo_state": str(state_root),
        "repo_state_dir": str(state_root),
    }
    if hasattr(state_handle, "repo_id"):
        try:
            values["repo_id"] = str(state_handle.repo_id)
        except Exception:
            pass
    if hasattr(state_handle, "repo"):
        repo = state_handle.repo
        if callable(repo):
            repo = repo()
        if repo is not None:
            values["repo"] = str(repo)
    try:
        return template.format(**values)
    except KeyError as error:
        raise ValueError(f"unsupported template variable in path-template: {error.args[0]}") from None


def _artifact_path(artifact_id: str, state_handle: Any) -> pathlib.Path:
    if artifact_id not in _REGISTRY:
        raise KeyError(f"artifact '{artifact_id}' is not registered")

    template = _REGISTRY[artifact_id]["path_template"].strip()
    if WILDCARD_RE.search(template):
        raise ValueError(f"artifact '{artifact_id}' has wildcard path-template; cannot be resolved")

    state_root = _state_root(state_handle)
    rendered = _resolve_template(template, state_root, state_handle)
    path = pathlib.Path(rendered)
    if not path.is_absolute():
        path = state_root / path

    try:
        path = path.resolve()
        path.relative_to(state_root)
    except ValueError as error:
        raise ValueError(f"artifact '{artifact_id}' writes outside state dir: {path}") from error
    return path


def _serialize_json(payload: Any, artifact_id: str) -> str:
    if not isinstance(payload, (dict, list)):
        raise ValueError(f"artifact '{artifact_id}' json payload must be dict or list")
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _serialize_jsonl(payload: Any, artifact_id: str) -> str:
    if isinstance(payload, str):
        text = payload
        if text and not text.endswith("\n"):
            text += "\n"
        return text
    if isinstance(payload, dict):
        return json.dumps(payload, sort_keys=True) + "\n"
    if isinstance(payload, list):
        lines: list[str] = []
        for index, row in enumerate(payload):
            try:
                lines.append(json.dumps(row, sort_keys=True))
            except TypeError as exc:
                raise ValueError(f"artifact '{artifact_id}' jsonl payload[{index}] must be JSON-serializable") from exc
        return "\n".join(lines) + ("\n" if lines else "")
    raise ValueError(f"artifact '{artifact_id}' jsonl payload must be dict, list, or str")


def _serialize_markdown(payload: Any, artifact_id: str) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, list) and all(isinstance(item, str) for item in payload):
        return "\n".join(payload) + ("\n" if payload else "")
    raise ValueError(f"artifact '{artifact_id}' markdown payload must be str")


def _serialize_text(payload: Any, artifact_id: str) -> str:
    if not isinstance(payload, str):
        raise ValueError(f"artifact '{artifact_id}' text payload must be str")
    return payload


def _serialize(artifact_id: str, payload: Any) -> str:
    format_name = _REGISTRY[artifact_id]["format"]
    if format_name == "json":
        return _serialize_json(payload, artifact_id)
    if format_name == "jsonl":
        return _serialize_jsonl(payload, artifact_id)
    if format_name == "markdown":
        return _serialize_markdown(payload, artifact_id)
    if format_name == "text":
        return _serialize_text(payload, artifact_id)
    raise ValueError(f"unsupported artifact format '{format_name}' for {artifact_id}")


def write_artifact(artifact_id: str, payload: Any, state_handle: Any) -> pathlib.Path:
    path = _artifact_path(artifact_id, state_handle)
    rendered = _serialize(artifact_id, payload)
    max_size = _REGISTRY[artifact_id].get("max_size")
    if max_size is not None and len(rendered.encode("utf-8")) > max_size:
        raise ValueError(f"artifact '{artifact_id}' exceeds max_size {max_size}")

    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, rendered)
    return path


if __name__ == "__main__":
    raise SystemExit("artifact_writer is a library; call write_artifact directly")
