"""Session-lifecycle synthesizer: next_action.

Library module — no CLI entry point.  Called by the MCP server via the
catalog auto-register pattern (M11).

Public API:

    next_action(repo, intent="auto", session_id=None) -> dict

Output schema (version 1):
    {
        "intent": "start" | "next" | "end" | "recap" | "leftoff" | "auto",
        "headline": str,               # 1-line summary
        "rationale": str,              # 2-3 sentences
        "suggested": {
            "skill":  str | None,
            "args":   str | None,
            "prompt": str,
        },
        "alternatives": [
            {"skill": str | None, "rationale": str},   # max 3
        ],
        "signals": {
            "pending_patches": int,
            "pending_recommendations": int,
            "recent_applies_7d": int,
            "recent_verdicts_7d": {"approve": int, "reject": int, "modify": int},
            "last_activity_iso": str | None,
        },
    }

Side effect: each call writes the result to
    <state-root>/repos/<repo-id>/reports/latest-next-action.json

Design rules (per Tom's stated synthesis discipline — KTD-21):
  - Never raw rows in output; counts + buckets + names only.
  - Reads exclusively through alc_query (the canonical read API).
  - Writes only the cached JSON file; no other side effects.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

try:
    from state_handle import StateHandle
    import alc_query
except ImportError:  # pragma: no cover
    import sys
    _BIN = Path(__file__).resolve().parent
    if str(_BIN) not in sys.path:
        sys.path.insert(0, str(_BIN))
    from state_handle import StateHandle
    import alc_query


# ---------------------------------------------------------------------------
# Intent normalisation
# ---------------------------------------------------------------------------

_INTENT_ALIASES: dict[str, str] = {
    "start":   "start",
    "begin":   "start",
    "next":    "next",
    "continue": "next",
    "end":     "end",
    "finish":  "end",
    "close":   "end",
    "recap":   "recap",
    "summary": "recap",
    "sum":     "recap",
    "leftoff": "leftoff",
    "left-off": "leftoff",
    "left_off": "leftoff",
    "wherewasi": "leftoff",
    "where": "leftoff",
    "auto":    "auto",
}

_VALID_INTENTS = frozenset({"start", "next", "end", "recap", "leftoff", "auto"})


def _normalise_intent(intent: str | None) -> str:
    if intent is None:
        return "auto"
    normalised = _INTENT_ALIASES.get(str(intent).strip().lower(), str(intent).strip().lower())
    if normalised not in _VALID_INTENTS:
        return "auto"
    return normalised


# ---------------------------------------------------------------------------
# Signal collection — all reads via alc_query
# ---------------------------------------------------------------------------

def _seven_days_ago() -> str:
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)
    return cutoff.isoformat()


def _collect_signals(state: StateHandle) -> dict[str, Any]:
    """Collect bucketed signals from the state.  Never raw rows.

    Reads project-scope state (events, patches, recommendations) and
    user-scope state (cross-repo approved gates) to inform synthesis.
    """
    # Pending patches (not rejected/deferred) — project-scope
    pending_patches = alc_query.get_pending_patches(state)
    pending_patch_count = len(pending_patches)
    # First pending patch id — used for the suggested args, not for dumping
    first_patch_id: str | None = pending_patches[0].get("patch_id") if pending_patches else None

    # Pending recommendations — project-scope
    recs = alc_query.get_recommendations(state)
    pending_rec_count = len(recs)

    # Approved gates — combined: cross-repo user-scope union project-scope
    gates_both = alc_query.get_gates(state, scope="both")
    gates_count = len(gates_both)
    gates_user_count = sum(1 for g in gates_both if g.get("_source_scope") == "user")
    gates_project_count = sum(1 for g in gates_both if g.get("_source_scope") == "project")

    # Recent apply events (7d) — project-scope
    applies_7d = alc_query.get_apply_log(state, since="7d")
    recent_applies_7d = len(applies_7d)

    # Recent verdicts (7d) — get_outcomes returns eval_verdict events (project-scope)
    outcomes_7d = alc_query.get_outcomes(state, since="7d")
    verdict_counts: dict[str, int] = {"approve": 0, "reject": 0, "modify": 0}
    last_ts: str | None = None
    for row in outcomes_7d:
        # verdicts are stored in the event name or a sub-field; normalise
        # best-effort — the schema doesn't guarantee a verdict sub-field,
        # so we count by event presence for now.
        # (The actual verdict is embedded in correlation_chain JSON if present.)
        ts = row.get("ts")
        if ts and (last_ts is None or ts > last_ts):
            last_ts = ts
        # Try to extract verdict from correlation_chain
        chain = row.get("correlation_chain")
        if isinstance(chain, str):
            try:
                payload = json.loads(chain)
                v = str(payload.get("verdict", "")).lower()
                if v in {"approve", "approved", "accept", "accepted"}:
                    verdict_counts["approve"] += 1
                elif v in {"reject", "rejected"}:
                    verdict_counts["reject"] += 1
                elif v in {"modify", "modified"}:
                    verdict_counts["modify"] += 1
                else:
                    verdict_counts["approve"] += 1
            except (json.JSONDecodeError, AttributeError):
                verdict_counts["approve"] += 1
        else:
            # No chain — count as generic outcome, lean toward approve
            verdict_counts["approve"] += 1

    # Last activity — latest event timestamp across applies + verdicts
    for row in applies_7d:
        ts = row.get("ts")
        if ts and (last_ts is None or ts > last_ts):
            last_ts = ts

    return {
        "pending_patches": pending_patch_count,
        "_first_patch_id": first_patch_id,
        "pending_recommendations": pending_rec_count,
        "recent_applies_7d": recent_applies_7d,
        "recent_verdicts_7d": verdict_counts,
        "last_activity_iso": last_ts,
        "approved_gates": {
            "total": gates_count,
            "user": gates_user_count,
            "project": gates_project_count,
        },
    }


# ---------------------------------------------------------------------------
# Synthesis helpers per intent
# ---------------------------------------------------------------------------

def _rung_pending_patches(signals: dict[str, Any]) -> dict[str, Any] | None:
    """Priority rung 1: pending patches."""
    count = signals["pending_patches"]
    if count <= 0:
        return None
    patch_id = signals.get("_first_patch_id")
    args_str = patch_id if patch_id else None
    noun = "patch" if count == 1 else "patches"
    return {
        "headline": f"{count} pending {noun} waiting for review.",
        "rationale": (
            f"There {'is' if count == 1 else 'are'} {count} pending {noun} in the improvement queue "
            "that have not been applied or rejected yet. "
            "Reviewing them now prevents the queue from growing stale and keeps the "
            "learning signal fresh."
        ),
        "skill": "ce-doc-review",
        "args": args_str,
        "prompt": (
            f"Review the pending patch {patch_id!r} and decide whether to apply, modify, or reject it."
            if patch_id
            else "Review the pending patches in the improvement queue."
        ),
        "alternatives": [
            {"skill": "list_pending_patches", "rationale": "Inspect all pending patches before deciding which to review first."},
        ],
    }


def _rung_recent_rejects(signals: dict[str, Any]) -> dict[str, Any] | None:
    """Priority rung 2: recently rejected verdicts."""
    rejects = signals["recent_verdicts_7d"]["reject"]
    if rejects < 1:
        return None
    noun = "rejection" if rejects == 1 else "rejections"
    return {
        "headline": f"{rejects} recommendation {noun} in the last 7 days — worth investigating.",
        "rationale": (
            f"The judge rejected {rejects} recommendation{'s' if rejects != 1 else ''} "
            "in the last 7 days. "
            "Reviewing what was rejected before adding more recommendations helps avoid "
            "repeating patterns that aren't landing. "
            "This is the highest-leverage diagnostic step right now."
        ),
        "skill": "ce-doc-review",
        "args": None,
        "prompt": "Investigate the recently rejected recommendations and identify recurring patterns.",
        "alternatives": [
            {"skill": "get_recommendations", "rationale": "Fetch the current recommendations list to see which ones are in flux."},
            {"skill": "ce-brainstorm", "rationale": "Brainstorm what went wrong if no clear pattern is obvious."},
        ],
    }


def _rung_stale_recommendations(signals: dict[str, Any]) -> dict[str, Any] | None:
    """Priority rung 3: stale / unreviewed recommendations queue."""
    count = signals["pending_recommendations"]
    if count < 4:
        return None
    return {
        "headline": f"{count} unreviewed recommendations in the queue — triage needed.",
        "rationale": (
            f"There are {count} unreviewed recommendations, which is above the actionable threshold. "
            "Triaging the queue keeps the learning loop tight and prevents low-signal entries "
            "from crowding out actionable ones."
        ),
        "skill": "alc-report",
        "args": "--recommend-only",
        "prompt": "Triage the recommendations queue: mark low-signal entries, promote strong ones.",
        "alternatives": [
            {"skill": "get_recommendations", "rationale": "Pull the raw list to review manually if the report is too slow."},
        ],
    }


def _rung_recent_commits_no_plan(signals: dict[str, Any]) -> dict[str, Any] | None:
    """Priority rung 4: recent commits without follow-up plan."""
    applies = signals["recent_applies_7d"]
    if applies < 1:
        return None
    return {
        "headline": f"{applies} patch{'es' if applies != 1 else ''} applied recently — plan the next step.",
        "rationale": (
            f"{applies} patch{'es' if applies != 1 else ''} were applied in the last 7 days. "
            "After a batch of changes, a short planning session helps lock in what worked, "
            "decide what to do next, and keeps the compound loop moving."
        ),
        "skill": "ce-plan",
        "args": None,
        "prompt": "Plan the next iteration based on recent changes and what they unblocked.",
        "alternatives": [
            {"skill": "ce-doc-review", "rationale": "Review docs to catch anything the recent patches touched but didn't document."},
            {"skill": "session-report", "rationale": "Run a session report to surface what happened in the last 7 days."},
        ],
    }


def _rung_idle() -> dict[str, Any]:
    """Priority rung 5: idle / no signal."""
    return {
        "headline": "No pending work — quiet state. Good time to brainstorm.",
        "rationale": (
            "There are no pending patches, no urgent recommendations, and no recent activity. "
            "This is a good moment to reflect on longer-horizon improvements or explore new directions "
            "before the queue fills up again."
        ),
        "skill": "ce-brainstorm",
        "args": None,
        "prompt": "Brainstorm the next improvement cycle: what learning loop should we invest in next?",
        "alternatives": [],
    }


# ---------------------------------------------------------------------------
# Intent-specific synthesis
# ---------------------------------------------------------------------------

def _synthesise_start_next(signals: dict[str, Any]) -> dict[str, Any]:
    """Forward-looking: what should I do now? (start / next intents)"""
    for rung_fn in (
        _rung_pending_patches,
        _rung_recent_rejects,
        _rung_stale_recommendations,
        _rung_recent_commits_no_plan,
    ):
        result = rung_fn(signals)
        if result is not None:
            return result
    return _rung_idle()


def _synthesise_end(signals: dict[str, Any]) -> dict[str, Any]:
    """Close-out: this session's recap + suggested wrap-up."""
    applies = signals["recent_applies_7d"]
    pending = signals["pending_patches"]

    if applies > 0:
        return {
            "headline": "Session wrap-up: commit your work and update the learning state.",
            "rationale": (
                f"{applies} patch{'es' if applies != 1 else ''} were applied this session. "
                "Before closing, commit your changes, update the session report, and "
                "make sure the improvement queue reflects what's left."
            ),
            "skill": "commit-commands:commit-push-pr",
            "args": None,
            "prompt": "Commit current changes, push, and open a PR to capture this session's output.",
            "alternatives": [
                {"skill": "session-report", "rationale": "Run session report to capture a narrative summary of what happened."},
                {"skill": "alc-report", "rationale": "Refresh the learning state report before closing."},
            ],
        }

    if pending > 0:
        return {
            "headline": "Session wrap-up: note pending work before closing.",
            "rationale": (
                f"There are {pending} pending patches still in the queue. "
                "Document your progress or defer the queue items so the next session can pick up cleanly."
            ),
            "skill": "session-report",
            "args": None,
            "prompt": "Summarise this session and document any pending items for the next session.",
            "alternatives": [
                {"skill": "commit-commands:commit", "rationale": "Commit any local changes first."},
            ],
        }

    return {
        "headline": "Session wrap-up: nothing applied — record what was learned.",
        "rationale": (
            "No patches were applied this session. "
            "Even a quiet session has learning value — record observations in the queue or "
            "update the session context before closing."
        ),
        "skill": "session-report",
        "args": None,
        "prompt": "Record session observations and close out cleanly.",
        "alternatives": [
            {"skill": "alc-report", "rationale": "Refresh the learning report to make sure the state is current."},
        ],
    }


def _synthesise_recap(signals: dict[str, Any]) -> dict[str, Any]:
    """Narrative summary of last 7 days."""
    applies = signals["recent_applies_7d"]
    verdicts = signals["recent_verdicts_7d"]
    total_verdicts = sum(verdicts.values())
    last_activity = signals["last_activity_iso"]

    if applies == 0 and total_verdicts == 0:
        return {
            "headline": "No activity in the last 7 days.",
            "rationale": (
                "No patches were applied and no verdicts were recorded in the last 7 days. "
                "The system is in a quiet state. "
                "This might be a good time to run the baseline and see if the repo has drifted."
            ),
            "skill": "alc-report",
            "args": None,
            "prompt": "Run the learning report to get a fresh snapshot of the current state.",
            "alternatives": [
                {"skill": "ce-brainstorm", "rationale": "Brainstorm what to work on next."},
            ],
        }

    v_str_parts = []
    if verdicts["approve"]:
        v_str_parts.append(f"{verdicts['approve']} approved")
    if verdicts["reject"]:
        v_str_parts.append(f"{verdicts['reject']} rejected")
    if verdicts["modify"]:
        v_str_parts.append(f"{verdicts['modify']} modified")
    v_str = ", ".join(v_str_parts) if v_str_parts else "no verdicts"
    activity_note = f" (last activity: {last_activity[:10]})" if last_activity else ""

    return {
        "headline": f"Last 7 days: {applies} patch{'es' if applies != 1 else ''} applied, {v_str}.{activity_note}",
        "rationale": (
            f"Over the last 7 days, {applies} patch{'es' if applies != 1 else ''} were applied and "
            f"{v_str} recorded. "
            "For a detailed narrative with quote-backed observations, run the full learning report."
        ),
        "skill": "alc-report",
        "args": None,
        "prompt": "Show the 7-day learning recap and suggest what to focus on next.",
        "alternatives": [
            {"skill": "session-report", "rationale": "Generate a session-level narrative view."},
        ],
    }


def _synthesise_leftoff(state: StateHandle, signals: dict[str, Any]) -> dict[str, Any]:
    """Where did I leave off: last patch_applied + last apply event."""
    last_ts = signals["last_activity_iso"]
    first_patch_id = signals.get("_first_patch_id")
    applies = signals["recent_applies_7d"]

    if last_ts is None and applies == 0 and signals["pending_patches"] == 0:
        return {
            "headline": "No recent activity found — starting fresh.",
            "rationale": (
                "No events or pending patches were found in the state for this repo. "
                "This looks like a fresh start. "
                "Initialize the learning system or run the baseline first."
            ),
            "skill": "alc-core",
            "args": None,
            "prompt": "Initialize the learning system for this repo and run the first baseline.",
            "alternatives": [
                {"skill": "ce-brainstorm", "rationale": "Brainstorm what to work on if the repo is already set up."},
            ],
        }

    patch_note = f" The first pending patch is {first_patch_id!r}." if first_patch_id else ""
    ts_note = f" Last recorded activity: {last_ts[:10] if last_ts else 'unknown'}." if last_ts else ""

    return {
        "headline": f"Picking up: {applies} recent appl{'ications' if applies != 1 else 'ication'}, {signals['pending_patches']} pending.{ts_note}",
        "rationale": (
            f"The most recent session applied {applies} patch{'es' if applies != 1 else ''} "
            f"and left {signals['pending_patches']} pending.{patch_note} "
            "Resume from the pending queue or check the apply log for the last touched area."
        ),
        "skill": "ce-doc-review" if first_patch_id else "alc-report",
        "args": first_patch_id,
        "prompt": (
            f"Resume from where I left off. Review pending patch {first_patch_id!r} first."
            if first_patch_id
            else "Resume from where I left off. Show the apply log and pending queue."
        ),
        "alternatives": [
            {"skill": "get_apply_log", "rationale": "Fetch the apply log to see the exact last event."},
            {"skill": "list_pending_patches", "rationale": "List all pending patches to prioritise."},
        ],
    }


def _synthesise_auto(state: StateHandle, signals: dict[str, Any]) -> dict[str, Any]:
    """Auto-select intent based on signals.

    Always delegates to the start/next priority ladder (rungs 1-5).
    The leftoff synthesiser is only invoked when the user explicitly requests
    it via intent='leftoff'.  Auto keeps things simple and predictable:
    any non-zero signal surfaces the appropriate rung; idle surfaces
    ce-brainstorm.
    """
    return _synthesise_start_next(signals)


# ---------------------------------------------------------------------------
# Schema assembly
# ---------------------------------------------------------------------------

def _build_result(
    intent: str,
    synthesis: dict[str, Any],
    signals: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the final output dict, stripping internal keys from signals."""
    public_signals = {
        "pending_patches": signals["pending_patches"],
        "pending_recommendations": signals["pending_recommendations"],
        "recent_applies_7d": signals["recent_applies_7d"],
        "recent_verdicts_7d": dict(signals["recent_verdicts_7d"]),
        "last_activity_iso": signals["last_activity_iso"],
        # approved_gates added in PR 2d. Tolerate older signal-dicts (e.g.
        # those produced by tests that pre-date the field) by defaulting to
        # an empty breakdown so the public schema is always complete.
        "approved_gates": signals.get("approved_gates", {"total": 0, "user": 0, "project": 0}),
    }
    alternatives_raw = synthesis.get("alternatives") or []
    alternatives = [
        {"skill": item.get("skill"), "rationale": item.get("rationale", "")}
        for item in alternatives_raw[:3]
    ]
    return {
        "intent": intent,
        "headline": synthesis["headline"],
        "rationale": synthesis["rationale"],
        "suggested": {
            "skill": synthesis.get("skill"),
            "args": synthesis.get("args"),
            "prompt": synthesis.get("prompt", ""),
        },
        "alternatives": alternatives,
        "signals": public_signals,
    }


# ---------------------------------------------------------------------------
# Cache write
# ---------------------------------------------------------------------------

def _write_cache(state: StateHandle, result: dict[str, Any]) -> None:
    """Write the result to <reports-dir>/latest-next-action.json."""
    target = state.reports_dir / "latest-next-action.json"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # Reject symlinks (trust model: telemetry writes must go to regular files)
        if target.exists() and not target.is_file():
            return
        serialised = json.dumps(result, sort_keys=True, ensure_ascii=False, indent=2)
        target.write_text(serialised, encoding="utf-8")
    except OSError:
        pass  # Cache write failure is non-fatal; synthesiser result still returned


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def next_action(
    state: StateHandle,
    intent: str = "auto",
    session_id: str | None = None,
) -> dict[str, Any]:
    """Synthesise a session-lifecycle recommendation for the given repo.

    Parameters
    ----------
    state:
        A ``StateHandle`` resolving the repo's ALC state root.  The MCP
        server's auto-register pattern constructs this from ``args["repo"]``
        before calling.
    intent:
        Lifecycle hint.  One of ``start | next | end | recap | leftoff | auto``.
        Aliases like ``begin``, ``finish``, ``summary`` are accepted and
        normalised.  Unknown values fall back to ``auto``.
    session_id:
        Optional session identifier.  Reserved for future use (e.g. fetching
        a session-scoped event DAG via ``get_event_dag``).  Not currently
        consumed by the synthesiser.

    Returns
    -------
    dict
        Structured recommendation conforming to the output schema documented
        at the top of this module.  Side effect: writes the result to
        ``<state-root>/repos/<repo-id>/reports/latest-next-action.json``.
    """
    normalised = _normalise_intent(intent)
    signals = _collect_signals(state)

    if normalised in ("start", "next"):
        synthesis = _synthesise_start_next(signals)
        out_intent = normalised
    elif normalised == "end":
        synthesis = _synthesise_end(signals)
        out_intent = "end"
    elif normalised == "recap":
        synthesis = _synthesise_recap(signals)
        out_intent = "recap"
    elif normalised == "leftoff":
        synthesis = _synthesise_leftoff(state, signals)
        out_intent = "leftoff"
    else:  # "auto"
        synthesis = _synthesise_auto(state, signals)
        out_intent = "auto"

    result = _build_result(out_intent, synthesis, signals)
    _write_cache(state, result)
    return result
