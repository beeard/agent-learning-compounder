#!/usr/bin/env python3
"""Single-source dataclass schema for event stream v4."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import MISSING, dataclass, field, fields, asdict
from types import UnionType
from typing import Any, get_args, get_origin

MAX_LINE_LEN = 200
CORRELATION_CHAIN_MAX = 8
CHAIN_LINK_ID_MAX = 128
ACTOR_KINDS = (
    "main_agent",
    "subagent",
    "background_agent",
    "mcp_server",
    "hook",
    "operator",
    "judge",
    "recommender",
    "arkiv_agent",
    "eval_judge",
)

JSONSCHEMA_DRAFT7 = "http://json-schema.org/draft-07/schema#"

_ABS_PATH_RE = re.compile(r"/home/|/Users/|C:\\Users\\", re.I)
_SECRET_RE = re.compile(
    r"(?i)\b(?:sk-ant-[A-Za-z0-9_\-]{20,}|sk-proj-[A-Za-z0-9_\-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|"
    r"bearer\s+\S+|aws_access_key_|aws_secret_access|api[_-]?key)\b"
)
_TRANSCRIPT_CHUNK_RE = re.compile(r"(?m)^(?:assistant|user|tool)\s*:\s")
_BASE64_RE = re.compile(r"^[A-Za-z0-9+/=\s]+$")


def _coerce_str(value: Any, *, max_len: int = MAX_LINE_LEN) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\n", " ").strip()
    if not text:
        return None
    return text[:max_len]


def _coerce_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("boolean is not a valid integer field")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("+-").isdigit():
        return int(value)
    return None


def _coerce_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _coerce_optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes"}:
            return True
        if lowered in {"0", "false", "no"}:
            return False
    return None


def _ensure_iso8601(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("ts must be ISO8601 UTC string")
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("ts must include timezone")
    return parsed.astimezone(dt.timezone.utc).isoformat()


def _iter_string_values(payload: Any):
    if isinstance(payload, str):
        yield payload
    elif isinstance(payload, dict):
        for value in payload.values():
            yield from _iter_string_values(value)
    elif isinstance(payload, (list, tuple)):
        for value in payload:
            yield from _iter_string_values(value)


def _looks_like_base64(value: str) -> bool:
    compact = value.replace("\n", "").replace(" ", "")
    return bool(compact) and bool(_BASE64_RE.fullmatch(compact)) and len(compact) > 32


def _enforce_boundary(payload: Any, *, allow_patch_payload: bool = False) -> None:
    for value in _iter_string_values(payload):
        if len(value) > MAX_LINE_LEN:
            raise ValueError(f"string exceeds MAX_LINE_LEN={MAX_LINE_LEN}")
        if _ABS_PATH_RE.search(value):
            raise ValueError("absolute path forbidden by boundary enforcement")
        if _SECRET_RE.search(value):
            raise ValueError("secret-like token forbidden by boundary enforcement")
        if _TRANSCRIPT_CHUNK_RE.search(value):
            raise ValueError("raw transcript snippet forbidden by boundary enforcement")
        if (
            len(value) > 1024
            and _looks_like_base64(value)
            and not allow_patch_payload
        ):
            raise ValueError("oversized base64 blob forbidden by boundary enforcement")


def _json_type_for_type(annotation: Any) -> dict[str, Any]:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is list:
        item = args[0] if args else Any
        return {"type": "array", "items": _json_type_for_type(item)}
    if isinstance(annotation, UnionType):
        schemas = []
        for arg in args:
            if arg is type(None):
                schemas.append({"type": "null"})
            else:
                schemas.append(_json_type_for_type(arg))
        if len(schemas) == 1:
            return schemas[0]
        return {"oneOf": schemas}
    if origin is dict:
        return {"type": "object"}
    if origin is None:
        if annotation is str:
            return {"type": "string"}
        if annotation is int:
            return {"type": "integer"}
        if annotation is float:
            return {"type": "number"}
        if annotation is bool:
            return {"type": "boolean"}
        if annotation is type(None):
            return {"type": "null"}
        if isinstance(annotation, type) and hasattr(annotation, "__dataclass_fields__"):
            return _json_schema_for_dataclass(annotation)
    elif origin is not None and str(origin).endswith("Union"):
        schemas = []
        required_null = False
        for arg in args:
            if arg is type(None):
                required_null = True
            else:
                schemas.append(_json_type_for_type(arg))
        if required_null:
            schemas.append({"type": "null"})
        if len(schemas) == 1:
            return schemas[0]
        return {"oneOf": schemas}
    return {"type": "string"}


def _json_schema_for_dataclass(model: type[Any]) -> dict[str, Any]:
    props: dict[str, Any] = {}
    required: list[str] = []
    for field_def in fields(model):
        props[field_def.name] = _json_type_for_type(field_def.type)
        if field_def.default is MISSING and field_def.default_factory is MISSING:
            required.append(field_def.name)
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": props,
        "required": required,
    }


@dataclass
class ActorInfo:
    kind: str
    name: str
    model: str | None = None
    parent_actor_id: str | None = None


@dataclass
class Telemetry:
    duration_ms: int | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cache_read_tokens: int | None = None
    cache_creation_tokens: int | None = None
    cost_usd: float | None = None
    interrupted: bool | None = None


@dataclass
class ChainLink:
    role: str
    id: str


@dataclass
class EventV4:
    event_id: str
    ts: str
    event: str
    schema_version: int = 4
    actor: ActorInfo = field(default_factory=lambda: ActorInfo(kind="hook", name="unknown"))
    telemetry: Telemetry = field(default_factory=Telemetry)
    correlation_chain: list[ChainLink] = field(default_factory=list)
    parent_event_id: str | None = None
    tool_server: str | None = None
    error_class: str | None = None

    @classmethod
    def deterministic_id(cls, actor_kind: str, event_type: str, payload_key: str) -> str:
        if payload_key is None:
            raise ValueError("payload_key required")
        digest = hashlib.sha256(f"{actor_kind}|{event_type}|{payload_key}".encode("utf-8")).hexdigest()[
            :12
        ]
        suffix = payload_key.rsplit(":", 1)[-1]
        if not suffix.isdigit():
            suffix = hashlib.sha256(payload_key.encode("utf-8")).hexdigest()[:12]
        return f"evt_{digest}_{suffix}"

    @classmethod
    def sqlite_ddl(cls) -> str:
        return (
            "CREATE TABLE IF NOT EXISTS events (\n"
            "    event_id TEXT NOT NULL,\n"
            "    ts TEXT NOT NULL,\n"
            "    event TEXT NOT NULL,\n"
            "    schema_version INTEGER NOT NULL DEFAULT 4,\n"
            "    actor_kind TEXT NOT NULL,\n"
            "    actor_name TEXT NOT NULL,\n"
            "    actor_model TEXT,\n"
            "    actor_parent_actor_id TEXT,\n"
            "    telemetry_duration_ms INTEGER,\n"
            "    telemetry_tokens_in INTEGER,\n"
            "    telemetry_tokens_out INTEGER,\n"
            "    telemetry_cache_read_tokens INTEGER,\n"
            "    telemetry_cache_creation_tokens INTEGER,\n"
            "    telemetry_cost_usd REAL,\n"
            "    telemetry_interrupted INTEGER,\n"
            "    correlation_chain TEXT NOT NULL,\n"
            "    parent_event_id TEXT,\n"
            "    tool_server TEXT,\n"
            "    error_class TEXT\n"
            ");\n"
            "CREATE INDEX IF NOT EXISTS idx_events_actor_kind ON events(actor_kind);\n"
            "CREATE INDEX IF NOT EXISTS idx_events_event ON events(event);\n"
        )

    @classmethod
    def jsonschema(cls) -> dict[str, Any]:
        return {
            "$schema": JSONSCHEMA_DRAFT7,
            "$id": "urn:alc:events:event-v4",
            "title": "EventV4",
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "event_id": {"type": "string"},
                "ts": {"type": "string", "format": "date-time"},
                "event": {"type": "string"},
                "schema_version": {"type": "integer", "const": 4},
                "actor": _json_schema_for_dataclass(ActorInfo),
                "telemetry": _json_schema_for_dataclass(Telemetry),
                "correlation_chain": {
                    **_json_type_for_type(list[ChainLink]),
                    "maxItems": CORRELATION_CHAIN_MAX,
                },
                "parent_event_id": {"type": ["string", "null"], "maxLength": MAX_LINE_LEN},
                "tool_server": {"type": ["string", "null"], "maxLength": MAX_LINE_LEN},
                "error_class": {"type": ["string", "null"], "maxLength": MAX_LINE_LEN},
            },
            "required": [
                "event_id",
                "ts",
                "event",
                "schema_version",
                "actor",
                "telemetry",
                "correlation_chain",
            ],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "EventV4":
        if not isinstance(raw, dict):
            raise ValueError("raw must be an object")

        if raw.get("event") is None:
            raise ValueError("missing required field: event")
        if raw.get("ts") is None:
            raise ValueError("missing required field: ts")
        if raw.get("actor") is None:
            raise ValueError("missing required field: actor")

        event_id = _coerce_str(raw.get("event_id"), max_len=MAX_LINE_LEN) or cls._auto_event_id(raw)
        event = _coerce_str(raw["event"], max_len=MAX_LINE_LEN)
        if not event:
            raise ValueError("event must be a non-empty string")
        ts = _ensure_iso8601(raw["ts"])
        schema_version = raw.get("schema_version", 4)
        if not isinstance(schema_version, int):
            raise ValueError("schema_version must be int")

        actor_raw = raw["actor"]
        if not isinstance(actor_raw, dict):
            raise ValueError("actor must be object")
        actor = cls._parse_actor(actor_raw)

        telemetry_raw = raw.get("telemetry", {})
        if not isinstance(telemetry_raw, dict):
            raise ValueError("telemetry must be object")
        telemetry = cls._parse_telemetry(telemetry_raw)

        chain_raw = raw.get("correlation_chain", [])
        if not isinstance(chain_raw, list):
            raise ValueError("correlation_chain must be list")
        if len(chain_raw) > CORRELATION_CHAIN_MAX:
            raise ValueError(f"correlation_chain exceeds max depth {CORRELATION_CHAIN_MAX}")
        correlation_chain = [cls._parse_chain_link(member) for member in chain_raw]

        event_obj = cls(
            event_id=event_id,
            ts=ts,
            event=event,
            schema_version=schema_version,
            actor=actor,
            telemetry=telemetry,
            correlation_chain=correlation_chain,
            parent_event_id=_coerce_str(raw.get("parent_event_id"), max_len=MAX_LINE_LEN),
            tool_server=_coerce_str(raw.get("tool_server"), max_len=MAX_LINE_LEN),
            error_class=_coerce_str(raw.get("error_class"), max_len=MAX_LINE_LEN),
        )
        _enforce_boundary(event_obj.to_dict())
        return event_obj

    @classmethod
    def upgrade_from(cls, v3_row: dict[str, Any]) -> "EventV4":
        if not isinstance(v3_row, dict):
            raise ValueError("v3 row must be object")

        # Defensive reorder: enforce the boundary on a copy of v3_row that
        # drops the known abs-path-bearing field (`repo`). v3 collect_hook_event
        # set `repo` to the absolute repo path; the boundary check would
        # quarantine every row collected before SCHEMA_VERSION=4. `repo` is
        # not mapped into the v4 envelope, so dropping it from the
        # enforcement view is safe -- the secret/transcript/base64 checks on
        # all other v3 fields (including drop-only fields like `payload`
        # that downstream consumers may still inspect) still run.
        v3_for_check = {k: v for k, v in v3_row.items() if k != "repo"}
        _enforce_boundary(v3_for_check)

        payload = {
            "ts": v3_row.get("ts"),
            "event": _coerce_str(v3_row.get("event"), max_len=MAX_LINE_LEN) or "unknown_event",
            "schema_version": 4,
            "actor": {
                "kind": cls._normalize_actor_kind(v3_row.get("runtime")),
                "name": (
                    _coerce_str(v3_row.get("command_class"), max_len=MAX_LINE_LEN)
                    or _coerce_str(v3_row.get("tool"), max_len=MAX_LINE_LEN)
                    or "hook"
                ),
                "model": _coerce_str(v3_row.get("agent_model"), max_len=MAX_LINE_LEN),
                "parent_actor_id": _coerce_str(v3_row.get("parent_actor_id"), max_len=MAX_LINE_LEN),
            },
            "telemetry": {
                "duration_ms": _coerce_optional_int(v3_row.get("duration_ms")),
                "tokens_in": _coerce_optional_int(v3_row.get("tokens_in")),
                "tokens_out": _coerce_optional_int(v3_row.get("tokens_out")),
                "cache_read_tokens": _coerce_optional_int(v3_row.get("cache_read_tokens")),
                "cache_creation_tokens": _coerce_optional_int(v3_row.get("cache_creation_tokens")),
                "cost_usd": _coerce_optional_float(v3_row.get("cost_usd")),
                "interrupted": _coerce_optional_bool(v3_row.get("interrupted")),
            },
            "correlation_chain": v3_row.get("correlation_chain", []),
            "parent_event_id": _coerce_str(v3_row.get("parent_event_id"), max_len=MAX_LINE_LEN),
            "tool_server": _coerce_str(v3_row.get("tool_server"), max_len=MAX_LINE_LEN)
            or _coerce_str(v3_row.get("runtime"), max_len=MAX_LINE_LEN),
            "error_class": _coerce_str(v3_row.get("error_class"), max_len=MAX_LINE_LEN),
            "event_id": _coerce_str(v3_row.get("event_id"), max_len=MAX_LINE_LEN),
        }
        return cls.from_dict(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "ts": self.ts,
            "event": self.event,
            "schema_version": self.schema_version,
            "actor": asdict(self.actor),
            "telemetry": asdict(self.telemetry),
            "correlation_chain": [asdict(link) for link in self.correlation_chain],
            "parent_event_id": self.parent_event_id,
            "tool_server": self.tool_server,
            "error_class": self.error_class,
        }

    @classmethod
    def _auto_event_id(cls, raw: dict[str, Any]) -> str:
        ts = _ensure_iso8601(raw.get("ts"))
        bucket = dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%Y%m%d_%H%M%S")
        digest = hashlib.sha256(json.dumps(raw, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]
        return f"evt_{bucket}_{digest}"

    @classmethod
    def _normalize_actor_kind(cls, value: Any) -> str:
        value = _coerce_str(value) or "hook"
        value = value.lower()
        return value if value in ACTOR_KINDS else "hook"

    @classmethod
    def _parse_actor(cls, raw: dict[str, Any]) -> ActorInfo:
        kind = _coerce_str(raw.get("kind"), max_len=MAX_LINE_LEN)
        if kind not in ACTOR_KINDS:
            raise ValueError(f"invalid actor.kind: {kind}")
        name = _coerce_str(raw.get("name"), max_len=MAX_LINE_LEN)
        if not name:
            raise ValueError("actor.name required")
        return ActorInfo(
            kind=kind,
            name=name,
            model=_coerce_str(raw.get("model"), max_len=MAX_LINE_LEN),
            parent_actor_id=_coerce_str(raw.get("parent_actor_id"), max_len=MAX_LINE_LEN),
        )

    @classmethod
    def _parse_telemetry(cls, raw: dict[str, Any]) -> Telemetry:
        return Telemetry(
            duration_ms=_coerce_optional_int(raw.get("duration_ms")),
            tokens_in=_coerce_optional_int(raw.get("tokens_in")),
            tokens_out=_coerce_optional_int(raw.get("tokens_out")),
            cache_read_tokens=_coerce_optional_int(raw.get("cache_read_tokens")),
            cache_creation_tokens=_coerce_optional_int(raw.get("cache_creation_tokens")),
            cost_usd=_coerce_optional_float(raw.get("cost_usd")),
            interrupted=_coerce_optional_bool(raw.get("interrupted")),
        )

    @classmethod
    def _parse_chain_link(cls, raw: Any) -> ChainLink:
        if not isinstance(raw, dict):
            raise ValueError("correlation_chain members must be objects")
        role = _coerce_str(raw.get("role"), max_len=MAX_LINE_LEN)
        if not role:
            raise ValueError("correlation_chain member role required")
        link_id = _coerce_str(raw.get("id"), max_len=CHAIN_LINK_ID_MAX + 1)
        if not link_id:
            raise ValueError("correlation_chain member id required")
        if len(link_id) > CHAIN_LINK_ID_MAX:
            raise ValueError(f"correlation_link id exceeds {CHAIN_LINK_ID_MAX}")
        return ChainLink(role=role, id=link_id)
