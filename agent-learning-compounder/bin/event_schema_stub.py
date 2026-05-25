"""Minimal EventV4 shim used by U5.5.0b while the full schema lands later."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from collections.abc import Mapping


_SECRET_PATTERNS = [
    re.compile(r"sk-", re.I),
    re.compile(r"\bbearer\b", re.I),
    re.compile(r"aws_access_key_", re.I),
    re.compile(r"ghp_", re.I),
    re.compile(r"gho_", re.I),
]

_PATH_PATTERNS = [
    re.compile(r"/home/", re.I),
    re.compile(r"/Users/", re.I),
    re.compile(r"C:\\Users\\", re.I),
]


def _event_key_for_id(payload: Mapping[str, Any]) -> str:
    ts = payload.get("ts")
    ts_text = str(ts) if ts is not None else None
    if not ts_text:
        ts_token = str(int(time.time()))
    else:
        digits = re.sub(r"\D", "", ts_text)
        ts_token = digits[:13] if digits else str(int(time.time()))
    return ts_token


def _to_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha1(encoded.encode("utf-8")).hexdigest()[:12]


@dataclass
class EventV4:
    event: str
    event_id: str | None = None
    ts: str | None = None
    source: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    schema_version: int = 4
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.event, str) or not self.event.strip():
            raise ValueError("event must be a non-empty string")
        if self.event_id is not None and not isinstance(self.event_id, str):
            raise ValueError("event_id must be a string")
        if self.ts is not None and not isinstance(self.ts, str):
            raise ValueError("ts must be a string")

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.extra)
        payload["event"] = self.event
        if self.event_id is not None:
            payload["event_id"] = self.event_id
        if self.ts is not None:
            payload["ts"] = self.ts
        if self.source is not None:
            payload["source"] = self.source
        payload["payload"] = self.payload
        payload["schema_version"] = self.schema_version
        return payload

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> "EventV4":
        if not isinstance(row, Mapping):
            raise ValueError("EventV4.from_dict expects a mapping")
        payload = dict(row)

        raw_event = payload.pop("event", None)
        if not isinstance(raw_event, str) or not raw_event.strip():
            raise ValueError("event is required")

        payload_data = payload.pop("payload", {})
        if payload_data is None:
            payload_data = {}
        if not isinstance(payload_data, dict):
            raise ValueError("payload must be a dict")

        event_id = payload.pop("event_id", None)
        if event_id is not None and not isinstance(event_id, str):
            raise ValueError("event_id must be a string")

        ts = payload.pop("ts", None)
        if ts is not None and not isinstance(ts, str):
            raise ValueError("ts must be a string")

        source = payload.pop("source", None)
        if source is not None and not isinstance(source, str):
            raise ValueError("source must be a string")

        schema_version = payload.pop("schema_version", 4)
        if schema_version not in (3, 4):
            raise ValueError("unsupported schema_version")

        return cls(
            event=str(raw_event),
            event_id=event_id,
            ts=ts,
            source=source,
            payload=payload_data,
            schema_version=int(schema_version),
            extra=dict(payload),
        )

    @staticmethod
    def deterministic_id(row: "EventV4 | Mapping[str, Any] | dict[str, Any]") -> str:
        payload = row.to_dict() if isinstance(row, EventV4) else dict(row)
        ts_token = _event_key_for_id(payload)
        return f"evt_{ts_token}_{_to_hash(payload)}"

    @classmethod
    def upgrade_from(cls, v3_row: Mapping[str, Any]) -> "EventV4":
        if not isinstance(v3_row, Mapping):
            raise ValueError("v3_row must be a mapping")

        upgraded = dict(v3_row)
        upgraded["schema_version"] = 4

        json_text = json.dumps(upgraded, sort_keys=True, separators=(",", ":"))
        for pattern in _SECRET_PATTERNS + _PATH_PATTERNS:
            if pattern.search(json_text):
                raise ValueError("v3 payload violates boundary constraints")

        return cls.from_dict(upgraded)
