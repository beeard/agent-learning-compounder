# Read-surface audit — 2026-05-27

Scope: every MCP read tool, every `alc_query.py` function, the propose seam,
the `next_action` synthesizer, `render_state_surface`, `alc_init`'s runtime
synthesis, and the two dashboards. Exercised against the populated state at
`/home/tth/work/active/agent-learning-compounder/.agent-learning/repos/agent-learning-compounder-45819fdf8f74/`.

## State on disk at audit time

| File | Size | Rows | Notes |
|---|---|---|---|
| `events.jsonl` | 1.3M | 4309 | populated by event_writer |
| `events.sqlite` | 25k | events: **0**, meta: 1 (`schema_version=4`) | indexer never ran |
| `events.sqlite.cursor` | — | `1266024` | cursor file present anyway |
| `hook-events.jsonl` | 1.3M | 4365 | populated by collect_hook_event |
| `improvement-queue.jsonl` | 0 | 0 | legitimately empty |
| `recommendations.json` | 163B | `recommendations: []`, `fallback_mode: true` | empty payload |
| `baseline.json` / `skill-usage.json` / `skill-map.json` / `skill-impact.json` | small | n/a | written by init/refresh; not surfaced by alc_query |
| `reports/latest-approved-gates.md` | 11 lines | 0 gates (placeholder `- none`) | well-formed but empty |
| `reports/latest-skill-context.md` | 15 lines | content present | render works |
| `reports/latest-next-action.json` | 21 lines | cached `next_action` output | write-only cache, never read back |
| `reports/latest-session-context.md` | — | **absent** | `alc_init` never run on this repo |

Pipeline-A symptom confirmed: `event_writer` (and `collect_hook_event`) only
write to JSONL; `index_events` is the only thing that fills `events.sqlite`,
and it hasn't run.

## Per-tool table

### MCP read surface (called via stdio handshake against `alc_mcp/server.py`)

| Tool | Backing | Expected | Actual | Severity | Notes |
|---|---|---|---|---|---|
| `get_gates` (M1) | `alc_query.get_gates` | array of gates parsed from `latest-approved-gates.md` | `[]` | LOW | Legitimately empty — gates file is the `- none` placeholder. Parser works on real input. |
| `get_skill_context` (M2) | `alc_query.get_skill_context` | markdown string | full 15-line string | OK | The one read tool that works as designed. |
| `get_recommendations` (M3) | `alc_query.get_recommendations` | array of rec rows | `[]` | **HIGH (latent bug)** | Reader looks up the `items` key; `analyst_score` writes the `recommendations` key. Confirmed via a synthetic file: reader returns `[]` even when 2 rows are present. Only reason it's "correct" today is that the live file has `recommendations: []`. |
| `list_pending_patches` (M4) | `alc_query.get_pending_patches` | array of patch bundles | `[]` | OK | `patches/` directory doesn't exist; correctly returns `[]`. |
| `get_dashboard_url` (M5) | `state_handle.dashboard_url` | localhost URL when dashboard is up; else file:// fallback | `file:///…/dashboard` (directory URI) | LOW | No `server.json` marker → falls through to `dashboard_dir.as_uri()`. Returns a directory URL, not the actual `dashboard.html`. Slightly misleading. |
| `propose_apply` (M6) | `alc_propose.propose_apply` | command string | `bin/alc_apply --patch <id> --write` | LOW | Returns command without verifying the patch exists; tested with `patch_id="nonexistent-patch-xxx"` — still synthesised a command. Documented as propose-only, so likely intentional. |
| `propose_gate` (M7) | `alc_propose.propose_gate` | queue_id; appends to `improvement-queue.jsonl` | not exercised destructively (write) | OK | No matching read tool — `alc_query` does not expose the improvement queue. Operator can write but cannot read back. See gap below. |
| `report_outcome` (M8) | `alc_propose.report_outcome` | `{recorded, event_id}` | not exercised destructively | OK | Writes via event_writer → events.jsonl only; will not show up in any read tool until `index_events` runs. |
| `report_agent_event` (M9) | `alc_propose.report_agent_event` | `{recorded, event_id, event}` | not exercised destructively | OK | Same pipeline-A blast radius as M8. |
| `exec_sandbox` (M10) | `exec_sandbox.run` | `{exit_code, stdout, stderr, event_id, run_id}` | full payload returned; `exit_code=3` for `echo hello` (not in allowlist), with sandbox-runs directory created | OK | Confirms sandbox surface is functional and event writes happen; emitted event goes to `events.jsonl` (not surfaced via any read tool). |
| `next_action` (M11) | `alc_next_action.next_action` | synthesis based on real signals | `"No pending work — quiet state. Good time to brainstorm."` for `auto`, `start`, `next`; recap says "No activity in 7 days"; leftoff says "starting fresh". Same answer for all 5 intents because all signals are zero. | **HIGH** | All signals come from `alc_query` which all return `[]`. With 4309 events on disk, calling this synth "quiet state" is materially wrong. Cache write to `latest-next-action.json` succeeds but cache is never read back. Verdict-counting fallback (lines 145-151) classifies *every unknown event* as `approve` — would cause silent miscounts once events.sqlite is populated. |
| `list_capabilities` | inline | M1-M11 metadata | array of 11 specs (id M1-M11) | OK | Description text says "Return M1-M10" — off-by-one comment/string mismatch since M11 was added. Cosmetic. |

All MCP calls succeed without crashing — the failure mode is silent emptiness, not errors.

### `bin/alc_query.py` direct-call surface (verbatim from a short Python harness)

| Function | Returns | Why | Severity |
|---|---|---|---|
| `get_gates(state)` | `[]` | Legit empty (gates file has `- none`) | OK |
| `get_recommendations(state)` | `[]` | **`items` vs `recommendations` key mismatch** with `analyst_score` writer | HIGH (latent) |
| `get_pending_patches(state)` | `[]` | `patches/` dir absent — legit | OK |
| `get_apply_log(state)` | `[]` | events.sqlite has 0 events rows | HIGH (pipeline-A blocked) |
| `get_outcomes(state)` | `[]` | events.sqlite has 0 events rows | HIGH (pipeline-A blocked) |
| `get_actor_summary(state)` | `{since: '7d', total: 0, by_actor_kind: []}` | events.sqlite empty | HIGH (pipeline-A blocked) |
| `get_skill_usage_summary(state)` | `[]` | events.sqlite empty | HIGH (pipeline-A blocked) |
| `get_event_dag(state, "session")` | `{session_id: 'session', nodes: []}` | events.sqlite empty | HIGH (pipeline-A blocked) |
| `get_skill_invocation_history(state, "claude")` | `[]` | events.sqlite empty AND jsonl fallback is broken (see below) | HIGH (pipeline-A blocked + parser bug) |
| `get_skill_context(state)` | full markdown string | reads `.md` file directly | OK |

### Other read paths

| Component | Through alc_query? | Behavior on partial state | Severity |
|---|---|---|---|
| `bin/render_state_surface --format markdown` | Reads `.md` files directly (acceptable — non-data surfaces) | Concatenates gates + skill-context + alc-core SKILL.md. `latest-session-context.md` is silently skipped if missing (which it is). | LOW (silent skip) |
| `bin/render_state_surface --format json` | Yes (`get_pending_patches`, `get_recommendations`, `get_actor_summary`, `get_apply_log`) | Returns all-zero counts + `mcp_status: configured`. All numbers wrong for the same reason as M11. | HIGH |
| `bin/render_state_surface --format session-report` | Yes (same five) | Writes `latest-session-report.md` saying "No events / No apply events / No verdict events / Nothing pending" despite 4365 hook events on disk. Rotates prior copies to `.001`. | HIGH |
| `bin/render_state_surface --format html` | Goes through `skills/alc-dashboard/server.py:build_data_blob` | Same emptiness; data.json shows zero rows. | HIGH |
| `skills/alc-dashboard/server.py` (stdlib dashboard) | Yes for events; reads `recommendations.json`, `latest-approved-gates.md`, `latest-skill-context.md` directly; also reads `suggestions.json` directly (which `alc_query` doesn't expose at all) | All counts zero; markdown surfaces render. | MEDIUM (one KTD-21 violation: `suggestions.json` is read inline) |
| `dashboard/__init__.py` (FastAPI dashboard) | **No — bypasses alc_query** | `/api/data` calls `render_dashboard.build_dashboard_data(personal, history_limit=180)` which reads `metrics.jsonl` and the embedded `<script id="report-payload">` from the latest archived report HTML. Has its own data-shape disconnected from `alc_query`. | **HIGH (KTD-21 violation)** |
| `bin/render_dashboard` | **No — direct file reads** | Reads `metrics.jsonl` line-by-line and parses embedded JSON from HTML files. None of this goes via `alc_query`. | KTD-21 violation |
| `bin/alc_init` → `render_runtime_summary_md` | Yes (5 alc_query reads) | Generated session-context section says "No durable runtime history yet" and "No tracked invocations of CE skills" — misleading given the 4365 hook events. CE-usage line returns the placeholder text. | HIGH |

## What's silently empty (returns `[]`/`{}` when the upstream pipeline should be producing data)

1. **`get_recommendations`** (M3) — `items` vs `recommendations` key bug. Will return `[]` even after `analyst_score` produces real recommendations.
2. **All sqlite-backed reads** (`get_apply_log`, `get_outcomes`, `get_actor_summary`, `get_skill_usage_summary`, `get_event_dag`, `get_skill_invocation_history`) — return `[]` because `events.sqlite` is empty (pipeline-A). No fallback to `events.jsonl`.
3. **`get_skill_invocation_history`** — has a fallback path that reads `events.jsonl` via `_read_json`, but `_read_json` treats the file as a single JSON document. `events.jsonl` is **JSON-LINES** (one object per line), so `_read_json` always returns `None` → fallback is dead code.
4. **`next_action`** (all 5 intents) — every signal is zero, so every intent returns the "quiet/idle/starting fresh" branch. The verdict-counting fallback (correlation_chain parsing) buckets every unknown verdict into `approve` — a future correctness bug.
5. **`render_state_surface` json + session-report + html** — same emptiness propagated to operator-facing surfaces.
6. **`render_runtime_summary_md`** (used by `alc_init`) — emits "No durable runtime history yet" + "No tracked invocations" placeholder text.

## What's actually working

- `get_skill_context` (markdown read of `latest-skill-context.md`).
- `get_gates` parser (correctly returns `[]` for the `- none` placeholder; not yet tested against a real populated gates file in this audit, but the parser logic looks sound).
- `get_pending_patches` (correctly empty when `patches/` dir absent).
- `render_state_surface --format markdown` (concatenates the three durable markdown surfaces + alc-core SKILL.md).
- MCP handshake / `tools/list` / `list_capabilities` (12 tools listed correctly).
- `exec_sandbox` (sandbox creation, run, event-write all happen — even when command is denied; failure mode is reported via `exit_code: 3`).
- `propose_apply` (returns CLI command without mutation, as intended; does not validate patch existence).

## KTD-21 violations (code reading sqlite/jsonl outside `alc_query.py`)

| File | What it reads directly | Severity | Notes |
|---|---|---|---|
| `bin/analyst_queries.py` | `events.sqlite` via `sqlite3.connect(...)` | HIGH | All 10 `query_q*` analysts (`bin/analyst_anomalies`, `bin/analyst_correlations`, `bin/analyst_patterns`, `bin/analyst_score`) depend on this. This is a parallel read surface, not the canonical one — by design or by drift? |
| `bin/sandbox_run_state.py` | `events.sqlite` connection (writes own `exec_sandbox_runs` table) | LOW | Separate table; sandbox lifecycle state, not events. Justifiable. |
| `bin/index_events` | reads `events.jsonl`, writes `events.sqlite` | NONE | This is the indexer, the legitimate writer. |
| `bin/render_dashboard` | reads `metrics.jsonl` and `*.html` report payloads directly | HIGH | The FastAPI dashboard's whole data layer bypasses `alc_query`. |
| `dashboard/__init__.py` | reads `metrics.jsonl` indirectly via `render_dashboard.build_dashboard_data`, and reads `latest-report.html`/`*.md` directly | HIGH | `/api/data`, `/api/reports/latest`, `/api/reports/latest.md` all bypass `alc_query`. |
| `skills/alc-dashboard/server.py` | reads `suggestions.json` directly via `_read_suggestions` | MEDIUM | One small inline read; everything else goes through `alc_query`. |
| `bin/alc_propose.py` | reads / appends to `improvement-queue.jsonl` and `patches/<id>.json` directly | NONE (write side) | Acceptable on the write side; but no read mirror exists in `alc_query`. |

## Additional findings

- **No improvement-queue read tool.** `propose_gate` writes to `improvement-queue.jsonl`; nothing in `alc_query` or the MCP catalog exposes the queue contents. Operator-proposed gates are write-only from the MCP surface.
- **`latest-next-action.json` cache is write-only.** `alc_next_action.next_action` writes it on every call, but no code reads it back. The cache buys nothing and slightly increases write pressure.
- **`list_capabilities` description string says "M1-M10"**, not M1-M11 (alc_mcp/server.py:167). Cosmetic.
- **`get_dashboard_url` fallback returns a directory URI**, not the actual `dashboard.html` inside it. The `dashboard.html` and `data.json` files exist; the URL helper could point at the file but doesn't.
- **`next_action` verdict miscounting**: in `_collect_signals`, lines 145-151 fall through to `verdict_counts["approve"] += 1` whenever the verdict can't be classified (no chain, JSON decode error, unknown verdict string). Once events.sqlite contains real `eval_verdict` rows, this will over-report approvals.
- **State-file consistency**: `events.sqlite.cursor` says `1266024` despite `events` table having 0 rows. Either the indexer started, advanced the cursor, then never wrote — or the cursor was set manually and rows were lost.

## Recommendation: broken vs legitimately empty

**Should be considered broken until pipeline-A fixes land** (will return `[]` / `0` regardless of real activity):

- `get_apply_log`, `get_outcomes`, `get_actor_summary`, `get_skill_usage_summary`, `get_event_dag`, `get_skill_invocation_history`
- `next_action` (all 6 intents)
- `render_state_surface --format json` (counts)
- `render_state_surface --format session-report` (the whole report body)
- `render_state_surface --format html` (zero counts, zero activity)
- `bin/alc_init` runtime synthesis (`render_runtime_summary_md`, `render_ce_usage_md`)
- `bin/render_dashboard` and `dashboard/__init__.py` (depend on `metrics.jsonl` and report-payload HTML — separate from events pipeline but same effective blackhole if those upstream files aren't fresh)

**Independently broken** (will return wrong/empty data even after pipeline-A is fixed):

- `get_recommendations` — `items` vs `recommendations` key mismatch.
- `get_skill_invocation_history` — JSONL fallback is dead because `_read_json` doesn't understand JSON-LINES.
- `next_action` verdict bucketing — unknown verdicts silently bucketed as `approve`.

**Legitimately empty** (will start returning data when something writes to the relevant file):

- `get_gates` (gates file is `- none`; parser is correct).
- `get_pending_patches` (no `patches/` dir).
- `list_pending_patches`.

**Working correctly today**:

- `get_skill_context`, `list_capabilities`, `propose_apply` (within its scope), `exec_sandbox`, `render_state_surface --format markdown`.

**Architectural follow-ups worth weighing** (not "broken" but worth a decision):

- Bring the FastAPI dashboard and `render_dashboard` under `alc_query` (currently the largest KTD-21 violation by surface area).
- Add a read mirror for `improvement-queue.jsonl` so `propose_gate` isn't write-only.
- Decide whether `analyst_queries.py` is a deliberate second read surface (cohabits with `alc_query`) or drift; if deliberate, document the boundary; if not, fold it in.
- Add an `events.jsonl` fallback layer in `alc_query` so the read surface degrades gracefully when the indexer is stale — would have masked pipeline-A entirely instead of silencing every read tool.
