#!/usr/bin/env python3
"""Write API for proposing outcomes, patches, and agent events."""

from __future__ import annotations

import json
import os
import secrets
import threading
from pathlib import Path
from typing import Any, Literal
import fcntl

from scrub_secrets import scrub

try:
    from state_handle import StateHandle
except ImportError:  # pragma: no cover
    from bin.state_handle import StateHandle

try:
    from collect_hook_event import assert_regular_file_destination
except ImportError:  # pragma: no cover
    from bin.collect_hook_event import assert_regular_file_destination

try:
    from agent_dispatch import bounded
except ImportError:  # pragma: no cover
    from bin.agent_dispatch import bounded

try:
    from event_writer import write_event, EventV4
except ImportError:  # pragma: no cover
    from bin.event_writer import write_event, EventV4

try:
    from state_handle import atomic_rewrite
except ImportError:  # pragma: no cover
    from bin.state_handle import atomic_rewrite

try:
    import proposal_lifecycle
    import index_events
except ImportError:  # pragma: no cover
    from bin import proposal_lifecycle
    from bin import index_events


MAX_GATE_TEXT_LEN = proposal_lifecycle.MAX_GATE_TEXT_LEN
MAX_EVIDENCE_LEN = proposal_lifecycle.MAX_EVIDENCE_LEN
MAX_REASON_LEN = proposal_lifecycle.MAX_REASON_LEN
MAX_DOMAIN_LEN = proposal_lifecycle.MAX_DOMAIN_LEN
MAX_CATEGORY_LEN = proposal_lifecycle.MAX_CATEGORY_LEN
MAX_KIND_LEN = proposal_lifecycle.MAX_KIND_LEN
MAX_NAME_LEN = proposal_lifecycle.MAX_NAME_LEN
ABSOLUTE_PATH_PREFIXES = ("/home/", "/Users/", "C:\\Users\\", "/etc/")
_EVENT_WRITER_LOCK = threading.RLock()


def _timestamp() -> str:
    return proposal_lifecycle.timestamp()


def _require(value: Any, name: str, limit: int = 200) -> str:
    return proposal_lifecycle.require_text(value, name, limit)


def _emit(state: StateHandle, row: dict[str, Any], *, source: str, auto_id_fallback: bool = True) -> str:
    row = dict(row)
    for key, value in list(row.items()):
        if isinstance(value, str):
            row[key] = bounded(value)
            if row[key] is None:
                raise ValueError(f"{key} rejected during bounded/scrub")
    row["schema_version"] = row.get("schema_version", 4)
    row["telemetry"] = row.get("telemetry", {})
    row.setdefault("actor", {"kind": row.get("actor", {}).get("kind", "operator"), "name": "alc_propose"})

    # Enforce explicit secret boundary before passing to event_writer.
    payload = scrub(json.dumps(row, sort_keys=True, separators=(",", ":")))
    if "[REDACTED" in payload:
        raise ValueError("payload contained secret-like content")

    with _EVENT_WRITER_LOCK:
        return write_event(row, source=source, auto_id_fallback=auto_id_fallback, state=state)


def _safe_telemetry(value: Any) -> Any:
    if isinstance(value, str):
        return "<path>" if value.startswith(ABSOLUTE_PATH_PREFIXES) else value
    if isinstance(value, list):
        return [_safe_telemetry(member) for member in value]
    if isinstance(value, dict):
        return {key: _safe_telemetry(member) for key, member in value.items()}
    return value


def _append_jsonl_locked(path: Path, row: dict[str, Any]) -> None:
    rendered = json.dumps(row, sort_keys=True, separators=(",", ":"))
    path.parent.mkdir(parents=True, exist_ok=True)
    assert_regular_file_destination(path, label="improvement queue")
    lock_path = path.with_suffix(path.suffix + ".lock")
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        with os.fdopen(fd, "a", encoding="utf-8") as lock_handle:
            fcntl.flock(lock_handle, fcntl.LOCK_EX)
            with path.open("a", encoding="utf-8") as queue_handle:
                queue_handle.write(rendered + "\n")
                queue_handle.flush()
                os.fsync(queue_handle.fileno())
    finally:
        pass


def refresh_write_visibility(state: StateHandle) -> dict[str, Any]:
    """Bounded post-write refresh so query/dashboard reads see new events."""
    try:
        indexed = index_events.run(state.repo_state_dir)
        return {"updated": True, "indexed_events": indexed}
    except Exception as error:  # noqa: BLE001 - writes should remain durable if indexing degrades.
        return {"updated": False, "indexed_events": 0, "error": str(error)}


def propose_gate(state: StateHandle, domain: str, category: str, gate: str, evidence: str | None = None) -> dict[str, str]:
    if not state.repo_state_dir.is_dir():
        raise FileNotFoundError("improvement queue missing; run init_learning_system first")
    proposal = proposal_lifecycle.build_gate_proposal(
        domain=domain,
        category=category,
        gate=gate,
        evidence=evidence,
    )

    queue = state.repo_state_dir / "improvement-queue.jsonl"
    _append_jsonl_locked(queue, proposal.queue_row)
    _emit(state, proposal.event, source="background")

    return {"queue_id": proposal.queue_id, "visibility": refresh_write_visibility(state)}


def propose_apply(state: StateHandle, patch_id: str) -> dict[str, str]:
    # Command matches the actual alc_apply CLI surface (--patch + --write).
    # An audit nonce is emitted only in the apply_proposed event payload so a
    # future correlator can pair a proposal with the eventual apply via
    # event_id chain — but it is NOT returned to MCP callers, because alc_apply
    # has no token-validation surface and exposing a "token" would suggest a
    # security guarantee that doesn't exist (see PR review round 2).
    audit_nonce = secrets.token_urlsafe(16)
    proposal = proposal_lifecycle.build_apply_proposal(patch_id=patch_id, audit_nonce=audit_nonce)
    _emit(state, proposal.event, source="apply")
    return {"command": proposal.command, "visibility": refresh_write_visibility(state)}


def report_outcome(state: StateHandle, recommendation_id: str, verdict: str, reason: str) -> str:
    payload = proposal_lifecycle.build_outcome_event(
        recommendation_id=recommendation_id,
        verdict=verdict,
        reason=reason,
    )
    event_id = _emit(state, payload, source="eval", auto_id_fallback=False)
    refresh_write_visibility(state)
    return event_id


def report_agent_event(state: StateHandle, kind: str, actor_name: str, telemetry: dict[str, Any] | None = None) -> str:
    payload = proposal_lifecycle.build_agent_event(
        kind=kind,
        actor_name=actor_name,
        telemetry=_safe_telemetry(dict(telemetry or {})),
    )
    event_id = _emit(state, payload, source="background")
    refresh_write_visibility(state)
    return event_id


def mark_patch_status(state: StateHandle, patch_id: str, status: Literal["deferred", "rejected"]) -> dict[str, str]:
    if status not in {"deferred", "rejected"}:
        raise ValueError("status must be 'deferred' or 'rejected'")
    patch_id = _require(patch_id, "patch_id", MAX_CATEGORY_LEN)
    path = state.repo_state_dir / "patches" / f"{patch_id}.json"
    assert_regular_file_destination(path, label="patch bundle")

    try:
        with atomic_rewrite(path) as (current, commit):
            data = json.loads(current) if current else {}
            if not isinstance(data, dict):
                raise ValueError("patch bundle must be an object")
            data["status"] = status
            data["status_updated_at"] = _timestamp()
            commit(json.dumps(data, sort_keys=True, separators=(",", ":")))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"patch bundle not found: {path}") from exc

    event = proposal_lifecycle.build_patch_status_event(patch_id=patch_id, status=status)
    _emit(state, event, source="apply")
    return {"patch_id": patch_id, "status": status, "visibility": refresh_write_visibility(state)}
