"""Canonical MCP capability catalog for agent-learning-compounder."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class MCPToolSpec:
    id: str
    kind: str
    summary: str
    backing: str
    parameters_schema: dict[str, Any]
    returns_schema: dict[str, Any]
    examples: list[dict[str, Any]]
    version: int
    min_compatible_version: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_REPO_PARAM = {"type": "string", "description": "Repository root path."}

# Scope param — see ARCHITECTURE.md § 4 ("Scope model").
# user = cross-repo learning; project = per-repo events; both = union.
_SCOPE_PARAM = {
    "type": "string",
    "enum": ["user", "project", "both"],
    "default": "project",
    "description": (
        "State scope to read. 'user' = cross-repo learning under "
        "AGENT_LEARNING_USER (default ~/.agent-learning). 'project' = "
        "per-repo state under <repo>/.agent-learning. 'both' = union."
    ),
}
_DOMAIN_PARAM = {
    "type": "string",
    "description": "Optional domain filter (e.g. 'tests', 'cloudflare').",
}


MCP_TOOLS: dict[str, MCPToolSpec] = {
    "get_gates": MCPToolSpec(
        id="M1",
        kind="read",
        summary="Return approved gates, scoped by state-root (user/project/both) and optionally filtered by domain.",
        backing="alc_query.get_gates",
        parameters_schema={"type": "object", "required": ["repo"], "properties": {"repo": _REPO_PARAM, "scope": _SCOPE_PARAM, "domain": _DOMAIN_PARAM}},
        returns_schema={"type": "array", "items": {"type": "object"}},
        examples=[
            {"repo": "/path/to/repo"},
            {"repo": "/path/to/repo", "scope": "user"},
            {"repo": "/path/to/repo", "scope": "both", "domain": "tests"},
        ],
        version=2,
        min_compatible_version=1,
    ),
    "get_skill_context": MCPToolSpec(
        id="M2",
        kind="read",
        summary="Return latest skill-context markdown, scoped by state-root (user/project/both).",
        backing="alc_query.get_skill_context",
        parameters_schema={"type": "object", "required": ["repo"], "properties": {"repo": _REPO_PARAM, "scope": _SCOPE_PARAM}},
        returns_schema={"type": "string"},
        examples=[{"repo": "/path/to/repo"}, {"repo": "/path/to/repo", "scope": "both"}],
        version=2,
        min_compatible_version=1,
    ),
    "get_recommendations": MCPToolSpec(
        id="M3",
        kind="read",
        summary="Return recommender output rows from recommendations.json (project-scope).",
        backing="alc_query.get_recommendations",
        parameters_schema={"type": "object", "required": ["repo"], "properties": {"repo": _REPO_PARAM, "scope": _SCOPE_PARAM}},
        returns_schema={"type": "array", "items": {"type": "object"}},
        examples=[{"repo": "/path/to/repo"}],
        version=2,
        min_compatible_version=1,
    ),
    "list_pending_patches": MCPToolSpec(
        id="M4",
        kind="read",
        summary="Return pending patch bundles, excluding rejected/deferred patches (project-scope).",
        backing="alc_query.get_pending_patches",
        parameters_schema={"type": "object", "required": ["repo"], "properties": {"repo": _REPO_PARAM, "scope": _SCOPE_PARAM}},
        returns_schema={"type": "array", "items": {"type": "object"}},
        examples=[{"repo": "/path/to/repo"}],
        version=2,
        min_compatible_version=1,
    ),
    "get_dashboard_url": MCPToolSpec(
        id="M5",
        kind="read",
        summary="Return the dashboard URL for repo, preferring localhost when configured.",
        backing="state_handle.dashboard_url",
        parameters_schema={"type": "object", "required": ["repo"], "properties": {"repo": _REPO_PARAM}},
        returns_schema={"type": "string"},
        examples=[{"repo": "/path/to/repo"}],
        version=1,
        min_compatible_version=1,
    ),
    "propose_apply": MCPToolSpec(
        id="M6",
        kind="propose",
        summary="Return an apply CLI command for a patch id without applying it (no mutation).",
        backing="alc_propose.propose_apply",
        parameters_schema={"type": "object", "required": ["repo", "patch_id"], "properties": {"repo": _REPO_PARAM, "patch_id": {"type": "string"}}},
        returns_schema={"type": "object", "required": ["command"], "properties": {"command": {"type": "string"}}},
        examples=[{"repo": "/path/to/repo", "patch_id": "patch-123"}],
        version=2,
        min_compatible_version=1,
    ),
    "propose_gate": MCPToolSpec(
        id="M7",
        kind="propose",
        summary="Append an operator-proposed gate to the improvement queue for review.",
        backing="alc_propose.propose_gate",
        parameters_schema={"type": "object", "required": ["repo", "domain", "category", "gate"], "properties": {"repo": _REPO_PARAM, "domain": {"type": "string"}, "category": {"type": "string"}, "gate": {"type": "string"}, "evidence": {"type": "string"}}},
        returns_schema={"type": "object", "required": ["queue_id"], "properties": {"queue_id": {"type": "string"}}},
        examples=[{"repo": "/path/to/repo", "domain": "tests", "category": "validation", "gate": "Run tests first."}],
        version=1,
        min_compatible_version=1,
    ),
    "report_outcome": MCPToolSpec(
        id="M8",
        kind="observe",
        summary="Record a recommendation or legacy gate outcome through event_writer.",
        backing="alc_propose.report_outcome",
        parameters_schema={"type": "object", "required": ["repo"], "properties": {"repo": _REPO_PARAM, "recommendation_id": {"type": "string"}, "verdict": {"type": "string"}, "reason": {"type": "string"}, "gate_id": {"type": "string"}, "outcome": {"type": "string"}, "correlation_id": {"type": "string"}}},
        returns_schema={"type": "object", "required": ["recorded"], "properties": {"recorded": {"type": "boolean"}, "event_id": {"type": "string"}}},
        examples=[{"repo": "/path/to/repo", "recommendation_id": "rec-1", "verdict": "accepted", "reason": "useful"}],
        version=1,
        min_compatible_version=1,
    ),
    "report_agent_event": MCPToolSpec(
        id="M9",
        kind="observe",
        summary="Record bounded agent dispatch telemetry through event_writer.",
        backing="alc_propose.report_agent_event",
        parameters_schema={"type": "object", "required": ["repo"], "properties": {"repo": _REPO_PARAM, "kind": {"type": "string"}, "actor_name": {"type": "string"}, "telemetry": {"type": "object"}}},
        returns_schema={"type": "object", "required": ["recorded"], "properties": {"recorded": {"type": "boolean"}, "event_id": {"type": "string"}}},
        examples=[{"repo": "/path/to/repo", "kind": "complete", "actor_name": "builder"}],
        version=1,
        min_compatible_version=1,
    ),
    "exec_sandbox": MCPToolSpec(
        id="M10",
        kind="exec",
        summary="Run a bounded sandbox command in read, worktree, or eval scope.",
        backing="exec_sandbox.run",
        parameters_schema={"type": "object", "required": ["repo", "scope", "command"], "properties": {"repo": _REPO_PARAM, "scope": {"type": "string", "enum": ["read", "worktree", "eval"]}, "command": {"type": "string"}, "base_ref": {"type": "string"}, "timeout_s": {"type": "integer"}}},
        returns_schema={"type": "object", "required": ["exit_code", "stdout", "stderr", "event_id"], "properties": {"exit_code": {"type": "integer"}, "stdout": {"type": "string"}, "stderr": {"type": "string"}, "event_id": {"type": "string"}, "run_id": {"type": "string"}}},
        examples=[{"repo": "/path/to/repo", "scope": "read", "command": "git status --short"}],
        version=1,
        min_compatible_version=1,
    ),
    "next_action": MCPToolSpec(
        id="M11",
        kind="read",
        summary="Synthesise a session-lifecycle recommendation (what's next, session start/end, where I left off).",
        backing="alc_next_action.next_action",
        parameters_schema={
            "type": "object",
            "required": ["repo"],
            "properties": {
                "repo": _REPO_PARAM,
                "intent": {
                    "type": "string",
                    "enum": ["start", "next", "end", "recap", "leftoff", "auto"],
                    "description": "Lifecycle hint. Defaults to 'auto'.",
                },
                "session_id": {
                    "type": "string",
                    "description": "Optional session identifier for scoped lookups.",
                },
            },
        },
        returns_schema={
            "type": "object",
            "required": ["intent", "headline", "rationale", "suggested", "alternatives", "signals"],
            "properties": {
                "intent": {"type": "string"},
                "headline": {"type": "string"},
                "rationale": {"type": "string"},
                "suggested": {
                    "type": "object",
                    "required": ["skill", "args", "prompt"],
                    "properties": {
                        "skill": {"type": ["string", "null"]},
                        "args": {"type": ["string", "null"]},
                        "prompt": {"type": "string"},
                    },
                },
                "alternatives": {
                    "type": "array",
                    "maxItems": 3,
                    "items": {
                        "type": "object",
                        "required": ["skill", "rationale"],
                        "properties": {
                            "skill": {"type": ["string", "null"]},
                            "rationale": {"type": "string"},
                        },
                    },
                },
                "signals": {
                    "type": "object",
                    "required": ["pending_patches", "pending_recommendations", "recent_applies_7d", "recent_verdicts_7d", "last_activity_iso"],
                    "properties": {
                        "pending_patches": {"type": "integer"},
                        "pending_recommendations": {"type": "integer"},
                        "recent_applies_7d": {"type": "integer"},
                        "recent_verdicts_7d": {
                            "type": "object",
                            "properties": {
                                "approve": {"type": "integer"},
                                "reject": {"type": "integer"},
                                "modify": {"type": "integer"},
                            },
                        },
                        "last_activity_iso": {"type": ["string", "null"]},
                        "approved_gates": {
                            "type": "object",
                            "description": "Cross-scope gate breakdown (PR 2d). 'total' = union, 'user' = cross-repo, 'project' = per-repo.",
                            "properties": {
                                "total": {"type": "integer"},
                                "user": {"type": "integer"},
                                "project": {"type": "integer"},
                            },
                        },
                    },
                },
            },
        },
        examples=[
            {"repo": "/path/to/repo"},
            {"repo": "/path/to/repo", "intent": "start"},
            {"repo": "/path/to/repo", "intent": "leftoff"},
            {"repo": "/path/to/repo", "intent": "end"},
        ],
        version=1,
        min_compatible_version=1,
    ),
}
