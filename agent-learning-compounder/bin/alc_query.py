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
from typing import Any, Literal

try:
    from state_handle import StateHandle, user_reports_dir, validate_read_scope
except ImportError:  # pragma: no cover
    from bin.state_handle import StateHandle, user_reports_dir, validate_read_scope

try:
    import proposal_lifecycle
except ImportError:  # pragma: no cover
    from bin import proposal_lifecycle

try:
    import gate_registry
except ImportError:  # pragma: no cover
    from bin import gate_registry


_DURATION_RE = re.compile(r"^(\d+)([smhdw])$", re.I)
_ALLOWED_KIND_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_NOW = dt.datetime.now


# Scope model — see ARCHITECTURE.md § 4. Validation and user report path
# selection are owned by state_handle so read and write callers share one
# vocabulary.
Scope = Literal["user", "project", "both"]


class QueryError(RuntimeError):
    pass


def _validate_scope(scope: str) -> str:
    try:
        return validate_read_scope(scope)
    except ValueError as exc:
        raise QueryError(str(exc)) from exc


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


def _parse_gates_markdown(text: str, *, source: str) -> list[dict[str, Any]]:
    try:
        rows: list[dict[str, Any]] = []
        for block in gate_registry.parse_gate_blocks(text):
            row: dict[str, Any] = {
                "domain": block.domain,
                "gate_id": block.gate_id,
                "category": block.gate_category,
                "gate": block.gate,
                "_source_scope": source,
            }
            if block.previous_gate_ids:
                row["previous_gate_ids"] = list(block.previous_gate_ids)
            rows.append(row)
        return rows
    except ValueError:
        pass

    out: list[dict[str, Any]] = []
    for i, block in enumerate(text.split("\n- domain:")):
        if i == 0:
            continue
        lines = block.splitlines()
        if not lines:
            continue
        domain = lines[0].strip()
        row: dict[str, Any] = {"domain": domain, "_source_scope": source}
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
    return out


def get_gates(
    state: StateHandle | None = None,
    domain: str | None = None,
    *,
    scope: Scope = "project",
    user_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Approved gates, optionally scoped.

    ``scope="project"`` (default): read ``<state.reports_dir>/latest-approved-gates.md``
    — the per-repo register.
    ``scope="user"``: read ``<user_root>/reports/agent-learning/latest-approved-gates.md``
    — cross-repo learning produced by ``auto_distill_session``.
    ``scope="both"``: union, deduped by ``gate_id``; project entries win on conflict.

    ``domain`` filters the returned list by gate ``domain`` field.
    """
    _validate_scope(scope)
    rows: list[dict[str, Any]] = []
    if scope in ("project", "both"):
        if state is None:
            if scope == "project":
                raise QueryError("get_gates(scope='project') requires a StateHandle")
        else:
            path = _configured_path(
                state, "latest_approved_gates", state.reports_dir / "latest-approved-gates.md"
            )
            if path.is_file():
                rows.extend(_parse_gates_markdown(path.read_text(encoding="utf-8"), source="project"))
    if scope in ("user", "both"):
        path = user_reports_dir(user_root) / "latest-approved-gates.md"
        if path.is_file():
            user_rows = _parse_gates_markdown(path.read_text(encoding="utf-8"), source="user")
            if scope == "both":
                seen = {row.get("gate_id") for row in rows}
                for row in rows:
                    seen.update(row.get("previous_gate_ids") or [])
                user_rows = [row for row in user_rows if row.get("gate_id") not in seen]
            rows.extend(user_rows)
    if domain:
        rows = [gate for gate in rows if gate["domain"] == domain]
    return rows


def get_skill_context(
    state: StateHandle | None = None,
    *,
    scope: Scope = "project",
    user_root: Path | None = None,
) -> str:
    """Compact skill-context markdown for the given scope.

    Project scope returns the per-repo file. User scope returns the cross-repo
    file produced by ``auto_distill_session``. Both returns user followed by
    project, separated by a header so consumers can distinguish them.
    """
    _validate_scope(scope)
    parts: list[str] = []
    if scope in ("user", "both"):
        user_path = user_reports_dir(user_root) / "latest-skill-context.md"
        if user_path.is_file():
            text = user_path.read_text(encoding="utf-8")
            parts.append(f"<!-- scope: user -->\n{text}" if scope == "both" else text)
    if scope in ("project", "both"):
        if state is not None:
            project_path = _configured_path(
                state, "latest_skill_context", state.reports_dir / "latest-skill-context.md"
            )
            if project_path.is_file():
                text = project_path.read_text(encoding="utf-8")
                parts.append(f"<!-- scope: project -->\n{text}" if scope == "both" else text)
        elif scope == "project":
            raise QueryError("get_skill_context(scope='project') requires a StateHandle")
    return "\n\n".join(parts)


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


def get_apply_log(
    state: StateHandle,
    since: str | dt.datetime | int | float | None = None,
    kind_filter=None,
    *,
    scope: Scope = "project",
) -> list[dict[str, Any]]:
    """Patch apply events from project-scope events.sqlite.

    User-scope has no apply log (gates are written, not applied) so
    ``scope="user"`` returns ``[]`` and ``scope="both"`` is equivalent to
    ``scope="project"``.
    """
    _validate_scope(scope)
    if scope == "user":
        return []
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


def get_outcomes(
    state: StateHandle,
    since: str | dt.datetime | int | float | None = None,
    *,
    scope: Scope = "project",
) -> list[dict[str, Any]]:
    """Eval-verdict outcomes from project-scope events.sqlite.

    Eval outcomes are project-bound. ``scope="user"`` returns ``[]``.
    """
    _validate_scope(scope)
    if scope == "user":
        return []
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


def get_recommendations(
    state: StateHandle,
    *,
    scope: Scope = "project",
) -> list[dict[str, Any]]:
    """Analyst recommendations for this project.

    Recommendations are produced from project-scope events. ``scope="user"``
    returns ``[]``.
    """
    _validate_scope(scope)
    if scope == "user":
        return []
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


def get_pending_patches(
    state: StateHandle,
    *,
    scope: Scope = "project",
) -> list[dict[str, Any]]:
    """Patch bundles awaiting operator review for this project.

    Patches are emitted by project-scope recommenders. ``scope="user"`` returns ``[]``.
    """
    _validate_scope(scope)
    if scope == "user":
        return []
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


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return str(value)


def get_suggestions(
    state: StateHandle,
    *,
    scope: Scope = "project",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Dashboard suggestions from project-scope recommender artifacts.

    Suggestions are generated from project analysis. ``scope="user"`` returns
    ``[]``. Missing, malformed, or non-list artifacts also return ``[]`` so
    dashboard callers can render cold-state empty UI deterministically.
    """
    _validate_scope(scope)
    if scope == "user":
        return []

    data = _read_json(state.repo_state_dir / "suggestions.json")
    rows = data.get("suggestions") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []

    bounded = rows[: max(0, int(limit))] if limit else rows
    out: list[dict[str, Any]] = []
    for row in bounded:
        if isinstance(row, dict):
            safe = _json_safe(row)
            out.append(safe if isinstance(safe, dict) else {})
    return out


def get_proposal_queue(
    state: StateHandle,
    *,
    scope: Scope = "project",
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Operator proposal queue rows from project-scope lifecycle state.

    The improvement queue is written by proposal tools. ``scope="user"``
    returns ``[]`` because proposal review state is repo-local.
    """
    _validate_scope(scope)
    if scope == "user":
        return []
    return proposal_lifecycle.read_proposal_queue(state, status=status, limit=limit)


def get_proposal_lifecycle(
    state: StateHandle,
    *,
    scope: Scope = "project",
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Normalized proposal lifecycle rows from queue, patch, and suggestion artifacts.

    This is a read mirror over existing artifacts, not a second write source.
    ``scope="user"`` returns ``[]`` because lifecycle artifacts are project-bound.
    """
    _validate_scope(scope)
    if scope == "user":
        return []
    return proposal_lifecycle.read_lifecycle_state(state, limit=limit)


def get_event_dag(
    state: StateHandle,
    session_id: str,
    *,
    scope: Scope = "project",
) -> dict[str, Any]:
    """Event DAG for ``session_id`` from project-scope events.sqlite.

    Sessions are project-scope. ``scope="user"`` returns an empty DAG.
    """
    _validate_scope(scope)
    if scope == "user":
        return {"session_id": session_id, "nodes": []}
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


def get_actor_summary(
    state: StateHandle,
    since: str = "7d",
    *,
    scope: Scope = "project",
) -> dict[str, Any]:
    """Per-actor counts from project-scope events.sqlite.

    Actor telemetry is project-bound. ``scope="user"`` returns an empty summary.
    """
    _validate_scope(scope)
    if scope == "user":
        return {"since": since, "total": 0, "by_actor_kind": [], "last_activity_iso": None}
    path = state.events_sqlite
    if not path.is_file():
        return {"since": since, "total": 0, "by_actor_kind": [], "last_activity_iso": None}

    cutoff = _parse_since(since)
    sql = "SELECT actor_kind, COUNT(*) AS count, COUNT(DISTINCT actor_name) AS unique_actors"
    sql += " FROM events"
    params: list[Any] = []
    if cutoff is not None:
        sql += " WHERE ts >= ?"
        params.append(cutoff)
    sql += " GROUP BY actor_kind ORDER BY actor_kind"

    last_sql = "SELECT MAX(ts) AS last_ts FROM events"
    if cutoff is not None:
        last_sql += " WHERE ts >= ?"

    with _with_conn(path) as conn:
        rows = _query_as_dicts(conn, sql, tuple(params))
        last_row = _query_as_dicts(conn, last_sql, tuple(params))

    last_ts = last_row[0]["last_ts"] if last_row and last_row[0].get("last_ts") else None

    return {
        "since": since,
        "total": sum(int(r["count"]) for r in rows),
        "by_actor_kind": [
            {"actor_kind": r["actor_kind"], "count": int(r["count"]), "unique_actors": int(r["unique_actors"])}
            for r in rows
        ],
        "last_activity_iso": last_ts,
    }


def get_skill_usage_summary(
    state: StateHandle,
    since: str | dt.datetime | int | float | None = None,
    prefix_filter: list[str] | tuple[str, ...] | None = None,
    *,
    scope: Scope = "project",
) -> list[dict[str, Any]]:
    """Aggregate actor_name counts in the indexed events.

    Buckets by `actor_name` (the actor surface that closest tracks a "skill"
    in our schema), filtered to actors whose name starts with any of the
    optional prefixes. Returns rows sorted by count desc.

    When events.sqlite is absent (fresh install), returns []. When the
    `actor_name` column exists but holds no rows matching the filter,
    returns []. Callers are expected to render "no data yet" rather than
    error.

    Output row shape: `{actor_name, count, last_used_ts}`.

    Skill usage is project-scope. ``scope="user"`` returns ``[]``.
    """
    _validate_scope(scope)
    if scope == "user":
        return []
    path = state.events_sqlite
    if not path.is_file():
        return []

    where: list[str] = ["actor_name IS NOT NULL", "actor_name != ''"]
    params: list[Any] = []
    cutoff = _parse_since(since)
    if cutoff is not None:
        where.append("ts >= ?")
        params.append(cutoff)

    sql = (
        "SELECT actor_name, COUNT(*) AS count, MAX(ts) AS last_used_ts "
        "FROM events WHERE " + " AND ".join(where) +
        " GROUP BY actor_name ORDER BY count DESC, actor_name ASC"
    )

    with _with_conn(path) as conn:
        rows = _query_as_dicts(conn, sql, tuple(params))

    if prefix_filter:
        prefixes = tuple(p for p in prefix_filter if isinstance(p, str) and p)
        if prefixes:
            rows = [r for r in rows if any(r["actor_name"].startswith(p) for p in prefixes)]

    return [
        {"actor_name": r["actor_name"], "count": int(r["count"]),
         "last_used_ts": r["last_used_ts"]}
        for r in rows
    ]


def get_skill_invocation_history(
    state: StateHandle,
    skill_name: str,
    *,
    scope: Scope = "project",
) -> list[dict[str, Any]]:
    """Skill invocation events from project-scope events.sqlite.

    Invocations are project-bound. ``scope="user"`` returns ``[]``.
    """
    _validate_scope(scope)
    if scope == "user":
        return []
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
