#!/usr/bin/env python3
"""Domain payload construction for markdown and HTML learning reports."""

from __future__ import annotations

import datetime as dt
import json
import pathlib
from typing import Any

from distill_learning import (
    DEFAULT_DOMAIN_PRESET,
    assistant_lines,
    classify_events,
    clean_user_messages,
    evidence_label,
    event_level,
    event_source,
    find_preference_evidence,
    load_domain_rules,
    meta_lines,
    packaged_domain_rules_path,
    prior_report_context,
    quote,
    skill_map_from_baseline,
)


def load_muted_domains(personal: pathlib.Path) -> set[str]:
    """Read the dashboard's muted-domains.json. Safe on missing/invalid file."""
    path = personal / "actions" / "muted-domains.json"
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(data, list):
        return set()
    return {
        (item.get("domain") or "").strip()
        for item in data
        if isinstance(item, dict) and (item.get("domain") or "").strip()
    }


def build_report_payload(
    corpus: str,
    baseline: dict,
    mode: str,
    personal: pathlib.Path | None = None,
    skill_map: dict | None = None,
    skill_usage: dict | None = None,
    skill_impact: dict | None = None,
    domain_rules: list[dict] | None = None,
    domain_rules_source: pathlib.Path | None = None,
) -> dict:
    """Compute the structured report payload shared by renderers."""
    domain_rules = domain_rules or load_domain_rules(packaged_domain_rules_path(DEFAULT_DOMAIN_PRESET))
    today = dt.date.today().isoformat()
    user_messages = clean_user_messages(corpus)
    u_lines = [message.text for message in user_messages]
    a_lines = assistant_lines(corpus)
    corpus_meta = meta_lines(corpus)
    evidence = find_preference_evidence(u_lines, domain_rules)
    checked_sources = baseline.get("source_files", []) + baseline.get("skills", [])
    source_evidence = baseline.get("source_evidence") or [
        {"fact": f"`{path}` exists as a repo source-of-truth file.", "source": f"{path}:1"}
        for path in baseline.get("source_files", [])
    ]
    instruction_evidence = baseline.get("instruction_evidence", [])
    skill_evidence = baseline.get("skill_evidence") or [
        {"path": path, "source": f"{path}:1"} for path in baseline.get("skills", [])
    ]
    validation_evidence = baseline.get("validation_evidence") or [
        {"command": command, "source": "package.json:1"} for command in baseline.get("validation_commands", [])
    ]
    map_rows = classify_events(baseline, user_messages, domain_rules)
    if personal:
        muted = load_muted_domains(personal)
        if muted:
            map_rows = [row for row in map_rows if row.get("domain") not in muted]
        prior_report, level_changes = prior_report_context(personal, map_rows)
        from distill_learning import evergreen_proposals

        proposed_evergreen = evergreen_proposals(personal, baseline, u_lines)
    else:
        prior_report = None
        level_changes = []
        proposed_evergreen = []

    skill_map = skill_map or skill_map_from_baseline(baseline)
    skill_usage = skill_usage or {}
    skill_impact = skill_impact or {}

    rows_serialized = []
    for row in map_rows:
        rows_serialized.append({
            "domain": row["domain"],
            "level": event_level(row),
            "count": row["count"],
            "source_count": row.get("source_count", 0),
            "session_refs": list(row.get("session_refs", [])),
            "failure_signal": row["failure_signal"],
            "gate": row["gate"],
            "gate_category": row["category"],
            "quote": row["quotes"][0] if row.get("quotes") else "",
            "evidence_label": evidence_label(row),
            "evidence_source": event_source(row),
        })

    valid_skills = [item for item in skill_map.get("skills", []) if item.get("valid", True)]
    invalid_skills = skill_map.get("invalid", [])
    missed = list(skill_usage.get("missed", []))
    failed = list(skill_usage.get("failed", []))
    expected = list(skill_usage.get("expected", []))
    loaded = list(skill_usage.get("loaded", []))
    applied = list(skill_usage.get("applied", []))
    impact_rows = [row for row in skill_impact.get("skills", []) if row.get("candidate_adjustment")]

    return {
        "date": today,
        "mode": mode,
        "repo": baseline.get("repo", "unknown"),
        "totals": {
            "user_lines": len(u_lines),
            "assistant_lines": len(a_lines),
            "corpus_meta": len(corpus_meta),
            "domain_rules": len(domain_rules),
            "gates": len(map_rows),
            "evidence_lines": sum(row["count"] for row in map_rows),
            "evidence_fallback": len(evidence),
            "skills_available": len(valid_skills),
            "skill_alerts": len(invalid_skills) + len(missed) + len(failed),
        },
        "corpus_meta": list(corpus_meta),
        "domain_rules": {
            "count": len(domain_rules),
            "source": str(domain_rules_source) if domain_rules_source else None,
        },
        "baseline_evidence": {
            "source": list(source_evidence),
            "purpose": list(baseline.get("purpose_evidence", [])),
            "entrypoint": list(baseline.get("entrypoint_evidence", [])),
            "planning": list(baseline.get("planning_evidence", [])),
            "stack": list(baseline.get("stack_evidence", [])),
            "gotcha": list(baseline.get("gotcha_evidence", [])),
            "instruction": list(instruction_evidence)[:30],
            "instruction_omitted": max(0, len(instruction_evidence) - 30),
            "skills": list(skill_evidence),
            "validation": list(validation_evidence),
            "has_checked_sources": bool(checked_sources or baseline.get("validation_commands")),
        },
        "memory_derived": {
            "rows": rows_serialized,
            "level_changes": list(level_changes),
            "evidence_fallback": [quote(item) for item in evidence],
            "had_data": bool(map_rows),
        },
        "needs_verification": [
            "Assistant claims in transcripts are not treated as current repo truth without live checks."
            if a_lines
            else "No assistant claims found. Re-run extraction if this is unexpected."
        ],
        "agent_compensation": {
            "rows": rows_serialized,
            "default": "Use read-only exploration before recommendations." if not map_rows else None,
        },
        "self_healing_loop": {
            "top": rows_serialized[0] if rows_serialized else None,
            "fallback": None if rows_serialized else "No repeated failure signal found; keep dry-run report advisory.",
        },
        "skill_inventory": {
            "available_count": len(valid_skills),
            "invalid_count": len(invalid_skills),
            "rows": [
                {"name": item.get("name", "unknown"), "path": item.get("path", "")}
                for item in valid_skills[:12]
            ],
            "omitted": max(0, len(valid_skills) - 12),
        },
        "skill_usage": {
            "expected": expected,
            "loaded": loaded,
            "applied": applied,
        },
        "skill_health": {
            "invalid": [item.get("path") or item.get("name", "unknown") for item in invalid_skills],
            "missed": missed,
            "failed_to_apply": failed,
        },
        "skill_compensation": {
            "rows": [
                {
                    "skill": row.get("skill", "unknown"),
                    "signal": row.get("impact_signal", "needs_review"),
                    "gate": row.get("candidate_adjustment", ""),
                    "count": row.get("expected_sessions", row.get("missed_sessions", 1)),
                }
                for row in impact_rows
            ],
        },
        "next_agent_brief": next_agent_brief(rows_serialized),
        "proposed_evergreen": list(proposed_evergreen),
        "prior_report_path": str(prior_report) if prior_report else None,
    }


def next_agent_brief(rows: list[dict[str, Any]]) -> list[str]:
    items = [
        "Start by reading repo-local instruction files and skill inventory.",
        "Treat transcript-derived memories as advisory until verified in the current checkout.",
    ]
    if rows:
        for row in rows[:5]:
            items.append(f"{row['domain']}: {row['gate']}")
    else:
        items.append("Convert repeated corrections into gates, not personality claims.")
    items.append("Do not append durable personalization unless validation passes and --write was requested.")
    return items
