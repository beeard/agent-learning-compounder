"""Shared write-path for EventV4 JSONL telemetry."""

from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import json
import os
import pathlib
import re
import stat
from typing import Any, Literal

from collections.abc import Mapping

try:
    from scrub_secrets import scrub
except ImportError:
    from bin.scrub_secrets import scrub

try:
    from state_handle import StateHandle, event_write_target
except ImportError:
    from bin.state_handle import StateHandle, event_write_target

try:
    from bin.event_schema import EventV4
except ImportError:
    from event_schema import EventV4


MAX_LINE_LEN = 200
MAX_EVENT_BYTES = 50 * 1024 * 1024

EventSource = Literal["hook", "transcript", "correlation", "background", "apply", "eval"]

_SECRET_PATTERNS = [
    re.compile(r"sk-", re.I),
    re.compile(r"\bbearer\b", re.I),
    re.compile(r"aws_access_key_", re.I),
    re.compile(r"ghp_", re.I),
    re.compile(r"gho_", re.I),
]

_ABSOLUTE_HOST_PATH_PATTERNS = [
    re.compile(r"/home/", re.I),
    re.compile(r"/Users/", re.I),
    re.compile(r"C:\\Users\\", re.I),
]

_TRANSCRIPT_MARKERS = [
    re.compile(r"(?im)^\s*(?:assistant|user)\b"),
    re.compile(r"<\s*(?:assistant|user)\s*>", re.I),
]

_BASE64_BLOB = re.compile(r"[A-Za-z0-9+/=]{1024,}")


def _state_lock_path(state: pathlib.Path) -> pathlib.Path:
    return state / ".events.lock"


def _events_path(state: pathlib.Path) -> pathlib.Path:
    return state / "events.jsonl"


@contextlib.contextmanager
def _acquire_state_lock(lock_path: pathlib.Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _assert_regular_file(path: pathlib.Path, *, label: str) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    if stat.S_ISLNK(mode):
        raise ValueError(f"{label} is a symlink: {path}")
    if not stat.S_ISREG(mode):
        raise ValueError(f"{label} is not a regular file: {path}")


def _looks_like_blob_key(path: str) -> bool:
    field = path.rsplit(".", 1)[-1].lower()
    return field.endswith("_bytes_b64") or field.endswith("_blob") or field.endswith("_b64")


def _iter_string_fields(node: Any, prefix: str = "") -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if isinstance(node, str):
        out.append((prefix, node))
        return out
    if isinstance(node, list):
        for index, member in enumerate(node):
            out.extend(_iter_string_fields(member, f"{prefix}[{index}]"))
        return out
    if isinstance(node, dict):
        for key, member in node.items():
            next_path = key if not prefix else f"{prefix}.{key}"
            out.extend(_iter_string_fields(member, next_path))
        return out
    return out


def _scrub_strings(value: Any) -> Any:
    if isinstance(value, str):
        clean = scrub(value)
        if "[REDACTED:" in clean:
            raise ValueError("free-text contains secret-like content")
        return clean
    if isinstance(value, list):
        return [_scrub_strings(member) for member in value]
    if isinstance(value, tuple):
        return [_scrub_strings(member) for member in value]
    if isinstance(value, dict):
        return {key: _scrub_strings(member) for key, member in value.items()}
    return value


def _bound_text(value: Any) -> Any:
    if isinstance(value, str):
        collapsed = " ".join(str(value).split())
        return collapsed[:MAX_LINE_LEN]
    if isinstance(value, list):
        return [_bound_text(member) for member in value]
    if isinstance(value, tuple):
        return [_bound_text(member) for member in value]
    if isinstance(value, dict):
        return {key: _bound_text(member) for key, member in value.items()}
    return value


def _boundary_checks(event: dict[str, Any], source: EventSource) -> None:
    allow_large_blob = source == "apply" and str(event.get("event") or "") in {"patch_applied", "patch_reverted"}
    for path, text in _iter_string_fields(event):
        if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
            raise ValueError(f"event boundary violation: secret-like content in {path}")
        if any(pattern.search(text) for pattern in _ABSOLUTE_HOST_PATH_PATTERNS):
            raise ValueError(f"event boundary violation: absolute path in {path}")
        if any(pattern.search(text) for pattern in _TRANSCRIPT_MARKERS):
            raise ValueError("event boundary violation: raw transcript chunk")
        if not allow_large_blob and _BASE64_BLOB.search(text):
            raise ValueError("event boundary violation: oversized base64 payload")
        if len(text) > MAX_LINE_LEN and not (allow_large_blob and _looks_like_blob_key(path)):
            raise ValueError(f"event boundary violation: overlong field {path}")


_SOURCE_TO_DEFAULT_ACTOR_KIND = {
    "hook": "hook",
    "transcript": "main_agent",
    "correlation": "main_agent",
    "background": "background_agent",
    "apply": "operator",
    "eval": "eval_judge",
}


def _coerce_row(
    raw_or_dataclass: Any,
    source: EventSource,
    auto_id_fallback: bool,
    *,
    write_scope: str,
) -> dict[str, Any]:
    if isinstance(raw_or_dataclass, EventV4):
        event = raw_or_dataclass.to_dict()
        had_event_id = bool(event.get("event_id"))
    elif isinstance(raw_or_dataclass, Mapping):
        raw = dict(raw_or_dataclass)
        # Early auto_id_fallback gate — before EventV4.from_dict auto-generates an id.
        had_event_id = bool(raw.get("event_id"))
        if not had_event_id and not auto_id_fallback:
            raise ValueError("event_id missing and auto_id_fallback=False")
        # Inject required-field defaults so callers (hooks, transcripts) can pass minimal rows.
        if not raw.get("ts"):
            raw["ts"] = dt.datetime.now(dt.timezone.utc).isoformat()
        if raw.get("actor") is None:
            raw["actor"] = {
                "kind": _SOURCE_TO_DEFAULT_ACTOR_KIND.get(source, "main_agent"),
                "name": f"auto:{source}",
            }
        event = EventV4.from_dict(raw).to_dict()
        # EventV4 schema doesn't yet carry `payload`; preserve from raw so
        # _boundary_checks can scan it. (Proper schema extension is U5.5.1+ work.)
        if "payload" in raw:
            event["payload"] = raw["payload"]
    else:
        raise TypeError("write_event expects an EventV4 or mapping")

    payload = event.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    event["payload"] = payload
    payload.setdefault("_write_scope", write_scope)

    event["source"] = source
    if not event.get("ts"):
        event["ts"] = dt.datetime.now(dt.timezone.utc).isoformat()

    if had_event_id:
        event_id = str(event["event_id"])
    else:
        # Auto-ID format per U5.5.0a docstring (random shorthash for non-deterministic sources).
        import secrets as _secrets
        event_id = f"evt_{int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)}_{_secrets.token_hex(4)}"
        event["event_id"] = event_id

    # KTD-16: boundary checks on the raw event BEFORE scrubbing so secrets/paths
    # surface as ValueError rather than getting silently masked.
    _boundary_checks(event, source)
    scrubbed = _scrub_strings(event)
    bounded = _bound_text(scrubbed)
    bounded["event_id"] = event_id
    return bounded


def write_event(
    raw_or_dataclass: Any,
    source: EventSource,
    auto_id_fallback: bool = True,
    *,
    repo: pathlib.Path | None = None,
    state: StateHandle | None = None,
    state_root: pathlib.Path | None = None,
) -> str:
    ids = write_events_batch(
        [raw_or_dataclass],
        source=source,
        auto_id_fallback=auto_id_fallback,
        repo=repo,
        state=state,
        state_root=state_root,
    )
    return ids[0]


def write_events_batch(
    rows: list[Any] | tuple[Any, ...],
    source: EventSource,
    auto_id_fallback: bool = True,
    *,
    repo: pathlib.Path | None = None,
    state: StateHandle | None = None,
    state_root: pathlib.Path | None = None,
) -> list[str]:
    target = event_write_target(
        repo=repo,
        state=state,
        state_root=state_root,
    )
    events = [
        _coerce_row(
            row,
            source,
            auto_id_fallback=auto_id_fallback,
            write_scope=target.write_scope,
        )
        for row in rows
    ]
    state = target.event_dir
    lock_path = _state_lock_path(state)
    output = _events_path(state)
    state.mkdir(parents=True, exist_ok=True)

    _assert_regular_file(output, label="events log")

    with _acquire_state_lock(lock_path):
        _rotate_if_needed(output)
        lines: list[str] = [json.dumps(event, sort_keys=True, separators=(",", ":")) for event in events]
        with open(output, "a", encoding="utf-8") as handle:
            for line in lines:
                handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        _rotate_if_needed(output)

    return [str(event["event_id"]) for event in events]


def _rotate_if_needed(output: pathlib.Path) -> None:
    try:
        size = output.stat().st_size
    except OSError:
        return
    if size <= MAX_EVENT_BYTES:
        return
    backup = output.with_name("events.jsonl.1")
    os.replace(output, backup)
    try:
        os.chmod(backup, 0o600)
    except OSError:
        pass
