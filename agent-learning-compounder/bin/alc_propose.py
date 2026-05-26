#!/usr/bin/env python3
"""Write API for proposing outcomes, patches, and agent events."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import secrets
import threading
import time
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
    from state_paths import atomic_rewrite
except ImportError:  # pragma: no cover
    from bin.state_paths import atomic_rewrite


MAX_GATE_TEXT_LEN = 200
MAX_EVIDENCE_LEN = 500
MAX_REASON_LEN = 500
MAX_DOMAIN_LEN = 80
MAX_CATEGORY_LEN = 80
MAX_KIND_LEN = 80
MAX_NAME_LEN = 80
ABSOLUTE_PATH_PREFIXES = ("/home/", "/Users/", "C:\\Users\\", "/etc/")
_EVENT_WRITER_LOCK = threading.RLock()


@contextlib.contextmanager
def _event_writer_state(state: StateHandle):
    previous = os.environ.get("AGENT_LEARNING_STATE_DIR")
    os.environ["AGENT_LEARNING_STATE_DIR"] = str(state.repo_state_dir)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("AGENT_LEARNING_STATE_DIR", None)
        else:
            os.environ["AGENT_LEARNING_STATE_DIR"] = previous


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _require(value: Any, name: str, limit: int = 200) -> str:
    text = bounded(value, limit)
    if not text:
        raise ValueError(f"{name} is required")
    return text


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

    with _EVENT_WRITER_LOCK, _event_writer_state(state):
        return write_event(row, source=source, auto_id_fallback=auto_id_fallback)


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


def propose_gate(state: StateHandle, domain: str, category: str, gate: str, evidence: str | None = None) -> dict[str, str]:
    if not state.repo_state_dir.is_dir():
        raise FileNotFoundError("improvement queue missing; run init_learning_system first")
    domain = _require(domain, "domain", MAX_DOMAIN_LEN)
    category = _require(category, "category", MAX_CATEGORY_LEN)
    gate_text = _require(gate, "gate", MAX_GATE_TEXT_LEN)
    evidence_text = bounded(evidence, MAX_EVIDENCE_LEN) if evidence else ""
    if evidence and evidence_text is None:
        raise ValueError("evidence contains secret-like content")

    digest = hashlib.sha256(f"{domain}|{category}|{gate_text}".encode("utf-8")).hexdigest()[:12]
    queue_id = f"proposed-{digest}-{int(time.time())}"

    row = {
        "id": queue_id,
        "kind": "operator_proposed_gate",
        "domain": domain,
        "category": category,
        "text": gate_text,
        "evidence": evidence_text,
        "ts": _timestamp(),
        "status": "open",
    }

    queue = state.repo_state_dir / "improvement-queue.jsonl"
    _append_jsonl_locked(queue, row)

    event = {
        "event": "gate_proposed",
        "actor": {"kind": "operator", "name": "alc_propose"},
        "ts": _timestamp(),
        "payload": {
            "queue_id": queue_id,
            "domain": domain,
            "category": category,
            "text": gate_text,
        },
    }
    _emit(state, event, source="background")

    return {"queue_id": queue_id}


def propose_apply(state: StateHandle, patch_id: str) -> dict[str, str]:
    patch_id = _require(patch_id, "patch_id", MAX_CATEGORY_LEN)
    token = secrets.token_urlsafe(16)
    command = f"alc_apply --patch-id {patch_id} --approve-token {token}"

    event = {
        "event": "apply_proposed",
        "actor": {"kind": "operator", "name": "alc_propose"},
        "ts": _timestamp(),
        "payload": {
            "patch_id": patch_id,
            "one_shot_token": token,
            "command": command,
        },
    }
    _emit(state, event, source="apply")

    return {"command": command, "token": token}


def report_outcome(state: StateHandle, recommendation_id: str, verdict: str, reason: str) -> str:
    recommendation_id = _require(recommendation_id, "recommendation_id", MAX_REASON_LEN)
    verdict = _require(verdict, "verdict", MAX_REASON_LEN)
    reason_text = _require(reason, "reason", MAX_REASON_LEN)

    key = f"{recommendation_id}:{verdict}:{reason_text}"
    event_id = EventV4.deterministic_id("eval_judge", "outcome_reported", key)
    ts = _timestamp()
    payload = {
        "event_id": event_id,
        "event": "outcome_reported",
        "schema_version": 4,
        "actor": {"kind": "eval_judge", "name": "alc_propose"},
        "telemetry": {},
        "ts": ts,
        "payload": {
            "recommendation_id": recommendation_id,
            "verdict": verdict,
            "reason": reason_text,
        },
    }
    return _emit(state, payload, source="eval", auto_id_fallback=False)


def report_agent_event(state: StateHandle, kind: str, actor_name: str, telemetry: dict[str, Any] | None = None) -> str:
    kind = _require(kind, "kind", MAX_KIND_LEN)
    actor_name = _require(actor_name, "actor_name", MAX_NAME_LEN)
    payload = {
        "event": f"agent_dispatch_{kind}",
        "actor": {"kind": "mcp_server", "name": actor_name},
        "ts": _timestamp(),
        "telemetry": _safe_telemetry(dict(telemetry or {})),
    }
    return _emit(state, payload, source="background")


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

    event = {
        "event": f"patch_{status}",
        "actor": {"kind": "operator", "name": "alc_propose"},
        "ts": _timestamp(),
        "payload": {
            "patch_id": patch_id,
            "status": status,
        },
    }
    _emit(state, event, source="apply")
    return {"patch_id": patch_id, "status": status}
