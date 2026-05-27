#!/usr/bin/env python3
"""Shared proposal lifecycle records and read helpers."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Literal

try:
    from agent_dispatch import bounded
except ImportError:  # pragma: no cover
    from bin.agent_dispatch import bounded

try:
    from state_handle import StateHandle
except ImportError:  # pragma: no cover
    from bin.state_handle import StateHandle

try:
    from event_writer import EventV4
except ImportError:  # pragma: no cover
    from bin.event_writer import EventV4


MAX_GATE_TEXT_LEN = 200
MAX_EVIDENCE_LEN = 500
MAX_REASON_LEN = 500
MAX_DOMAIN_LEN = 80
MAX_CATEGORY_LEN = 80
MAX_KIND_LEN = 80
MAX_NAME_LEN = 80

PatchStatus = Literal["deferred", "rejected"]


@dataclass(frozen=True)
class GateProposal:
    queue_id: str
    queue_row: dict[str, Any]
    record: dict[str, Any]
    event: dict[str, Any]


@dataclass(frozen=True)
class ApplyProposal:
    patch_id: str
    command: str
    record: dict[str, Any]
    event: dict[str, Any]


def timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def require_text(value: Any, name: str, limit: int = 200) -> str:
    text = bounded(value, limit)
    if not text:
        raise ValueError(f"{name} is required")
    return text


def optional_text(value: Any, limit: int) -> str:
    if value is None or value == "":
        return ""
    text = bounded(value, limit)
    if text is None:
        raise ValueError("value contains secret-like content")
    return text


def proposal_id(kind: str, *parts: Any, suffix: str | int | None = None) -> str:
    body = "|".join(str(part) for part in parts)
    digest = hashlib.sha256(f"{kind}|{body}".encode("utf-8")).hexdigest()[:12]
    if suffix is None:
        return f"{kind}-{digest}"
    return f"{kind}-{digest}-{suffix}"


def lifecycle_ref(
    *,
    proposal_kind: str,
    status: str,
    artifact_id: str,
    ts: str,
    recommendation_id: str | None = None,
    artifact_type: str | None = None,
    event_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "proposal_kind": proposal_kind,
        "status": status,
        "artifact_id": artifact_id,
        "ts": ts,
    }
    if recommendation_id:
        record["recommendation_id"] = recommendation_id
    if artifact_type:
        record["artifact_type"] = artifact_type
    if event_id:
        record["event_id"] = event_id
    if metadata:
        record["metadata"] = json_safe(metadata)
    return record


def build_gate_proposal(
    *,
    domain: str,
    category: str,
    gate: str,
    evidence: str | None = None,
    now: str | None = None,
    epoch_seconds: int | None = None,
) -> GateProposal:
    domain_text = require_text(domain, "domain", MAX_DOMAIN_LEN)
    category_text = require_text(category, "category", MAX_CATEGORY_LEN)
    gate_text = require_text(gate, "gate", MAX_GATE_TEXT_LEN)
    evidence_text = optional_text(evidence, MAX_EVIDENCE_LEN)
    ts = now or timestamp()
    suffix = int(time.time()) if epoch_seconds is None else int(epoch_seconds)
    queue_id = proposal_id("proposed", domain_text, category_text, gate_text, suffix=suffix)

    row = {
        "id": queue_id,
        "kind": "operator_proposed_gate",
        "domain": domain_text,
        "category": category_text,
        "text": gate_text,
        "evidence": evidence_text,
        "ts": ts,
        "status": "open",
    }
    record = lifecycle_ref(
        proposal_kind="gate",
        status="queued",
        artifact_id=queue_id,
        artifact_type="improvement_queue",
        ts=ts,
        metadata={"domain": domain_text, "category": category_text},
    )
    event = {
        "event": "gate_proposed",
        "actor": {"kind": "operator", "name": "alc_propose"},
        "ts": ts,
        "payload": {
            "queue_id": queue_id,
            "domain": domain_text,
            "category": category_text,
            "text": gate_text,
            "lifecycle": record,
        },
    }
    return GateProposal(queue_id=queue_id, queue_row=row, record=record, event=event)


def build_apply_proposal(
    *,
    patch_id: str,
    audit_nonce: str,
    now: str | None = None,
) -> ApplyProposal:
    patch = require_text(patch_id, "patch_id", MAX_CATEGORY_LEN)
    ts = now or timestamp()
    command = f"bin/alc_apply --patch {patch} --write"
    record = lifecycle_ref(
        proposal_kind="apply",
        status="proposed",
        artifact_id=patch,
        artifact_type="patch",
        ts=ts,
    )
    event = {
        "event": "apply_proposed",
        "actor": {"kind": "operator", "name": "alc_propose"},
        "ts": ts,
        "payload": {
            "patch_id": patch,
            "audit_nonce": audit_nonce,
            "command": command,
            "lifecycle": record,
        },
    }
    return ApplyProposal(patch_id=patch, command=command, record=record, event=event)


def build_outcome_event(
    *,
    recommendation_id: str,
    verdict: str,
    reason: str,
    now: str | None = None,
) -> dict[str, Any]:
    rec = require_text(recommendation_id, "recommendation_id", MAX_REASON_LEN)
    verdict_text = require_text(verdict, "verdict", MAX_REASON_LEN)
    reason_text = require_text(reason, "reason", MAX_REASON_LEN)
    key = f"{rec}:{verdict_text}:{reason_text}"
    event_id = EventV4.deterministic_id("eval_judge", "outcome_reported", key)
    ts = now or timestamp()
    record = lifecycle_ref(
        proposal_kind="outcome",
        status="reported",
        artifact_id=rec,
        artifact_type="recommendation",
        recommendation_id=rec,
        event_id=event_id,
        ts=ts,
    )
    return {
        "event_id": event_id,
        "event": "outcome_reported",
        "schema_version": 4,
        "actor": {"kind": "eval_judge", "name": "alc_propose"},
        "telemetry": {},
        "ts": ts,
        "payload": {
            "recommendation_id": rec,
            "verdict": verdict_text,
            "reason": reason_text,
            "lifecycle": record,
        },
    }


def build_agent_event(
    *,
    kind: str,
    actor_name: str,
    telemetry: dict[str, Any],
    now: str | None = None,
) -> dict[str, Any]:
    kind_text = require_text(kind, "kind", MAX_KIND_LEN)
    actor = require_text(actor_name, "actor_name", MAX_NAME_LEN)
    ts = now or timestamp()
    record = lifecycle_ref(
        proposal_kind="agent_event",
        status="reported",
        artifact_id=f"agent_dispatch_{kind_text}",
        artifact_type="event",
        ts=ts,
    )
    return {
        "event": f"agent_dispatch_{kind_text}",
        "actor": {"kind": "mcp_server", "name": actor},
        "ts": ts,
        "telemetry": json_safe(telemetry),
        "payload": {"lifecycle": record},
    }


def build_patch_status_event(*, patch_id: str, status: PatchStatus, now: str | None = None) -> dict[str, Any]:
    if status not in {"deferred", "rejected"}:
        raise ValueError("status must be 'deferred' or 'rejected'")
    patch = require_text(patch_id, "patch_id", MAX_CATEGORY_LEN)
    ts = now or timestamp()
    record = lifecycle_ref(
        proposal_kind="patch_status",
        status=status,
        artifact_id=patch,
        artifact_type="patch",
        ts=ts,
    )
    return {
        "event": f"patch_{status}",
        "actor": {"kind": "operator", "name": "alc_propose"},
        "ts": ts,
        "payload": {
            "patch_id": patch,
            "status": status,
            "lifecycle": record,
        },
    }


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    return str(value)


def _read_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def queue_row_to_record(row: dict[str, Any]) -> dict[str, Any]:
    queue_id = str(row.get("id") or "")
    status = str(row.get("status") or "open")
    ts = str(row.get("ts") or "")
    return lifecycle_ref(
        proposal_kind="gate" if row.get("kind") == "operator_proposed_gate" else str(row.get("kind") or "queue"),
        status=status,
        artifact_id=queue_id,
        artifact_type="improvement_queue",
        ts=ts,
        metadata={
            "domain": row.get("domain"),
            "category": row.get("category"),
            "text": row.get("text"),
            "evidence": row.get("evidence"),
        },
    ) | {"queue_id": queue_id}


def read_proposal_queue(
    state: StateHandle,
    *,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows = [queue_row_to_record(row) for row in _read_jsonl(state.repo_state_dir / "improvement-queue.jsonl")]
    if status is not None:
        rows = [row for row in rows if row.get("status") == status]
    rows.sort(key=lambda row: str(row.get("ts") or ""))
    if limit <= 0:
        return rows
    return rows[-limit:]


def read_patch_records(state: StateHandle) -> list[dict[str, Any]]:
    patch_dir = state.repo_state_dir / "patches"
    if not patch_dir.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(patch_dir.glob("*.json")):
        payload = _read_json(path)
        if not isinstance(payload, dict):
            continue
        patch_id = str(payload.get("patch_id") or path.stem)
        rows.append(
            lifecycle_ref(
                proposal_kind="patch",
                status=str(payload.get("status") or "pending"),
                artifact_id=patch_id,
                artifact_type="patch",
                recommendation_id=payload.get("recommendation_id") if isinstance(payload.get("recommendation_id"), str) else None,
                ts=str(payload.get("created_at") or payload.get("status_updated_at") or ""),
                metadata={"path": str(path), "title": payload.get("title")},
            )
        )
    return rows


def read_suggestion_records(state: StateHandle) -> list[dict[str, Any]]:
    payload = _read_json(state.repo_state_dir / "suggestions.json")
    suggestions = payload.get("suggestions") if isinstance(payload, dict) else None
    if not isinstance(suggestions, list):
        return []
    rows: list[dict[str, Any]] = []
    generated_at = str(payload.get("generated_at") or "")
    for index, suggestion in enumerate(suggestions):
        if not isinstance(suggestion, dict):
            continue
        rec_id = suggestion.get("recommendation_id")
        artifact_id = str(rec_id or suggestion.get("id") or f"suggestion-{index}")
        rows.append(
            lifecycle_ref(
                proposal_kind=str(suggestion.get("kind") or "suggestion"),
                status=str(suggestion.get("status") or "suggested"),
                artifact_id=artifact_id,
                artifact_type="suggestion",
                recommendation_id=rec_id if isinstance(rec_id, str) else None,
                ts=str(suggestion.get("created_at") or generated_at),
                metadata={"title": suggestion.get("title")},
            )
        )
    return rows


def read_lifecycle_state(state: StateHandle, *, limit: int = 200) -> list[dict[str, Any]]:
    rows = [
        *read_proposal_queue(state, limit=0),
        *read_patch_records(state),
        *read_suggestion_records(state),
    ]
    rows.sort(key=lambda row: str(row.get("ts") or ""))
    if limit <= 0:
        return rows
    return rows[-limit:]
