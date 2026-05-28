"""Lifecycle contract table for core ALC entities."""

from __future__ import annotations

from typing import Any


LIFECYCLE_CONTRACTS: list[dict[str, Any]] = [
    {"entity": "events", "create": "event_writer.write_event", "read": "alc_query event reads", "update": None, "archive": None, "delete": None, "append_only_rationale": "Telemetry is append-only audit history."},
    {"entity": "gates", "create": "distill_learning", "read": "alc_query.get_gates", "update": "export_gates --rename", "archive": "gate retirement candidates", "delete": None, "append_only_rationale": ""},
    {"entity": "recommendations", "create": "recommender pipeline", "read": "alc_query.get_recommendations", "update": None, "archive": "report rotation", "delete": None, "append_only_rationale": "Generated report rows are immutable snapshots."},
    {"entity": "patch_bundles", "create": "recommender_render", "read": "alc_query.get_pending_patches", "update": "alc_propose.mark_patch_status", "archive": "deferred/rejected status", "delete": None, "append_only_rationale": ""},
    {"entity": "proposals", "create": "alc_propose.propose_gate/apply", "read": "alc_query.get_proposal_queue", "update": "proposal status rows", "archive": "closed status", "delete": None, "append_only_rationale": ""},
    {"entity": "outcomes", "create": "alc_propose.report_outcome", "read": "alc_query.get_outcomes", "update": None, "archive": None, "delete": None, "append_only_rationale": "Judgements are append-only evidence."},
    {"entity": "dashboard_artifacts", "create": "render_state_surface/render_dashboard", "read": "dashboard_read_model", "update": "bounded refresh", "archive": "report history", "delete": None, "append_only_rationale": ""},
    {"entity": "dashboard_action_records", "create": "dashboard.actions", "read": "dashboard.actions.actions_summary", "update": "promote/mute idempotent updates", "archive": "unpromote/unmute", "delete": None, "append_only_rationale": ""},
    {"entity": "skill_context", "create": "refresh_learning_state", "read": "alc_query.get_skill_context", "update": "refresh loop", "archive": "latest file replacement", "delete": None, "append_only_rationale": ""},
    {"entity": "capabilities", "create": "source registries", "read": "list_capabilities/alc_help", "update": "registry edit plus render_catalogs", "archive": "git history", "delete": "remove registry row", "append_only_rationale": ""},
    {"entity": "agent_definitions", "create": "recommender_generators", "read": "filesystem/catalog", "update": "skill_manage_op patch", "archive": "git history", "delete": "operator-managed", "append_only_rationale": ""},
    {"entity": "agent_invocations", "create": "report_agent_event/hooks", "read": "alc_query skill/actor queries", "update": None, "archive": None, "delete": None, "append_only_rationale": "Invocation telemetry is append-only audit history."},
    {"entity": "reports", "create": "render_unified_report", "read": "latest report/dashboard", "update": "latest pointer replacement", "archive": "timestamped reports", "delete": None, "append_only_rationale": ""},
    {"entity": "metrics", "create": "report pipeline", "read": "dashboard_read_model", "update": None, "archive": None, "delete": None, "append_only_rationale": "Metric rows are append-only observations."},
    {"entity": "suggestions", "create": "recommender_render", "read": "alc_query.get_suggestions", "update": "future lifecycle status", "archive": "proposal lifecycle", "delete": None, "append_only_rationale": ""},
]


def list_lifecycle_contracts() -> list[dict[str, Any]]:
    return [dict(row) for row in LIFECYCLE_CONTRACTS]
