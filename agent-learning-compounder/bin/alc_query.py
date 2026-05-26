#!/usr/bin/env python3
"""Read-only query API used by MCP/dashboard/CLI."""

from __future__ import annotations

import collections
import contextlib
import datetime as dt
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

try:
    from state_handle import StateHandle
except ImportError:  # pragma: no cover
    from bin.state_handle import StateHandle


_DURATION_RE = re.compile(r"^(\d+)([smhdw])$", re.I)
_ALLOWED_KIND_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_NOW = dt.datetime.now


class QueryError(RuntimeError):
    pass


def _read_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _read_agent_learning_config(state: StateHandle) -> dict[str, Any]:
    data = _read_json(state.repo / ".agent-learning.json")
    return data if isinstance(data, dict) else {}


def _configured_path(state: StateHandle, key: str, fallback: Path) -> Path:
    value = _read_agent_learning_config(state).get(key)
    return Path(value) if isinstance(value, str) and value.strip() else fallback


def get_gates(state: StateHandle, scope: str | None = None) -> list[dict[str, Any]]:
    path = _configured_path(state, "latest_approved_gates", state.reports_dir / "latest-approved-gates.md")
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for i, block in enumerate(path.read_text(encoding="utf-8").split("\n- domain:")):
        if i == 0:
            continue
        lines = block.splitlines()
        if not lines:
            continue
        domain = lines[0].strip()
        row: dict[str, Any] = {"domain": domain}
        for line in lines[1:]:
            stripped = line.strip()
            if stripped.startswith("gate_id:"):
                row["gate_id"] = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("gate_category:"):
                row["category"] = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("gate:"):
                row["gate"] = stripped.split(":", 1)[1].strip()
        if {"gate_id", "category", "gate"} <= set(row):
            out.append(row)
    return [gate for gate in out if gate["domain"] == scope] if scope else out


def get_skill_context(state: StateHandle) -> str:
    path = _configured_path(state, "latest_skill_context", state.reports_dir / "latest-skill-context.md")
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _to_iso(dt_value: dt.datetime) -> str:
    if dt_value.tzinfo is None:
        dt_value = dt_value.replace(tzinfo=dt.timezone.utc)
    return dt_value.astimezone(dt.timezone.utc).isoformat()


def _parse_since(since: str | dt.datetime | int | float | None) -> str | None:
    if since is None:
        return None
    if isinstance(since, (int, float)):
        return _to_iso(dt.datetime.fromtimestamp(float(since), tz=dt.timezone.utc))
    if isinstance(since, dt.datetime):
        return _to_iso(since)

    if not isinstance(since, str):
        raise TypeError("since must be None, datetime, numeric epoch, or duration string")

    text = since.strip().lower()
    if not text:
        return None

    m = _DURATION_RE.fullmatch(text)
    if m:
        count = int(m.group(1))
        unit = m.group(2)
        now = _NOW(dt.timezone.utc)
        if unit == "s":
            delta = dt.timedelta(seconds=count)
        elif unit == "m":
            delta = dt.timedelta(minutes=count)
        elif unit == "h":
            delta = dt.timedelta(hours=count)
        else:
            delta = dt.timedelta(days=count)
        return _to_iso(now - delta)

    try:
        value = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        if value.tzinfo is None:
            raise ValueError
        return value.astimezone(dt.timezone.utc).isoformat()
    except ValueError as exc:
        raise ValueError(f"unsupported since value: {since!r}") from exc


def _connect_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


@contextlib.contextmanager
def _with_conn(target: StateHandle | Path):
    # sqlite3.Connection's own context manager only commits/rolls back — it does
    # NOT close. Without this contextmanager wrapper, every caller's `with _with_conn(...)`
    # leaked a connection (the dashboard process opens 4-5 per /data.json request).
    path = target.events_sqlite if isinstance(target, StateHandle) else Path(target)
    conn = _connect_readonly(path)
    try:
        yield conn
    finally:
        conn.close()


def _query_as_dicts(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def _row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if value is not None}


def _normalize_kind_filter(kind_filter: str | list[str] | tuple[str, ...] | None) -> list[str] | None:
    if kind_filter is None:
        return None
    if isinstance(kind_filter, str):
        values = [kind_filter]
    else:
        values = list(kind_filter)
    cleaned: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        if not _ALLOWED_KIND_PATTERN.fullmatch(text):
            raise ValueError(f"invalid event kind: {value!r}")
        cleaned.append(text)
    return cleaned or None


def _ensure_session_filter(conn: sqlite3.Connection) -> bool:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(events)")}
    return "session_id" in cols


def get_apply_log(state: StateHandle, since: str | dt.datetime | int | float | None = None, kind_filter=None) -> list[dict[str, Any]]:
    path = state.events_sqlite
    if not path.is_file():
        return []

    kinds = _normalize_kind_filter(kind_filter)

    where = ["event LIKE 'patch_%'"]
    params: list[Any] = []
    if since is not None:
        cutoff = _parse_since(since)
        if cutoff is not None:
            where.append("ts >= ?")
            params.append(cutoff)
    if kinds:
        placeholders = ",".join(["?"] * len(kinds))
        where.append(f"event IN ({placeholders})")
        params.extend(kinds)

    sql = "SELECT event_id, ts, event, actor_kind, actor_name, parent_event_id, correlation_chain FROM events"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY ts ASC"

    with _with_conn(path) as conn:
        rows = _query_as_dicts(conn, sql, tuple(params))
    return [_row_to_dict(row) for row in rows]


def get_outcomes(state: StateHandle, since: str | dt.datetime | int | float | None = None) -> list[dict[str, Any]]:
    path = state.events_sqlite
    if not path.is_file():
        return []

    sql = "SELECT event_id, ts, event, actor_kind, actor_name, parent_event_id, correlation_chain FROM events WHERE event = 'eval_verdict'"
    params: list[Any] = []
    cutoff = _parse_since(since)
    if cutoff is not None:
        sql += " AND ts >= ?"
        params.append(cutoff)
    sql += " ORDER BY ts ASC"

    with _with_conn(path) as conn:
        rows = _query_as_dicts(conn, sql, tuple(params))
    return [_row_to_dict(row) for row in rows]


def get_recommendations(state: StateHandle) -> list[dict[str, Any]]:
    data = _read_json(state.reports_dir / "recommendations.json")
    if data is None:
        return []
    if isinstance(data, dict):
        rows = data.get("items")
    else:
        rows = data
    if not isinstance(rows, list):
        return []
    return [row if isinstance(row, dict) else {} for row in rows]


def get_pending_patches(state: StateHandle) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    patch_dir = state.repo_state_dir / "patches"
    if not patch_dir.is_dir():
        return []

    for path in sorted(patch_dir.glob("*.json")):
        payload = _read_json(path)
        if not isinstance(payload, dict):
            continue
        status = str(payload.get("status", "pending"))
        if status in {"deferred", "rejected"}:
            continue
        payload = dict(payload)
        payload["patch_id"] = payload.get("patch_id", path.stem)
        payload["_path"] = str(path)
        out.append(payload)
    out.sort(key=lambda row: row.get("ts", ""))
    return out


def get_event_dag(state: StateHandle, session_id: str) -> dict[str, Any]:
    path = state.events_sqlite
    if not path.is_file():
        return {"session_id": session_id, "nodes": []}

    with _with_conn(path) as conn:
        rows = _query_as_dicts(
            conn,
            """
            WITH RECURSIVE chain AS (
                SELECT event_id, parent_event_id, ts, event, actor_kind, actor_name, 0 AS depth
                FROM events
                WHERE session_id = ?
                  AND (
                      parent_event_id IS NULL
                      OR parent_event_id = ''
                      OR NOT EXISTS (
                          SELECT 1
                          FROM events AS parent
                          WHERE parent.session_id = events.session_id
                            AND parent.event_id = events.parent_event_id
                      )
                  )
                UNION ALL
                SELECT e.event_id, e.parent_event_id, e.ts, e.event, e.actor_kind, e.actor_name, chain.depth + 1
                FROM events e
                JOIN chain ON e.parent_event_id = chain.event_id
                WHERE e.session_id = ? AND chain.depth < 64
            )
            SELECT event_id, parent_event_id, ts, event, actor_kind, actor_name, depth
            FROM chain
            ORDER BY depth ASC, ts ASC
            """,
            (session_id, session_id),
        )

    if not rows:
        return {"session_id": session_id, "nodes": []}

    by_id: dict[str, dict[str, Any]] = {}
    children: dict[str | None, list[str]] = collections.defaultdict(list)
    for row in rows:
        row_id = str(row["event_id"])
        parent = row.get("parent_event_id")
        parent_id = str(parent) if parent else None
        payload = {
            "event_id": row_id,
            "parent_event_id": parent,
            "ts": row.get("ts"),
            "event": row.get("event"),
            "actor_kind": row.get("actor_kind"),
            "actor_name": row.get("actor_name"),
            "children": [],
        }
        by_id[row_id] = payload
        children[parent_id].append(row_id)

    def _build(node_id: str) -> dict[str, Any]:
        node = by_id[node_id]
        node["children"] = [_build(child_id) for child_id in children.get(node_id, [])]
        return node

    root_ids = children.get(None, [])
    # Fallback: treat missing-parent rows as roots for orphaned chains.
    known = set(by_id)
    if not root_ids:
        root_ids = sorted(id_ for id_ in by_id if by_id[id_]["parent_event_id"] not in known)

    return {
        "session_id": session_id,
        "nodes": [_build(node_id) for node_id in root_ids],
    }


def get_actor_summary(state: StateHandle, since: str = "7d") -> dict[str, Any]:
    path = state.events_sqlite
    if not path.is_file():
        return {"since": since, "total": 0, "by_actor_kind": []}

    cutoff = _parse_since(since)
    sql = "SELECT actor_kind, COUNT(*) AS count, COUNT(DISTINCT actor_name) AS unique_actors"
    sql += " FROM events"
    params: list[Any] = []
    if cutoff is not None:
        sql += " WHERE ts >= ?"
        params.append(cutoff)
    sql += " GROUP BY actor_kind ORDER BY actor_kind"

    with _with_conn(path) as conn:
        rows = _query_as_dicts(conn, sql, tuple(params))

    return {
        "since": since,
        "total": sum(int(r["count"]) for r in rows),
        "by_actor_kind": [
            {"actor_kind": r["actor_kind"], "count": int(r["count"]), "unique_actors": int(r["unique_actors"])}
            for r in rows
        ],
    }


def get_skill_invocation_history(state: StateHandle, skill_name: str) -> list[dict[str, Any]]:
    path = state.events_sqlite
    if not path.is_file():
        return []

    query = (
        "SELECT event_id, ts, event, actor_kind, actor_name, session_id, parent_event_id "
        "FROM events WHERE actor_name = ? ORDER BY ts ASC"
    )
    with _with_conn(path) as conn:
        rows = _query_as_dicts(conn, query, (str(skill_name),))
    if rows:
        return [_row_to_dict(row) for row in rows]

    # Fallback for readers that still persist skill in raw JSON events.
    events = _read_json(state.events_jsonl)
    if events is None or not isinstance(events, list):
        return []
    out: list[dict[str, Any]] = []
    for row in events:
        if not isinstance(row, dict):
            continue
        if row.get("skill") == skill_name:
            out.append(_row_to_dict(row))
    return out
