#!/usr/bin/env python3
"""Shared SQLite query library for analyst scripts.

The module keeps all SQL in one place so analyst scripts can share query
definitions and test contract shape expectations together.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import sqlite3
from collections.abc import Callable
from typing import Any

EXPECTED_SCHEMA_VERSION = 4
EVENT_SCHEMA_COLUMNS = [
    "event_id",
    "ts",
    "event",
    "schema_version",
    "actor_kind",
    "actor_name",
    "actor_model",
    "actor_parent_actor_id",
    "telemetry_duration_ms",
    "telemetry_tokens_in",
    "telemetry_tokens_out",
    "telemetry_cache_read_tokens",
    "telemetry_cache_creation_tokens",
    "telemetry_cost_usd",
    "telemetry_interrupted",
    "correlation_chain",
    "parent_event_id",
    "tool_server",
    "error_class",
    "session_id",
]


def _state_path(state_handle: Any, attr: str, *, required: bool = True) -> pathlib.Path | None:
    if hasattr(state_handle, attr):
        value = getattr(state_handle, attr)
        return pathlib.Path(value)
    if required:
        raise ValueError(f"state handle missing {attr}")
    return None


def open_events_db(state_handle: Any) -> sqlite3.Connection:
    """Open events.sqlite in read-only mode and validate schema_version.

    Accepts either a StateHandle-like object with ``events_sqlite`` or a direct
    path-like to a db file.
    """
    db_path = _state_path(state_handle, "events_sqlite")
    if db_path is None:
        db_path = pathlib.Path(state_handle)

    if not db_path.is_file():
        raise FileNotFoundError(f"events.sqlite not found: {db_path}")

    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        _validate_schema_version(conn, db_path)
    except Exception:
        conn.close()
        raise
    return conn


def _validate_schema_version(conn: sqlite3.Connection, path: pathlib.Path) -> None:
    row = conn.execute("SELECT value FROM events_meta WHERE key='schema_version'").fetchone()
    if row is None:
        conn.close()
        raise RuntimeError(
            f"events.sqlite missing events_meta.schema_version: {path}"
        )
    try:
        version = int(row[0])
    except (TypeError, ValueError):
        raise RuntimeError(f"events.sqlite has non-integer schema_version: {path}")

    if version != EXPECTED_SCHEMA_VERSION:
        raise RuntimeError(
            f"events.sqlite schema_version mismatch: expected {EXPECTED_SCHEMA_VERSION}, found {version}"
        )


def _fetch(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cursor = conn.execute(sql, params)
    return [dict(row) for row in cursor.fetchall()]


def query_q1_longest_by_skill(conn: sqlite3.Connection, *, min_events: int = 1) -> list[dict[str, Any]]:
    rows = _fetch(
        conn,
        """
        SELECT
            actor_name AS skill,
            event AS event_name,
            COUNT(*) AS sample_count,
            MIN(telemetry_duration_ms) AS min_duration_ms,
            MAX(telemetry_duration_ms) AS max_duration_ms,
            ROUND(AVG(COALESCE(telemetry_duration_ms, 0.0)), 3) AS avg_duration_ms
        FROM events
        WHERE actor_name IS NOT NULL
          AND telemetry_duration_ms IS NOT NULL
        GROUP BY actor_name, event
        HAVING sample_count >= ?
        ORDER BY avg_duration_ms DESC
        """,
        (min_events,),
    )
    return rows


def query_q2_model_overkill(conn: sqlite3.Connection, *, min_events: int = 1) -> list[dict[str, Any]]:
    rows = _fetch(
        conn,
        """
        SELECT
            actor_model AS model,
            actor_name AS skill,
            COUNT(*) AS sample_count,
            ROUND(SUM(COALESCE(telemetry_cost_usd, 0.0)), 3) AS total_cost_usd,
            ROUND(AVG(COALESCE(telemetry_cost_usd, 0.0)), 3) AS avg_cost_usd,
            ROUND(
                AVG(
                    CASE
                        WHEN COALESCE(telemetry_interrupted, 0) = 1 OR error_class IS NOT NULL THEN 0.0
                        ELSE 1.0
                    END
                )
            , 3) AS pass_rate
        FROM events
        WHERE actor_model IS NOT NULL
          AND actor_name IS NOT NULL
        GROUP BY actor_model, actor_name
        HAVING sample_count >= ?
        ORDER BY total_cost_usd DESC
        """,
        (min_events,),
    )
    return rows


def query_q3_dag_subagent_cost(conn: sqlite3.Connection, *, min_events: int = 1) -> list[dict[str, Any]]:
    rows = _fetch(
        conn,
        """
        SELECT
            p.actor_name AS parent_actor,
            c.actor_name AS child_actor,
            c.actor_model AS child_model,
            COUNT(*) AS event_count,
            ROUND(AVG(COALESCE(c.telemetry_duration_ms, 0.0)), 3) AS avg_child_duration_ms,
            ROUND(SUM(COALESCE(c.telemetry_cost_usd, 0.0)), 3) AS total_child_cost_usd
        FROM events AS c
        JOIN events AS p
          ON c.parent_event_id = p.event_id
        GROUP BY p.actor_name, c.actor_name, c.actor_model
        HAVING event_count >= ?
        ORDER BY total_child_cost_usd DESC
        """,
        (min_events,),
    )
    return rows


def query_q4_background_failure(conn: sqlite3.Connection, *, min_events: int = 1) -> list[dict[str, Any]]:
    return _fetch(
        conn,
        """
        SELECT
            actor_name AS actor,
            COUNT(*) AS sample_count,
            SUM(CASE WHEN COALESCE(telemetry_interrupted, 0) = 1 OR error_class IS NOT NULL THEN 1 ELSE 0 END) AS error_count,
            ROUND(AVG(COALESCE(telemetry_duration_ms, 0.0)), 3) AS avg_duration_ms,
            ROUND(SUM(COALESCE(telemetry_cost_usd, 0.0)), 3) AS total_cost_usd
        FROM events
        WHERE actor_kind = 'background_agent'
          AND actor_name IS NOT NULL
        GROUP BY actor_name
        HAVING sample_count >= ?
        ORDER BY error_count DESC
        """,
        (min_events,),
    )


def query_q5_gate_effectiveness(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return _fetch(
        conn,
        """
        WITH loaded_gates AS (
            SELECT DISTINCT
                session_id,
                actor_name AS gate_id
            FROM events
            WHERE event = 'session_start'
              AND actor_name IS NOT NULL
              AND session_id IS NOT NULL
        ),
        gate_tools AS (
            SELECT
                lg.gate_id,
                pt.event_id AS tool_event_id,
                pt.telemetry_interrupted,
                pt.error_class,
                pt.actor_name AS tool_actor
            FROM loaded_gates AS lg
            JOIN events AS pt
              ON pt.session_id = lg.session_id
             AND pt.event = 'post_tool_use'
        )
        SELECT
            gate_id,
            COUNT(tool_event_id) AS n_loaded_tools,
            SUM(CASE WHEN error_class IS NOT NULL OR COALESCE(telemetry_interrupted, 0) = 1 THEN 1 ELSE 0 END) AS n_error,
            ROUND(
                CASE
                    WHEN COUNT(tool_event_id) > 0
                        THEN 1.0 - CAST(SUM(CASE WHEN error_class IS NOT NULL OR COALESCE(telemetry_interrupted, 0) = 1 THEN 1 ELSE 0 END) AS REAL) / COUNT(tool_event_id)
                    ELSE 0.0
                END
            , 3) AS pass_rate
        FROM gate_tools
        GROUP BY gate_id
        HAVING n_loaded_tools > 0
        ORDER BY gate_id
        """,
    )


def query_q6_time_of_day_sessions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return _fetch(
        conn,
        """
        WITH session_span AS (
            SELECT
                session_id,
                actor_name,
                MIN(ts) AS session_start,
                MAX(ts) AS session_end
            FROM events
            WHERE session_id IS NOT NULL
              AND actor_name IS NOT NULL
            GROUP BY session_id, actor_name
            HAVING session_start IS NOT NULL AND session_end IS NOT NULL
        )
        SELECT
            actor_name,
            CAST(STRFTIME('%H', session_start) AS INTEGER) AS hour_of_day,
            COUNT(*) AS session_count,
            ROUND(AVG((JULIANDAY(session_end)-JULIANDAY(session_start)) * 86400.0), 3) AS avg_session_seconds,
            MIN((JULIANDAY(session_end)-JULIANDAY(session_start)) * 86400.0) AS min_session_seconds,
            MAX((JULIANDAY(session_end)-JULIANDAY(session_start)) * 86400.0) AS max_session_seconds
        FROM session_span
        GROUP BY actor_name, hour_of_day
        ORDER BY actor_name, hour_of_day
        """,
    )


def query_q7_tool_server_bottlenecks(conn: sqlite3.Connection, *, min_events: int = 1) -> list[dict[str, Any]]:
    return _fetch(
        conn,
        """
        SELECT
            tool_server,
            COUNT(*) AS sample_count,
            ROUND(AVG(COALESCE(telemetry_duration_ms, 0.0)), 3) AS avg_duration_ms,
            ROUND(MIN(COALESCE(telemetry_duration_ms, 0.0)), 3) AS min_duration_ms,
            ROUND(MAX(COALESCE(telemetry_duration_ms, 0.0)), 3) AS max_duration_ms
        FROM events
        WHERE tool_server IS NOT NULL
        GROUP BY tool_server
        HAVING sample_count >= ?
        ORDER BY avg_duration_ms DESC
        """,
        (min_events,),
    )


def query_q8_frustration_pairs(conn: sqlite3.Connection, *, seconds: int = 30) -> list[dict[str, Any]]:
    return _fetch(
        conn,
        f"""
        WITH stop_events AS (
            SELECT event_id AS stop_event_id, session_id, ts
            FROM events
            WHERE event = 'stop'
              AND session_id IS NOT NULL
        )
        SELECT
            s.stop_event_id,
            s.session_id,
            COUNT(t.event_id) AS failed_tool_events_earlier_30s
        FROM stop_events AS s
        JOIN events AS t
          ON t.session_id = s.session_id
         AND t.event = 'post_tool_use'
         AND t.ts BETWEEN datetime(s.ts, '-' || CAST(? AS TEXT) || ' seconds') AND s.ts
         AND (t.error_class IS NOT NULL OR COALESCE(t.telemetry_interrupted, 0) = 1)
        GROUP BY s.stop_event_id, s.session_id
        HAVING failed_tool_events_earlier_30s > 0
        ORDER BY s.stop_event_id
        """,
        (seconds,),
    )


def query_q9_drift(conn: sqlite3.Connection, *, now: str | None = None) -> list[dict[str, Any]]:
    now_utc = now or dt.datetime.now(dt.timezone.utc).isoformat()
    return _fetch(
        conn,
        """
        WITH windows AS (
            SELECT
                actor_name AS skill,
                SUM(CASE WHEN ts >= datetime(?, '-30 days') THEN 1 ELSE 0 END) AS recent_count,
                SUM(CASE WHEN ts >= datetime(?, '-60 days') AND ts < datetime(?, '-30 days') THEN 1 ELSE 0 END) AS prior_count
            FROM events
            WHERE actor_name IS NOT NULL
              AND ts >= datetime(?, '-60 days')
            GROUP BY actor_name
        )
        SELECT
            skill,
            recent_count,
            prior_count,
            CAST(recent_count AS INTEGER) AS recent_count_int,
            CAST(prior_count AS INTEGER) AS prior_count_int,
            CASE
                WHEN prior_count > 0 THEN ROUND(CAST(recent_count AS REAL) / CAST(prior_count AS REAL), 3)
                ELSE NULL
            END AS ratio,
            CASE
                WHEN prior_count > 0 AND CAST(recent_count AS REAL) <= CAST(prior_count AS REAL) * 0.5 THEN 1
                ELSE 0
            END AS is_drifted
        FROM windows
        """,
        (now_utc, now_utc, now_utc, now_utc),
    )


def query_q10_eval_verdict_roi(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return _fetch(
        conn,
        """
        SELECT
            actor_name AS kind,
            COUNT(*) AS sample_count,
            ROUND(SUM(COALESCE(telemetry_cost_usd, 0.0)), 3) AS total_cost_usd,
            ROUND(AVG(COALESCE(telemetry_tokens_in, 0.0) + COALESCE(telemetry_tokens_out, 0.0)), 3) AS avg_tokens,
            SUM(CASE WHEN COALESCE(telemetry_interrupted, 0) = 1 OR error_class IS NOT NULL THEN 1 ELSE 0 END) AS failed_count
        FROM events
        WHERE event = 'eval_verdict'
        GROUP BY actor_name
        HAVING sample_count > 0
        ORDER BY total_cost_usd DESC
        """,
    )


def query_gate_with_evidence(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = _fetch(
        conn,
        """
        WITH loaded_gates AS (
            SELECT DISTINCT
                session_id,
                actor_name AS gate_id,
                ts AS started_at
            FROM events
            WHERE event = 'session_start'
              AND actor_name IS NOT NULL
              AND session_id IS NOT NULL
        ),
        gate_events AS (
            SELECT
                lg.gate_id,
                pt.event_id,
                pt.ts,
                pt.error_class,
                pt.telemetry_interrupted
            FROM loaded_gates AS lg
            JOIN events AS pt
              ON pt.session_id = lg.session_id
             AND pt.event = 'post_tool_use'
             AND pt.ts >= lg.started_at
        )
        SELECT
            gate_id,
            COUNT(event_id) AS n_loaded_tools,
            SUM(CASE WHEN error_class IS NOT NULL OR COALESCE(telemetry_interrupted, 0) = 1 THEN 1 ELSE 0 END) AS n_error,
            ROUND(
                CASE
                    WHEN COUNT(event_id) > 0
                        THEN 1.0 - CAST(SUM(CASE WHEN error_class IS NOT NULL OR COALESCE(telemetry_interrupted, 0) = 1 THEN 1 ELSE 0 END) AS REAL) / COUNT(event_id)
                    ELSE 0.0
                END
            , 3) AS pass_rate,
            GROUP_CONCAT(event_id) AS event_ids
        FROM gate_events
        GROUP BY gate_id
        HAVING n_loaded_tools > 0
        ORDER BY n_error DESC, n_loaded_tools DESC
        """,
    )
    for row in rows:
        raw_event_ids = row.get("event_ids")
        row["event_ids"] = [item for item in str(raw_event_ids).split(",") if item] if raw_event_ids else []
    return rows


def query_dag_parent_child_cost(conn: sqlite3.Connection, *, min_events: int = 1) -> list[dict[str, Any]]:
    rows = _fetch(
        conn,
        """
        WITH parent_map AS (
            SELECT
                event_id AS parent_event_id,
                actor_name AS parent_actor,
                actor_model AS parent_model
            FROM events
        ),
        child AS (
            SELECT
                p.parent_actor,
                c.actor_name AS child_actor,
                c.actor_model AS child_model,
                c.event_id AS child_event_id,
                c.parent_event_id,
                COALESCE(c.telemetry_duration_ms, 0) AS child_duration_ms,
                COALESCE(c.telemetry_cost_usd, 0.0) AS child_cost_usd
            FROM events AS c
            JOIN parent_map AS p
              ON c.parent_event_id = p.parent_event_id
            WHERE c.parent_event_id IS NOT NULL
              AND c.actor_name IS NOT NULL
        )
        SELECT
            parent_actor,
            child_actor,
            child_model,
            COUNT(*) AS event_count,
            ROUND(AVG(child_duration_ms), 3) AS avg_child_duration_ms,
            ROUND(SUM(child_cost_usd), 3) AS total_child_cost_usd,
            GROUP_CONCAT(child_event_id) AS event_ids
        FROM child
        GROUP BY parent_actor, child_actor, child_model
        HAVING event_count >= ?
        ORDER BY total_child_cost_usd DESC
        """,
        (min_events,),
    )
    for row in rows:
        raw_event_ids = row.get("event_ids")
        row["event_ids"] = [item for item in str(raw_event_ids).split(",") if item] if raw_event_ids else []
    return rows


def query_cache_hit_ratio(conn: sqlite3.Connection, *, min_samples: int = 1) -> list[dict[str, Any]]:
    rows = _fetch(
        conn,
        """
        SELECT
            session_id,
            actor_model,
            COUNT(*) AS sample_count,
            ROUND(SUM(COALESCE(telemetry_cache_read_tokens, 0)) * 1.0 / NULLIF(SUM(COALESCE(telemetry_tokens_in, 0)), 0), 3) AS cache_hit_ratio,
            ROUND(SUM(COALESCE(telemetry_duration_ms, 0.0)), 3) AS total_duration_ms
        FROM events
        WHERE session_id IS NOT NULL
          AND actor_model IS NOT NULL
          AND (telemetry_cache_read_tokens IS NOT NULL OR telemetry_tokens_in IS NOT NULL)
        GROUP BY session_id, actor_model
        HAVING sample_count >= ?
        ORDER BY cache_hit_ratio DESC
        """,
        (min_samples,),
    )
    return rows


def load_samples_rows(state_handle: Any) -> list[dict[str, Any]]:
    path = _state_path(state_handle, "repo_state_dir") / "samples.json"
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("samples") if isinstance(payload.get("samples"), list) else []
    else:
        return []
    return [row for row in rows if isinstance(row, dict)]


Q1 = {
    "id": "Q1",
    "name": "Which slash-command takes longest relative to its value?",
    "question": "Which slash-command takes longest relative to its value?",
    "sql": "SELECT ... FROM events ...",
    "shape": ["skill", "event_name", "sample_count", "avg_duration_ms", "min_duration_ms", "max_duration_ms"],
    "consumers": ["analyst_anomalies", "analyst_correlations"],
}


Q2 = {
    "id": "Q2",
    "name": "Which model is overkill for which skill (high cost, high pass-rate)?",
    "question": "Which model is overkill for which skill (high cost, high pass-rate)?",
    "sql": "SELECT ... FROM events ...",
    "shape": ["model", "skill", "sample_count", "total_cost_usd", "avg_cost_usd", "pass_rate"],
    "consumers": ["analyst_correlations"],
}


Q3 = {
    "id": "Q3",
    "name": "Which subagent dispatch patterns spawn most expensive subagents?",
    "question": "Which subagent dispatch patterns spawn most expensive subagents?",
    "sql": "SELECT ... FROM events ...",
    "shape": ["parent_actor", "child_actor", "child_model", "event_count", "avg_child_duration_ms", "total_child_cost_usd"],
    "consumers": ["analyst_correlations"],
}


Q4 = {
    "id": "Q4",
    "name": "Which background agents fail silently?",
    "question": "Which background agents fail silently?",
    "sql": "SELECT ... FROM events ...",
    "shape": ["actor", "sample_count", "error_count", "avg_duration_ms", "total_cost_usd"],
    "consumers": ["analyst_anomalies"],
}


Q5 = {
    "id": "Q5",
    "name": "Which gates load at SessionStart but never get used in same session?",
    "question": "Which gates load at SessionStart but never get used in same session?",
    "sql": "SELECT ... FROM events ...",
    "shape": ["gate_id", "n_loaded_tools", "n_error", "pass_rate"],
    "consumers": ["analyst_correlations"],
}


Q6 = {
    "id": "Q6",
    "name": "What time-of-day buckets have shortest/longest sessions?",
    "question": "What time-of-day buckets have shortest/longest sessions?",
    "sql": "SELECT ... FROM events ...",
    "shape": ["actor_name", "hour_of_day", "session_count", "avg_session_seconds", "min_session_seconds", "max_session_seconds"],
    "consumers": ["analyst_patterns"],
}


Q7 = {
    "id": "Q7",
    "name": "Which MCP servers are bottlenecks (avg duration_ms)?",
    "question": "Which MCP servers are bottlenecks (avg duration_ms)?",
    "sql": "SELECT ... FROM events ...",
    "shape": ["tool_server", "sample_count", "avg_duration_ms", "min_duration_ms", "max_duration_ms"],
    "consumers": ["analyst_anomalies"],
}


Q8 = {
    "id": "Q8",
    "name": "Frustration patterns: Stop within 30s after PostToolUse(error)?",
    "question": "Frustration patterns: Stop within 30s after PostToolUse(error)?",
    "sql": "SELECT ... FROM events ...",
    "shape": ["stop_event_id", "session_id", "failed_tool_events_earlier_30s"],
    "consumers": ["analyst_correlations"],
}


Q9 = {
    "id": "Q9",
    "name": "Which skills have drifted (loaded freq dropped >50% over 30d)?",
    "question": "Which skills have drifted (loaded freq dropped >50% over 30d)?",
    "sql": "SELECT ... FROM events ...",
    "shape": ["skill", "recent_count", "prior_count", "ratio", "is_drifted"],
    "consumers": ["analyst_patterns"],
}


Q10 = {
    "id": "Q10",
    "name": "Eval-loop ROI: cost of eval vs. quality of resulting recommendations?",
    "question": "Eval-loop ROI: cost of eval vs. quality of resulting recommendations?",
    "sql": "SELECT ... FROM events ...",
    "shape": ["kind", "sample_count", "total_cost_usd", "avg_tokens", "failed_count"],
    "consumers": ["analyst_correlations"],
}


Q11 = {
    "id": "Q11",
    "name": "Tool-use DAG parent-child support",
    "question": "DAG parent-child cost attribution",
    "sql": "SELECT ... FROM events ...",
    "shape": ["parent_actor", "child_actor", "child_model", "event_count", "avg_child_duration_ms", "total_child_cost_usd", "event_ids"],
    "consumers": ["analyst_correlations"],
}

Q12 = {
    "id": "Q12",
    "name": "Cache-hit ratio by session and model",
    "question": "Cache-hit ratio by session × model",
    "sql": "SELECT ... FROM events ...",
    "shape": ["session_id", "actor_model", "sample_count", "cache_hit_ratio", "total_duration_ms"],
    "consumers": ["analyst_correlations"],
}

QUERY_FUNCS: dict[str, Callable[..., list[dict[str, Any]]]] = {
    "Q1": query_q1_longest_by_skill,
    "Q2": query_q2_model_overkill,
    "Q3": query_q3_dag_subagent_cost,
    "Q4": query_q4_background_failure,
    "Q5": query_q5_gate_effectiveness,
    "Q6": query_q6_time_of_day_sessions,
    "Q7": query_q7_tool_server_bottlenecks,
    "Q8": query_q8_frustration_pairs,
    "Q9": query_q9_drift,
    "Q10": query_q10_eval_verdict_roi,
    "Q11": query_dag_parent_child_cost,
    "Q12": query_cache_hit_ratio,
}

def query_by_id(conn: sqlite3.Connection, query_id: str, **kwargs: Any) -> list[dict[str, Any]]:
    if not isinstance(query_id, str):
        raise ValueError("query_id must be string")
    fn = QUERY_FUNCS.get(query_id.upper())
    if fn is None:
        raise ValueError(f"unsupported query id: {query_id}")
    return fn(conn, **kwargs)


QUERIES = [Q1, Q2, Q3, Q4, Q5, Q6, Q7, Q8, Q9, Q10]
PROPOSALS: list[dict[str, Any]] = []
