#!/usr/bin/env python3
"""Shared transcript parsing helpers for Claude and Codex transcript formats."""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import pathlib
import re
from typing import Any, Iterable, Iterator

from event_writer import EventV4

logger = logging.getLogger(__name__)


CLAUDE_EVENT_TYPES = {"user", "assistant", "tool_use", "tool_result"}
CORRELATION_SESSION_ROLE = "session"
CORRELATION_PARENT_ROLE = "parent"
CORRELATION_TOOL_ROLE = "tool"

CLAUDE_EVENT_MAP = {
    "user": "client_message",
    "assistant": "agent_message",
    "tool_use": "tool_use",
    "tool_result": "tool_result",
}

CODEX_EVENT_MAP = {
    "PreToolUse": "pre_tool_use",
    "PostToolUse": "post_tool_use",
    "PostToolUseFailure": "post_tool_use_failure",
    "SessionStart": "session_start",
    "SessionEnd": "session_end",
    "SubagentStart": "subagent_start",
    "SubagentStop": "subagent_stop",
    "HookSuccess": "hook_success",
    "HookFailure": "hook_failure",
    "AutoMode": "auto_mode",
    "PermissionsMode": "permissions_mode",
    "FileChanged": "file_changed",
}


_TS_KEYS = ("ts", "timestamp", "created_at", "time", "event_ts", "event_time", "createdTime")
_SESSION_KEYS = (
    "session_id",
    "sessionId",
    "session",
    "conversation_id",
    "conversationId",
)
_EVENT_ID_KEYS = (
    "uuid",
    "id",
    "toolUseID",
    "tool_use_id",
    "event_id",
    "parent_id",
)
_PARENT_ID_KEYS = (
    "parent_uuid",
    "parentUuid",
    "parent_id",
    "parentEventId",
    "tool_result_id",
)
_PATH_KEYS = ("path", "cwd", "file", "repo", "code_path", "workingDirectory", "working_directory")


def iter_transcript_jsonl(path: pathlib.Path) -> Iterator[tuple[int, dict[str, Any]]]:
    """Yield ``(line_no, payload)`` pairs from a JSONL transcript file."""
    path = pathlib.Path(path).expanduser()
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for idx, raw in enumerate(handle, 1):
            raw_text = raw.strip()
            if not raw_text:
                continue
            try:
                row = json.loads(raw_text)
            except json.JSONDecodeError as exc:
                logger.warning("Skipping malformed JSON in %s:%d (%s)", path, idx, exc)
                continue
            if isinstance(row, dict):
                yield idx, row


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_snake(value: str) -> str:
    text = re.sub(r"\s+", "_", str(value).strip())
    text = re.sub(r"[^\w\-]+", "_", text).strip("_").lower()
    text = re.sub(r"([a-z])([A-Z])", r"\1_\2", text).lower()
    return text or "unknown"


def _normalize_path(value: str | None) -> str | None:
    text = _coerce_str(value)
    if not text:
        return None
    if ":" in text and "\\" in text:
        text = text.replace("\\", "/")
    if not os.path.isabs(text):
        return text

    stripped = text
    if re.match(r"^[A-Za-z]:/", stripped):
        stripped = re.sub(r"^[A-Za-z]:/", "", stripped)
    home = str(pathlib.Path.home())
    if stripped.startswith(home):
        return stripped[len(home) :].lstrip("/\\")
    if stripped.startswith("/"):
        stripped = stripped.lstrip("/")
    return stripped


def _parse_ts(value: Any) -> dt.datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return dt.datetime.fromtimestamp(float(value), tz=dt.timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return dt.datetime.fromisoformat(text).astimezone(dt.timezone.utc)
    except ValueError:
        return None


def _extract_timestamp(raw: dict[str, Any]) -> dt.datetime:
    for key in _TS_KEYS:
        if key in raw:
            parsed = _parse_ts(raw.get(key))
            if parsed is not None:
                return parsed
    message = raw.get("message")
    if isinstance(message, dict):
        for key in _TS_KEYS:
            parsed = _parse_ts(message.get(key))
            if parsed is not None:
                return parsed
    return dt.datetime.now(dt.timezone.utc)


def _extract_session_id(raw: dict[str, Any]) -> str | None:
    for key in _SESSION_KEYS:
        value = _coerce_str(raw.get(key))
        if value:
            return value
    message = raw.get("message")
    if isinstance(message, dict):
        for key in _SESSION_KEYS:
            value = _coerce_str(message.get(key))
            if value:
                return value
    return None


def _extract_event_id(raw: dict[str, Any]) -> str | None:
    for key in _EVENT_ID_KEYS:
        value = _coerce_str(raw.get(key))
        if value:
            return value
    message = raw.get("message")
    if isinstance(message, dict):
        for key in _EVENT_ID_KEYS:
            value = _coerce_str(message.get(key))
            if value:
                return value
    attachment = raw.get("attachment")
    if isinstance(attachment, dict):
        value = _coerce_str(attachment.get("id"))
        if value:
            return value
    return None


def _extract_parent_id(raw: dict[str, Any]) -> str | None:
    for key in _PARENT_ID_KEYS:
        value = _coerce_str(raw.get(key))
        if value:
            return value
    attachment = raw.get("attachment")
    if isinstance(attachment, dict):
        value = _coerce_str(attachment.get("parent"))
        if value:
            return value
    return None


def _extract_path(raw: dict[str, Any]) -> str | None:
    for key in _PATH_KEYS:
        value = _coerce_str(raw.get(key))
        if value:
            return _normalize_path(value)
    for key in _PATH_KEYS:
        attachment = raw.get(key)
        if isinstance(attachment, dict):
            value = _coerce_str(attachment.get("path"))
            if value:
                return _normalize_path(value)
    return None


def _normalize_event_type(event_type: str | None) -> str:
    if not event_type:
        return "transcript_event"
    text = str(event_type).strip()
    if not text:
        return "transcript_event"
    if text in CLAUDE_EVENT_MAP:
        return CLAUDE_EVENT_MAP[text]
    return _to_snake(text)


def _extract_claude_event_type(raw: dict[str, Any]) -> str:
    message = raw.get("message")
    if isinstance(message, dict):
        direct = _coerce_str(message.get("type")) or _coerce_str(message.get("role"))
        if direct and direct in CLAUDE_EVENT_TYPES:
            return _normalize_event_type(direct)
    raw_type = _coerce_str(raw.get("type"))
    if raw_type:
        if raw_type in CLAUDE_EVENT_TYPES:
            return _normalize_event_type(raw_type)
    if isinstance(message, dict):
        role = _coerce_str(message.get("role"))
        if role:
            return _normalize_event_type(role)
    return "transcript_event"


def _extract_codex_event_type(raw: dict[str, Any]) -> str:
    raw_type = _coerce_str(raw.get("type"))
    if raw_type in CLAUDE_EVENT_TYPES:
        return _normalize_event_type(raw_type)
    if raw_type and raw_type in CODEX_EVENT_MAP:
        return CODEX_EVENT_MAP[raw_type]
    if raw_type:
        attachment = raw.get("attachment")
        if isinstance(attachment, dict):
            attachment_type = _coerce_str(attachment.get("type"))
            if attachment_type and attachment_type in CODEX_EVENT_MAP:
                return CODEX_EVENT_MAP[attachment_type]
        return _normalize_event_type(raw_type)
    attachment = raw.get("attachment")
    if isinstance(attachment, dict):
        attachment_type = _coerce_str(attachment.get("type"))
        if attachment_type:
            return CODEX_EVENT_MAP.get(attachment_type, _normalize_event_type(attachment_type))
    return "transcript_event"


def _extract_payload(raw: dict[str, Any], event_type: str, source: str) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    include_keys = (
        "event",
        "eventType",
        "tool",
        "tool_name",
        "toolName",
        "tool_call_id",
        "name",
        "label",
        "status",
        "outcome",
        "result",
        "path",
        "cwd",
        "repo",
        "runtime",
        "subtype",
        "message_id",
        "request_id",
        "session",
        "subtype",
        "command",
    )
    for key in include_keys:
        value = raw.get(key)
        if isinstance(value, (str, int, float, bool)):
            payload[key] = value
    message = raw.get("message")
    if isinstance(message, dict):
        for key in ("status", "outcome", "tool", "tool_name", "toolName", "path", "cwd"):
            value = message.get(key)
            if isinstance(value, (str, int, float, bool)):
                payload[key] = value
    payload["source"] = source
    payload["event_type"] = event_type
    payload["path"] = _extract_path(raw) or _extract_path(raw.get("message", {}) if isinstance(raw.get("message"), dict) else {})
    return payload


def _correlation_chain(raw: dict[str, Any], *, event_id: str | None, parent_id: str | None, source: str) -> list[dict[str, str]]:
    chain: list[dict[str, str]] = []
    session_id = _extract_session_id(raw)
    if session_id:
        chain.append({"role": CORRELATION_SESSION_ROLE, "id": session_id})
    if parent_id:
        chain.append({"role": CORRELATION_PARENT_ROLE, "id": parent_id})
    tool_id = _coerce_str(raw.get("toolUseID") or raw.get("tool_use_id"))
    if tool_id:
        chain.append({"role": CORRELATION_TOOL_ROLE, "id": tool_id})
    return chain


def _emit_row(raw: dict[str, Any], event_type: str, source: str) -> dict[str, Any]:
    event_id = _extract_event_id(raw)
    parent_id = _extract_parent_id(raw)
    parsed_ts = _extract_timestamp(raw)
    chain = _correlation_chain(raw, event_id=event_id, parent_id=parent_id, source=source)
    payload = _extract_payload(raw, event_type, source)
    payload = {key: value for key, value in payload.items() if value is not None}
    if "path" in payload:
        normalized_path = _normalize_path(_coerce_str(payload["path"]))
        if normalized_path:
            payload["path"] = normalized_path

    event: dict[str, Any] = {
        "schema_version": 4,
        "event": event_type,
        "ts": parsed_ts.isoformat(),
        "runtime": source,
        "actor": {"kind": "main_agent", "name": f"transcript-{source}"},
        "correlation_chain": chain,
        "payload": payload,
        "path": _normalize_path(_extract_path(raw)),
    }

    session_id = _extract_session_id(raw)
    if session_id:
        event["session_id"] = session_id
    if parent_id:
        event["parent_event_id"] = parent_id
    return event


def parse_claude_transcript(path: pathlib.Path) -> Iterator[dict[str, Any]]:
    """Parse a single Claude transcript into normalized event rows."""
    for _line_no, raw in iter_transcript_jsonl(path):
        event_type = _extract_claude_event_type(raw)
        if not isinstance(event_type, str):
            continue
        yield _emit_row(raw, event_type, "claude")


def parse_codex_transcript(path: pathlib.Path) -> Iterator[dict[str, Any]]:
    """Parse a single Codex transcript into normalized event rows."""
    for _line_no, raw in iter_transcript_jsonl(path):
        event_type = _extract_codex_event_type(raw)
        if not isinstance(event_type, str):
            continue
        yield _emit_row(raw, event_type, "codex")


def iter_transcript_events(path: pathlib.Path) -> Iterator[dict[str, Any]]:
    """Auto-detect format and parse a transcript file.

    The current heuristics treat paths under ``~/.codex`` as Codex transcripts
    and everything else as Claude.
    """
    path = pathlib.Path(path)
    if path.is_file() and "codex" in str(path).lower():
        yield from parse_codex_transcript(path)
    else:
        yield from parse_claude_transcript(path)


def deterministic_event_id(event_type: str, transcript_path: pathlib.Path, offset: int) -> str:
    """Return deterministic id for backfill events."""
    payload_key = f"{pathlib.Path(transcript_path).as_posix()}:{offset}"
    return EventV4.deterministic_id("main_agent", event_type, payload_key=payload_key)
