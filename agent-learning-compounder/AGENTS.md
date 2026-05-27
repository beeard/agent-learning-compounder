# agent-learning-compounder (Codex entrypoint)

Codex loads this file for plugin instructions. See `CLAUDE.md` for the full cross-runtime notes.

## Core commands

- `/alc-report` — run the full learning report pipeline via `scripts/render_unified_report.py`.
- `alc_init` — first-run profiler: detects host repo, smokes MCP, writes
  per-repo session-context with synthesized runtime summary, doc-contract
  check, and CE playbook tailored to the detected stack.
- `init_learning_system` — bootstrap repository state and hooks in one command.
- `render_unified_report` — run the full report chain with optional automation flags.

## MCP tools

20 stdio tools, auto-started via `.mcp.json`, plus the `list_capabilities`
meta tool.

**Read surface** (backed by `bin/alc_query.py` — the canonical read API per KTD-21):

- `get_gates` — approved gates, optionally scoped by domain
- `get_skill_context` — latest skill-routing markdown
- `get_recommendations` — recommender output rows
- `list_pending_patches` — patch bundles not yet applied
- `get_dashboard_url` — dashboard URL for this repo
- `get_proposal_queue` — proposal queue rows from `improvement-queue.jsonl`
- `get_proposal_lifecycle` — normalized queue/patch/suggestion lifecycle rows
- `list_capabilities` — M1–M20 MCP catalog metadata
- `next_action` (M11) — synthesise session-lifecycle recommendation (what's next, session start/end, where I left off); backed by `bin/alc_next_action.py`; writes `latest-next-action.json` cache

**Propose / write surface** (backed by `bin/alc_propose.py` — the symmetric propose seam per KTD-21):

- `propose_gate` — append operator-proposed gate to improvement queue
- `propose_apply` — return apply CLI command (no mutation — keeps human in loop)
- `report_outcome` — record recommendation/gate outcome
- `report_agent_event` — record bounded agent dispatch telemetry
- `mark_patch_status` — defer or reject a pending patch bundle

**Sandbox:**

- `exec_sandbox` — run a bounded command in `read|worktree|eval` scope; M10 tier

## Read/write seams

- `bin/alc_query.py` is the only read API. Hooks, dashboards, MCP tools,
  slash commands, and `alc_init` all consume it — never reimplement
  SQLite/JSONL reads inline. This is KTD-21.
- `bin/alc_propose.py` is the symmetric propose/write API for the queue +
  event writer. Same rule: future propose-style tools register here.
- `bin/proposal_lifecycle.py` owns proposal identity, lifecycle records,
  proposal event payloads, and normalized read mirrors. Keep `alc_propose.py`
  as the CLI/MCP adapter and expose read-side lifecycle state through
  `alc_query.py`.
- `bin/release_metadata.py` owns package-visible release identity. Manifest,
  npm, Claude plugin, marketplace, and README release strings are adapters
  guarded by `tests/test_release_metadata.py`.
- `bin/release_layout.py` owns release archive/package layout. Build scripts,
  sanitizer policy, npm files, manifest docs/exclusions, and release fixture
  archive checks are adapters guarded by `tests/test_release_layout.py`.
- `bin/dashboard_url_publisher.py` owns dashboard live marker schema,
  loopback validation, owner-token cleanup, and static fallback order. FastAPI,
  stdlib serving, static rendering, `state_handle.dashboard_url`, and MCP
  `get_dashboard_url` are adapters around that policy.

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
