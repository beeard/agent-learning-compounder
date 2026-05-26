# MCP Capability Catalog (M1-M10)

`alc_mcp.catalog.MCP_TOOLS` is the canonical machine-readable catalog. This file is the human-readable reference for agents.

| ID | Tool | Kind | Backing | Notes |
| --- | --- | --- | --- | --- |
| M1 | `get_gates` | read | `alc_query.get_gates` | Approved gates for a repo, optionally domain scoped. |
| M2 | `get_skill_context` | read | `alc_query.get_skill_context` | Latest skill-context markdown. |
| M3 | `get_recommendations` | read | `alc_query.get_recommendations` | Recommender rows from `recommendations.json`. |
| M4 | `list_pending_patches` | read | `alc_query.get_pending_patches` | Pending patch bundles, excluding rejected/deferred patches. |
| M5 | `get_dashboard_url` | read | `state_handle.dashboard_url` | Localhost dashboard URL when known, otherwise `file://` dashboard path. |
| M6 | `propose_apply` | propose | `alc_propose.propose_apply` | Returns an apply command and one-shot token. Does not apply or mutate target files. |
| M7 | `propose_gate` | propose | `alc_propose.propose_gate` | Appends a proposed gate to the review queue and emits proposal telemetry. |
| M8 | `report_outcome` | observe | `alc_propose.report_outcome` | Emits `outcome_reported` via `event_writer.write_event`. |
| M9 | `report_agent_event` | observe | `alc_propose.report_agent_event` | Emits `agent_dispatch_*` via `event_writer.write_event`. |
| M10 | `exec_sandbox` | exec | `exec_sandbox.run` | Runs bounded read/worktree/eval commands through the sandbox primitive. |

Agents should call `list_capabilities(repo)` first and compare each returned `version` and `min_compatible_version` against their known client contract.
