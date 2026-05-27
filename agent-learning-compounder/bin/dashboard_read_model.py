#!/usr/bin/env python3
"""Shared dashboard read-model assembly.

This module is intentionally read-only. FastAPI action endpoints, proposal
writers, patch mutation, and distill job orchestration stay in the dashboard
action layer.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
import time
from typing import Any

try:
    import alc_query
    from state_handle import StateHandle
except ImportError:  # pragma: no cover
    from bin import alc_query
    from bin.state_handle import StateHandle


REPORT_PAYLOAD_RE = re.compile(
    r'<script[^>]*id="report-payload"[^>]*>(.*?)</script>',
    re.DOTALL,
)

STDLIB_SECTIONS = [
    "recommendations",
    "pending_patches",
    "anomalies",
    "patterns",
    "correlations",
    "apply_log",
    "gates_and_insights",
    "suggestions",
]


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return str(value)


def _safe_read(label: str, fallback: Any, fn) -> Any:
    try:
        return _json_safe(fn())
    except Exception as error:  # noqa: BLE001 - dashboard reads degrade to diagnostics.
        if isinstance(fallback, dict):
            value = dict(fallback)
            value["_error"] = label
            value["detail"] = str(error)
            return value
        return fallback


def _read_text(path: pathlib.Path) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _file_bytes(path: pathlib.Path) -> int:
    try:
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0


def find_latest_payload(personal: pathlib.Path) -> dict[str, Any] | None:
    """Read the most recent report's embedded payload."""
    target_dir = pathlib.Path(personal) / "reports" / "agent-learning"
    if not target_dir.is_dir():
        return None
    candidates = sorted(
        (
            path
            for path in target_dir.glob("*.html")
            if path.name not in {"latest-report.html", "latest-dashboard.html"}
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    latest_report = target_dir / "latest-report.html"
    if latest_report.is_file():
        candidates.insert(0, latest_report)
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        match = REPORT_PAYLOAD_RE.search(text)
        if not match:
            continue
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return _json_safe(payload)
    return None


def read_history(personal: pathlib.Path, limit: int) -> list[dict[str, Any]]:
    metrics = pathlib.Path(personal) / "reports" / "agent-learning" / "metrics.jsonl"
    if not metrics.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = metrics.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(_json_safe(row))
    return rows[-limit:] if limit else rows


def build_archive_model(personal: pathlib.Path, history_limit: int = 180) -> dict[str, Any]:
    personal = pathlib.Path(personal).expanduser().resolve()
    report_dir = personal / "reports" / "agent-learning"
    metrics = report_dir / "metrics.jsonl"
    latest = find_latest_payload(personal)
    history = read_history(personal, history_limit)
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "personal_root": str(personal),
        "latest": latest,
        "history": history,
        "archive_diagnostics": {
            "reports_dir": str(report_dir),
            "reports_dir_present": report_dir.is_dir(),
            "metrics_jsonl_present": metrics.is_file(),
            "metrics_jsonl_bytes": _file_bytes(metrics),
            "latest_present": latest is not None,
            "history_rows": len(history),
        },
    }


def build_static_payload(personal: pathlib.Path, history_limit: int = 180) -> dict[str, Any]:
    return build_archive_model(personal, history_limit=history_limit)


def build_scoped_gates(state: StateHandle | None, *, user_root: pathlib.Path | None = None) -> dict[str, Any]:
    try:
        if state is not None:
            rows = alc_query.get_gates(state, scope="both", user_root=user_root)
            skill_context_md = alc_query.get_skill_context(state, scope="both", user_root=user_root)
        else:
            rows = alc_query.get_gates(scope="user", user_root=user_root)
            skill_context_md = alc_query.get_skill_context(scope="user", user_root=user_root)
    except Exception:
        rows, skill_context_md = [], ""

    rows = _json_safe(rows)
    if not isinstance(rows, list):
        rows = []
    summary = {
        "total": len(rows),
        "user": sum(1 for row in rows if isinstance(row, dict) and row.get("_source_scope") == "user"),
        "project": sum(1 for row in rows if isinstance(row, dict) and row.get("_source_scope") == "project"),
    }
    return {
        "rows": rows,
        "summary": summary,
        "skill_context_md": skill_context_md,
    }


def _project_diagnostics(state: StateHandle) -> dict[str, Any]:
    hook_events = state.repo_state_dir / "hook-events.jsonl"
    diagnostics = {
        "repo_state": str(state.repo_state_dir),
        "events_sqlite": str(state.events_sqlite),
        "events_sqlite_present": state.events_sqlite.is_file(),
        "events_sqlite_bytes": _file_bytes(state.events_sqlite),
        "events_jsonl_present": state.events_jsonl.is_file(),
        "events_jsonl_bytes": _file_bytes(state.events_jsonl),
        "hook_events_present": hook_events.is_file(),
        "hook_events_bytes": _file_bytes(hook_events),
    }
    reasons: list[str] = []
    if not diagnostics["events_sqlite_present"]:
        reasons.append("events.sqlite is missing")
    elif diagnostics["events_sqlite_bytes"] == 0:
        reasons.append("events.sqlite is empty")
    if not diagnostics["events_jsonl_present"] and not diagnostics["hook_events_present"]:
        reasons.append("no raw event artifacts are present")
    diagnostics["cold_state_reasons"] = reasons
    return diagnostics


def build_project_read_surface(state: StateHandle | None) -> dict[str, Any] | None:
    if state is None:
        return None

    recommendations = _safe_read("recommendations", [], lambda: alc_query.get_recommendations(state))
    pending_patches = _safe_read("pending_patches", [], lambda: alc_query.get_pending_patches(state))
    apply_log = _safe_read("apply_log", [], lambda: alc_query.get_apply_log(state, since="30d"))
    outcomes = _safe_read("outcomes", [], lambda: alc_query.get_outcomes(state, since="30d"))
    skill_usage = _safe_read("skill_usage", [], lambda: alc_query.get_skill_usage_summary(state, since="30d"))
    suggestions = _safe_read("suggestions", [], lambda: alc_query.get_suggestions(state))
    actor_summary = _safe_read(
        "actor_summary",
        {"since": "7d", "total": 0, "by_actor_kind": [], "last_activity_iso": None},
        lambda: alc_query.get_actor_summary(state, since="7d"),
    )

    return {
        "actor_summary": actor_summary,
        "recommendations": recommendations[:25] if isinstance(recommendations, list) else recommendations,
        "pending_patches": pending_patches[:25] if isinstance(pending_patches, list) else pending_patches,
        "apply_log": apply_log[-25:] if isinstance(apply_log, list) else apply_log,
        "outcomes": outcomes[-25:] if isinstance(outcomes, list) else outcomes,
        "skill_usage": skill_usage[:25] if isinstance(skill_usage, list) else skill_usage,
        "suggestions": suggestions[:25] if isinstance(suggestions, list) else suggestions,
        "diagnostics": _project_diagnostics(state),
    }


def build_fastapi_payload(
    personal: pathlib.Path,
    *,
    state: StateHandle | None = None,
    history_limit: int = 180,
) -> dict[str, Any]:
    payload = build_archive_model(personal, history_limit=history_limit)
    payload["scoped_gates"] = build_scoped_gates(state, user_root=pathlib.Path(personal))
    payload["read_surface"] = build_project_read_surface(state)
    return payload


def _bucket_recommendations(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    buckets = {name: [] for name in ("anomalies", "patterns", "correlations")}
    for row in rows:
        kind = str(row.get("kind", "")).lower()
        if "anomaly" in kind:
            buckets["anomalies"].append(row)
            continue
        if "pattern" in kind:
            buckets["patterns"].append(row)
            continue
        if "correlation" in kind or "dag" in kind:
            buckets["correlations"].append(row)
            continue
    return buckets


def build_stdlib_payload(
    state: StateHandle,
    *,
    user_root: pathlib.Path | None = None,
) -> dict[str, Any]:
    recommendations = _safe_read("recommendations", [], lambda: alc_query.get_recommendations(state))
    if not isinstance(recommendations, list):
        recommendations = []
    rec_buckets = _bucket_recommendations(recommendations)

    gates_rows = _safe_read("gates", [], lambda: alc_query.get_gates(state, scope="both", user_root=user_root))
    if not isinstance(gates_rows, list):
        gates_rows = []
    insights_markdown = _safe_read(
        "skill_context",
        "",
        lambda: alc_query.get_skill_context(state, scope="both", user_root=user_root),
    )
    if not isinstance(insights_markdown, str):
        insights_markdown = ""
    gates_markdown = _read_text(state.reports_dir / "latest-approved-gates.md")
    gates_summary = {
        "total": len(gates_rows),
        "user": sum(1 for row in gates_rows if isinstance(row, dict) and row.get("_source_scope") == "user"),
        "project": sum(1 for row in gates_rows if isinstance(row, dict) and row.get("_source_scope") == "project"),
    }

    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "recommendations": recommendations,
        "pending_patches": _safe_read("pending_patches", [], lambda: alc_query.get_pending_patches(state)),
        "anomalies": rec_buckets["anomalies"],
        "patterns": rec_buckets["patterns"],
        "correlations": rec_buckets["correlations"],
        "apply_log": _safe_read("apply_log", [], lambda: alc_query.get_apply_log(state)),
        "gates_and_insights": {
            "gates_markdown": gates_markdown,
            "insights_markdown": insights_markdown,
            "gates_rows": gates_rows,
            "gates_summary": gates_summary,
            "actor_summary": _safe_read("actor_summary", {}, lambda: alc_query.get_actor_summary(state)),
        },
        "suggestions": _safe_read("suggestions", [], lambda: alc_query.get_suggestions(state)),
        "sections": list(STDLIB_SECTIONS),
    }
