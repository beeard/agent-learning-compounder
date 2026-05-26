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


MCP_TOOLS: dict[str, MCPToolSpec] = {
    "get_gates": MCPToolSpec(
        id="M1",
        kind="read",
        summary="Return approved gates loaded for repo, optionally scoped by domain.",
        backing="alc_query.get_gates",
        parameters_schema={"type": "object", "required": ["repo"], "properties": {"repo": _REPO_PARAM, "scope": {"type": "string"}}},
        returns_schema={"type": "array", "items": {"type": "object"}},
        examples=[{"repo": "/path/to/repo"}, {"repo": "/path/to/repo", "scope": "tests"}],
        version=1,
        min_compatible_version=1,
    ),
    "get_skill_context": MCPToolSpec(
        id="M2",
        kind="read",
        summary="Return latest skill-context markdown for repo.",
        backing="alc_query.get_skill_context",
        parameters_schema={"type": "object", "required": ["repo"], "properties": {"repo": _REPO_PARAM}},
        returns_schema={"type": "string"},
        examples=[{"repo": "/path/to/repo"}],
        version=1,
        min_compatible_version=1,
    ),
    "get_recommendations": MCPToolSpec(
        id="M3",
        kind="read",
        summary="Return recommender output rows from recommendations.json.",
        backing="alc_query.get_recommendations",
        parameters_schema={"type": "object", "required": ["repo"], "properties": {"repo": _REPO_PARAM}},
        returns_schema={"type": "array", "items": {"type": "object"}},
        examples=[{"repo": "/path/to/repo"}],
        version=1,
        min_compatible_version=1,
    ),
    "list_pending_patches": MCPToolSpec(
        id="M4",
        kind="read",
        summary="Return pending patch bundles, excluding rejected/deferred patches.",
        backing="alc_query.get_pending_patches",
        parameters_schema={"type": "object", "required": ["repo"], "properties": {"repo": _REPO_PARAM}},
        returns_schema={"type": "array", "items": {"type": "object"}},
        examples=[{"repo": "/path/to/repo"}],
        version=1,
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
        summary="Return an apply CLI command and one-shot token for a patch id without applying it.",
        backing="alc_propose.propose_apply",
        parameters_schema={"type": "object", "required": ["repo", "patch_id"], "properties": {"repo": _REPO_PARAM, "patch_id": {"type": "string"}}},
        returns_schema={"type": "object", "required": ["command", "token"], "properties": {"command": {"type": "string"}, "token": {"type": "string"}}},
        examples=[{"repo": "/path/to/repo", "patch_id": "patch-123"}],
        version=1,
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
}
