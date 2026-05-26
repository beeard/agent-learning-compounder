# agent-learning-compounder (Claude entrypoint)

This is the Claude Code plugin entry for `agent-learning-compounder`. The
plugin's MCP server, hooks, and slash commands auto-discover from this
directory; see `.claude-plugin/plugin.json`, `.mcp.json`, and `hooks/hooks.json`.

## Core commands

- `/alc-report` — run the full learning report pipeline via `scripts/render_unified_report.py`.
- `alc_init` — first-run profiler: detects host repo, smokes MCP, writes
  per-repo session-context with synthesized runtime summary, doc-contract
  check, and CE playbook tailored to the detected stack.
- `init_learning_system` — bootstrap repository state and hooks in one command.
- `render_unified_report` — run the full report chain with optional automation flags.

## MCP tools

12 stdio tools, auto-started via `.mcp.json`.

**Read surface** (backed by `bin/alc_query.py` — the canonical read API per KTD-21):

- `get_gates` — approved gates, optionally scoped by domain
- `get_skill_context` — latest skill-routing markdown
- `get_recommendations` — recommender output rows
- `list_pending_patches` — patch bundles not yet applied
- `get_dashboard_url` — dashboard URL for this repo
- `list_capabilities` — M1–M11 MCP catalog metadata
- `next_action` (M11) — synthesise session-lifecycle recommendation (what's next, session start/end, where I left off); backed by `bin/alc_next_action.py`; writes `latest-next-action.json` cache

**Propose / write surface** (backed by `bin/alc_propose.py` — the symmetric propose seam per KTD-21):

- `propose_gate` — append operator-proposed gate to improvement queue
- `propose_apply` — return apply CLI command (no mutation — keeps human in loop)
- `report_outcome` — record recommendation/gate outcome
- `report_agent_event` — record bounded agent dispatch telemetry

**Sandbox:**

- `exec_sandbox` — run a bounded command in `read|worktree|eval` scope; M10 tier

## Read/write seams

- `bin/alc_query.py` is the only read API. Hooks, dashboards, MCP tools,
  slash commands, and `alc_init` all consume it — never reimplement
  SQLite/JSONL reads inline. This is KTD-21.
- `bin/alc_propose.py` is the symmetric propose/write API for the queue +
  event writer. Same rule: future propose-style tools register here.

## Operating rules

### State and scope

- Use command entrypoints in the `scripts/` directory, not direct internal modules.
- Keep repo mutation paths inside `agents/`, `skills/`, `commands/`, and configured state roots.

### Output policy

- Prefer durable report outputs (`latest-approved-gates.md`,
  `latest-skill-context.md`, `latest-session-context.md`) over raw
  transcripts.
- Synthesize alc_query results into prose summaries — never dump raw
  event rows or JSON payloads into agent context. See
  `bin/alc_init` (`render_runtime_summary_md`, `render_doc_contract_md`)
  for the synthesis discipline.
- Never include secrets, absolute paths, or unbounded transcript chunks in command outputs.
