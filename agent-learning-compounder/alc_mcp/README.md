# agent-learning-compounder MCP server

Stdio MCP server exposing the durable state as queryable tools.

## Install

```bash
pip install mcp
```

(Or `pip install -r requirements-optional.txt` from the installed skill root.
From the archive root, use
`pip install -r agent-learning-compounder/requirements-optional.txt`.)

## Run

From the installed skill root:

```bash
python3 -m alc_mcp.server
```

Or directly:

```bash
python3 alc_mcp/server.py
```

## Tools

- `get_gates(repo, scope=None) -> list[gate]`
- `get_skill_context(repo) -> str`
- `get_recommendations(repo) -> list[recommendation]`
- `list_pending_patches(repo) -> list[patch]`
- `get_dashboard_url(repo) -> str`
- `propose_apply(repo, patch_id) -> {command}`
- `propose_gate(repo, domain, category, gate, evidence?) -> {queue_id}`
- `report_outcome(repo, recommendation_id, verdict, reason) -> {recorded, event_id}`
- `report_agent_event(repo, kind, actor_name, telemetry?) -> {recorded, event_id}`
- `exec_sandbox(repo, scope, command, ...) -> {exit_code, stdout, stderr, event_id}`
- dashboard action tools: `run_distill`, `list_action_jobs`, `get_action_job`,
  `get_action_state`, `promote_gate_action`, `unpromote_gate_action`,
  `mute_domain`, `unmute_domain`, `get_latest_report`
- `get_session_signals(repo, intent?) -> {intent, signals}`
- `get_lifecycle_contracts(repo) -> list[contract]`
- dashboard read tools: `get_dashboard_payload`, `get_dashboard_health`,
  `get_latest_report_content`
- `list_capabilities(repo) -> list[MCPToolSpec]`

The M1-M34 capability catalog is published as `alc_mcp.MCP_TOOLS`; see
`skills/alc-core/references/mcp-catalog.md` for the human-readable reference.

## Integration

For Claude Desktop / Cursor / other MCP clients, configure stdio with the
absolute path to this server entry point. Repo path is passed per call so a
single server instance can serve multiple repos.

The handler functions are import-safe even when the `mcp` SDK is missing —
they don't depend on it. Only the stdio entry point (`build_server`, `main`)
requires the SDK.
