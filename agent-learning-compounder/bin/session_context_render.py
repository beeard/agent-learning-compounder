"""Pure render helpers for the session-context document.

Library module — no CLI entry point, no side effects, no I/O.
Import from ``alc_init``, future MCP tools, and the dashboard session-filter
view without pulling in any orchestration state.

Public surface
--------------
render_runtime_summary_md(summary)   -> str
render_ce_usage_md(ce_usage)         -> str
render_doc_contract_md(rows, ce_installed) -> str
render_session_context(profile, mcp_status, *, ...) -> str
"""

from __future__ import annotations

from typing import Any


def render_runtime_summary_md(summary: dict[str, Any]) -> str:
    """Synthesize the runtime summary into compact prose. Never raw JSON."""
    actors = summary.get("actors") or {}
    applies = summary.get("applies") or []
    outcomes = summary.get("outcomes") or []
    recs = summary.get("recommendations") or []
    pending = summary.get("pending_patches") or []

    has_any = (
        (actors.get("total") or 0) > 0
        or applies or outcomes or recs or pending
    )
    if not has_any:
        return ("_No durable runtime history yet — sessions and apply events "
                "will start populating this section once hooks fire and the "
                "indexer runs._")

    lines: list[str] = []

    if (actors.get("total") or 0) > 0:
        kinds = ", ".join(
            f"{r['count']} {r['actor_kind']} ({r['unique_actors']} unique)"
            for r in actors["by_actor_kind"]
        )
        lines.append(f"- **Activity (7d):** {actors['total']} events — {kinds}")

    if applies:
        from collections import Counter
        breakdown = Counter(row.get("event", "?") for row in applies)
        parts = [f"{count} {ev.replace('patch_', '')}"
                 for ev, count in breakdown.most_common()]
        lines.append(f"- **Patches (7d):** {', '.join(parts)}")

    if outcomes:
        lines.append(f"- **Judge verdicts (7d):** {len(outcomes)} event(s) — "
                     f"detail via `get_outcomes` MCP / dashboard")

    if recs or pending:
        pieces = []
        if recs:
            pieces.append(f"{len(recs)} recommendation(s)")
        if pending:
            pieces.append(f"{len(pending)} pending patch(es)")
        lines.append(f"- **Awaiting review:** {', '.join(pieces)} — "
                     "triage via `/alc-report` or `alc_apply --list-pending`")

    return "\n".join(lines)


def render_ce_usage_md(ce_usage: list[dict[str, Any]]) -> str:
    """Synthesize CE-family skill usage into a single line per skill, sorted."""
    if not ce_usage:
        return ("_No tracked invocations of compound-engineering or adjacent "
                "lifecycle skills yet._")
    lines = []
    for row in ce_usage[:15]:
        last = row.get("last_used_ts") or "?"
        # Trim ISO ts to date for brevity.
        last_day = str(last)[:10] if isinstance(last, str) else "?"
        lines.append(f"- `{row['actor_name']}` — {row['count']}× (last {last_day})")
    if len(ce_usage) > 15:
        lines.append(f"- _…and {len(ce_usage) - 15} more (see `alc_query.get_skill_usage_summary`)_")
    return "\n".join(lines)


def render_doc_contract_md(rows: list[dict[str, Any]], ce_installed: bool) -> str:
    """Synthesize the doc-contract check into a present/missing table with hints."""
    lines: list[str] = []
    grouped: dict[str, list[dict[str, Any]]] = {"anchor": [], "architecture": [], "workflow": []}
    for row in rows:
        grouped.setdefault(row["tier"], []).append(row)

    tier_labels = {
        "anchor": "Anchors",
        "architecture": "Architecture",
        "workflow": "Workflow surfaces",
    }
    for tier, label in tier_labels.items():
        tier_rows = grouped.get(tier) or []
        if not tier_rows:
            continue
        lines.append(f"**{label}:**")
        for row in tier_rows:
            mark = "✓" if row["found"] else "✗"
            paths_str = " / ".join(f"`{p}`" for p in row["paths_checked"])
            if row["found"]:
                lines.append(f"- {mark} {paths_str} — present (`{row['found']}`)")
            else:
                hint = ""
                if row["generator"]:
                    if ce_installed:
                        hint = f" — generate via `/{row['generator']}`"
                    else:
                        hint = (f" — install compound-engineering, then "
                                f"`/{row['generator']}`, or write manually")
                lines.append(f"- {mark} {paths_str} — missing{hint}")
        lines.append("")
    return "\n".join(lines).rstrip()


def render_session_context(
    profile: dict[str, Any],
    mcp_status: dict[str, Any],
    *,
    playbook_md: str = "",
    runtime_md: str = "",
    ce_usage_md: str = "",
    doc_contract_md: str = "",
) -> str:
    """Assemble all sections into the full session-context document."""
    lang_line = ""
    if profile.get("languages"):
        top = sorted(profile["languages"].items(), key=lambda x: -x[1])[:3]
        lang_line = ", ".join(f"{lang} ({count})" for lang, count in top)

    lines = [
        "# Session context — agent-learning-compounder",
        "",
        f"_Generated by `alc init` for `{profile['name']}` at `{profile['abspath']}`._",
        "",
        "## Repo profile",
        "",
        f"- **Languages**: {lang_line or '_none detected_'}",
        f"- **Frameworks**: {', '.join(profile['frameworks']) or '_none detected_'}",
        f"- **Package managers**: {', '.join(profile['package_managers']) or '_none_'}",
        f"- **Tests**: {'yes' if profile['has_tests'] else 'no'}",
        f"- **Frontend**: {'yes' if profile['has_frontend'] else 'no'}",
        f"- **Monorepo**: {'yes' if profile['monorepo'] else 'no'}",
        f"- **Git repo**: {'yes' if profile['has_git'] else 'no'}",
        "",
        "## ALC MCP status",
        "",
        f"- **Status**: `{mcp_status['status']}`",
    ]
    if mcp_status.get("tools"):
        lines.append(f"- **Tools** ({len(mcp_status['tools'])}): "
                     + ", ".join(f"`{t}`" for t in mcp_status["tools"]))
    if mcp_status.get("error"):
        lines.append(f"- **Note**: {mcp_status['error']}")
    lines.append("")

    lines.append("## Runtime summary (synthesized from alc_query)")
    lines.append("")
    lines.append(runtime_md.rstrip() if runtime_md else "_Not computed._")
    lines.append("")

    lines.append("## Documentation contract")
    lines.append("")
    lines.append(doc_contract_md.rstrip() if doc_contract_md
                 else "_Doc contract not checked._")
    lines.append("")

    lines.append("## CE-family skill usage (last 30 days)")
    lines.append("")
    lines.append(ce_usage_md.rstrip() if ce_usage_md
                 else "_Not computed._")
    lines.append("")

    lines.append("## Compound-engineering playbook")
    lines.append("")
    lines.append(playbook_md.rstrip() if playbook_md
                 else "_No playbook generated._")
    lines.append("")
    return "\n".join(lines)
