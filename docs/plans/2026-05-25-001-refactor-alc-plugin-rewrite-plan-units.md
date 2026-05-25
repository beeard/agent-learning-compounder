# Refactor: ALC Plugin Rewrite — Implementation Units

> **Plan structure (post pass-7 split):** This file is the IMPLEMENTER VIEW (22 detailed implementation units, U1-U19 + U5.5 + U10.5 + U13.5). Companion: `2026-05-25-001-refactor-alc-plugin-rewrite-plan.md` has the executive overview + decisions + roadmap + verification strategy.

## Implementation Units


### U1. Worktree + baseline test snapshot

**Goal:** Isolated workspace; record current passing-test count as floor for the rewrite.

**Requirements:** (setup, not requirements-derived)

**Dependencies:** none

**Files:**
- Worktree ALREADY exists at `~/work/active/agent-learning-compounder-v2/` on branch `alc-plugin-v2` (pre-flight setup before LFG; pushed to `origin/alc-plugin-v2`)
- Touch: none in main repo

**Approach:**
- LFG runs in worktree directory; all code work in subdir `agent-learning-compounder/` per CLAUDE.md dual-tree convention
- Run all three existing test suites and record pass counts:
  ```bash
  cd /home/tth/work/active/agent-learning-compounder-v2/agent-learning-compounder
  python3 -m unittest discover -s fixtures/tests 2>&1 | tail -3
  python3 -m unittest discover -s tests 2>&1 | tail -3
  python3 scripts/run_pressure_tests.py 2>&1 | tail -3
  ```
- Verify the existing `dashboard/` FastAPI app still imports
- Initialize `scripts/spike/RESULTS.md` with baseline test counts + dry-run gate template

**Patterns to follow:** worktree already set up; just verify + record baseline

**Test scenarios:** Test expectation: none -- workspace verification, not behavioral change.

**Verification:** worktree at `~/work/active/agent-learning-compounder-v2/` on branch `alc-plugin-v2`; all three test suites green; baseline pass counts recorded in `scripts/spike/RESULTS.md`.

---

### U2. Three validation gates (premise, runtime, schema)

**Goal:** Empirically verify the premise that this rewrite is worth doing, AND verify two runtime assumptions the V1 plan made silently.

**Requirements:** R1, R2, R7

**Dependencies:** U1

**Files:**
- Create: `scripts/spike/spike_validate_premise.sh` (G0.5.1 driver)
- Create: `scripts/spike/spike_validate_runtime.sh` (G0.5.2 driver)
- Create: `scripts/spike/spike_validate_schema.sh` (G0.5.3 driver)
- Create: `scripts/spike/RESULTS.md` (manual grading rubric + outcomes)

**Approach:**
- **G0.5.1 (premise, 4h):** Run analyst prototypes against the user's real `~/.claude/projects` corpus. Use the other session's adapter at `/home/tth/alc-agent-native-audit-export-2026-05-25T17-16-05/scripts/alc-session-metrics-adapter.mjs` to produce `samples.json` from `claude-insights-extracted.mjs --json` output. Then dry-run pattern/anomaly/correlation/scoring scripts against this real data. Manually grade top-10 recommendations: are ≥3 non-obvious AND actionable?
- **G0.5.2 (cross-runtime, 1h):** Verify `${CLAUDE_PLUGIN_ROOT}` works in Claude; verify `.codex-plugin/plugin.json` discovery (or absence thereof) in Codex; verify AGENTS.md auto-load behavior in Codex.
- **G0.5.3 (data-schema, 1h):** Find existing `hook-events.jsonl` files; confirm schema; locate any `session-report` cost-tokens data; determine path to `{id, cost, tokens, duration_s}`.

**Patterns to follow:** S4 for manifest parity; RESULTS.md mirrors CONSOLIDATED-REVIEW §2 gate format

**Test scenarios:** Test expectation: none -- these are manual validation scripts, not unit tests. Pass/fail is recorded in RESULTS.md.

**Verification:** RESULTS.md committed with explicit pass/fail per gate. Decision committed: either "proceed to Phase B" or "scope collapse: drop Phase D-F, ship only U3 + U4 + U5".

---

### U3. Plugin shell (cross-runtime manifests, runtime entry files)

**Goal:** Establish plugin discovery surface for Claude (+ Codex if G0.5.2 was green).

**Requirements:** R7, R9

**Dependencies:** U1, U2 (gate G0.5.2 outcome dictates Codex scope)

**Files:**
- Create: `.claude-plugin/plugin.json`
- Create: `CLAUDE.md`
- Create (conditional on G0.5.2 green): `.codex-plugin/plugin.json`, `AGENTS.md`, `scripts/sync-to-codex-plugin.sh`
- Create: `tests/test_cross_runtime.py` (manifest parity + presence checks)
- Modify: `README.md` (add plugin-shell overview)

**Approach:**
- Manifest references `./skills/`, `./agents/`, `./commands/`, `./hooks/hooks.json`
- CLAUDE.md / AGENTS.md describe entry points (`/alc-report`), available MCP tools, and operating rules
- If G0.5.2 was green for AGENTS.md only (not `.codex-plugin/`): drop the Codex manifest, keep only AGENTS.md, content-level parity test instead of file-level
- If G0.5.2 was red entirely: skip Codex entirely; plan continues Claude-only

**Patterns to follow:** S4 (cross-runtime manifest parity)

**Test scenarios:**
- `.claude-plugin/plugin.json` parses as valid JSON with required fields (name, version, description)
- (if Codex green) `.codex-plugin/plugin.json` parses; key fields (name, version, description) match Claude manifest
- (if Codex green) `sync-to-codex-plugin.sh` is executable and produces parity after running
- CLAUDE.md and AGENTS.md both reference the same core commands (`init_learning_system`, `render_unified_report`)
- Existing tests still pass (no regression from new files)

**Verification:** `python3 -m unittest tests.test_cross_runtime -v` passes; existing test suite still green.

---

### U4. Refactor existing SKILL.md → skills/alc-core/SKILL.md

**Goal:** Move root-level SKILL.md into sub-skill location without disturbing runtime; existing `bin/*` scripts continue to work.

**Requirements:** R9 (sub-skill collapse)

**Dependencies:** U3

**Files:**
- Move: `SKILL.md` → `skills/alc-core/SKILL.md`
- Move: `references/` → `skills/alc-core/references/`
- Create: `skills/alc-core/scripts` (symlink to `../../bin/`)
- Modify: `skills/alc-core/SKILL.md` frontmatter (`name: alc-core`, updated description)
- Update: any internal paths from `scripts/foo.py` to `../../bin/foo`

**Approach:**
- `git mv` preserves history
- Symlink `scripts/` keeps existing references in `bin/`-callers valid
- Add note in SKILL.md that the live skill discovery only updates on next session (per Hermes-pattern documentation: ROOT 13)
- Confirm worktree-vs-live distinction: the worktree at `../alc-plugin-v2/` is not symlinked into `~/.claude/skills/` until merge at end of U19

**Patterns to follow:** S1 (Hermes skill layout)

**Test scenarios:**
- `skills/alc-core/SKILL.md` exists with valid frontmatter (`name: alc-core`, description present, ≤1024 chars)
- `skills/alc-core/scripts/init_learning_system` resolves (symlink valid)
- `skills/alc-core/references/architecture.md` exists (moved correctly)
- All existing `bin/*` scripts still execute (smoke: `python3 bin/distill_learning --help`)

**Verification:** `tests/test_cross_runtime.TestAlcCoreSkill` passes; all existing fixture tests still pass.

---

### U5. Session-metrics synthesizer (`bin/synthesize_samples`)

**Goal:** Produce real `samples.json` so analyst scripts have actual data. This is the keystone fix for ROOT 1.

**Requirements:** R2

**Dependencies:** U2 (G0.5.3 schema-discovery outcome dictates implementation)

**Files:**
- Create: `bin/synthesize_samples`
- Create: `bin/synthesize_samples.py` (symlink for `scripts/` parity)
- Create: `tests/test_synthesize_samples.py`
- Modify: `data-contracts.json` (add `session-metrics` entry — but data-contracts.json itself doesn't exist yet; see U6)

**Approach:**
- Two implementation paths depending on G0.5.3:
 - **Path A (preferred if `alc-session-metrics-adapter.mjs` is reusable):** Python wrapper that shells out to the node adapter, normalizes JSON to ALC's expected shape, writes to `samples.json`. ~40 lines.
 - **Path B (if node-based adapter not viable):** Pure-Python implementation that reads `hook-events.jsonl` + optional session-report data, computes per-session `{id, cost, tokens, duration_s, skill?, model?, outcome?}`. ~80 lines.
- Input: configurable via `--source hook-events|claude-insights|combined`
- Output: `<state>/samples.json` (path resolved via StateHandle when U7 lands)
- Bounded telemetry: no raw prompts, no transcript chunks, no absolute paths in output

**Patterns to follow:** S6 (bounded telemetry + scrubbing); alc-session-metrics-adapter.mjs from /home/tth/alc-agent-native-audit-export-2026-05-25T17-16-05/scripts/ as algorithmic reference

**Test scenarios:**
- Synthesizer produces valid `samples.json` from a fixture corpus with known {id, cost, tokens, duration_s}
- Empty input → empty array with `reason` field, not crash
- Input containing secrets (regex `sk-...`, `bearer ...`) → secrets scrubbed in output
- Absolute paths in input → relative paths in output
- Sample count matches input session count (no dedup loss)
- Output passes `bin/validate_artifacts` (once U6 lands)

**Verification:** `python3 -m unittest tests.test_synthesize_samples -v` passes; manual: run synthesizer on real `~/.claude/projects`, sample count > 0, no secrets in output.

---

### U5.5. Comprehensive event ingestion (unified stream from all emitters)

**Goal:** All event sources (Claude hooks, Codex hooks, MCP tools, subagent dispatches, background agents, parsed transcripts) emit to ONE normalized stream with correlation chain + actor attribution + per-event telemetry. SQLite mirror provides query-layer for analyst joins.

**Requirements:** R21, R22, R23, R24, R25

**Dependencies:** U5 (synthesizer establishes the normalization-toward-bounded-fields pattern), U6 (data-contracts registers the new events.sqlite + events.jsonl + transcripts archive)

**Files:**
- Create: `bin/event_schema.py` (— Python-dataclass som single source of truth for v4-schema)
- Create: `bin/event_writer.py` (— delt write-path: normalize + scrub + flock + rotate)
- Modify: `bin/install_runtime_hooks` (expand DEFAULT_EVENTS)
- Modify: `bin/collect_hook_event` (now becomes a thin adapter: maps hook-payload → event_writer.write_event())
- Create: `bin/ingest_transcripts`, `bin/ingest_transcripts.py` (thin adapter)
- Create: `bin/correlate_events`, `bin/correlate_events.py` (thin adapter)
- Create: `bin/event_emit`, `bin/event_emit.py` (thin adapter)
- Create: `bin/index_events`, `bin/index_events.py` (reads `EventV4.sqlite_ddl()` for schema)
- Create: `tests/test_event_schema.py` dataclass + DDL-gen + JSONSchema-gen tests)
- Create: `tests/test_event_writer.py` delt write-path: normalize + scrub + flock + rotate + idempotency)
- Create: `tests/test_event_schema_v4_compat.py` (backward-compat: v3 rows readable)
- Create: `tests/test_ingest_transcripts.py`
- Create: `tests/test_correlate_events.py`
- Create: `tests/test_event_emit.py`
- Create: `tests/test_index_events.py`
- Create: `skills/alc-core/references/event-taxonomy.md` (henviser til `bin/event_schema.py` som source-of-truth; ingen schema-tabell duplisert)
- Modify: existing `bin/auto_distill_session`, `bin/refresh_learning_state` (wrap with `event_emit()` at start/end so background activity becomes visible in stream)

**Approach:**

Two **foundation modules** sequential first, then five **parallel-safe** thin adapters (arch-pass-5 F3: 5.5.1-5.5.5 can be dispatched as 5 parallel subagents once 0a + 0b are committed):

- **U5.5.0a (45 min) — `bin/event_schema.py` — single source of truth (arch-#2):**
 - `@dataclass EventV4` med alle felter (event_id, ts, event, schema_version, actor: ActorInfo, telemetry: Telemetry, correlation_chain: list[ChainLink], …)
 - Klasse-metoder: `EventV4.sqlite_ddl() -> str` (auto-generert CREATE TABLE + indices fra dataclass), `EventV4.jsonschema() -> dict` (auto-generert JSONSchema fra felter + type-hints), `EventV4.from_dict(raw) -> EventV4` (validator + bounded-field-clamping), `EventV4.to_dict() -> dict` (serializer for events.jsonl)
 - Forward-compat hook: `EventV4.upgrade_from(v3_row: dict) -> EventV4` håndterer skjema_version=3 rows (missing fields = None)
 - `index_events.py` kaller `EventV4.sqlite_ddl()` — INGEN duplisert SQL i index-scriptet
 - `data-contracts.json` events-entry henviser til `bin/event_schema.py:EventV4` (string path), ikke flate skjemafelt
 - Effort: 45 min for dataclass + auto-gen helpers. Saves N timer i schema-drift-bugs senere.

- **U5.5.0b (45 min, +15 min for boundary-enforcement) — `bin/event_writer.py` — delt write-path (arch-#1) + boundary-invariant (arch-#3):**
 - `write_event(raw_or_dataclass, source: Literal["hook","transcript","correlation","background","apply","eval"]) -> str` (returnerer event_id)
 - `write_events_batch(rows, source) -> list[str]` (én flock-acquire for hele batch — perf for backfill)
 - Eier internt: `EventV4.from_dict(raw)` validering, `scrub_secrets()` på free-text felter, `bounded()` på alle string-felter, **`_enforce_boundary(event)` som hever ValueError på brudd**, `fcntl.flock` på `<state>/.events.lock`, atomic append-with-rotate til `<state>/events.jsonl`, ny `event_id` hvis ikke i raw
 - `_enforce_boundary(event)` regelsett:
 - Ingen secret-patterns (regex: `sk-`, `bearer `, `aws_access_key_`, `ghp_`, `gho_`, etc.) i serialisert event
 - Ingen absolute host paths (`/home/`, `/Users/`, `C:\Users\`)
 - Ingen string-felt > MAX_LINE_LEN (200 chars) i loadable surfaces
 - Ingen base64-blob > MAX_BLOB_SIZE (1KB) UNLESS event-kind in `{patch_applied, patch_reverted}` (original_bytes_b64 er nødvendig for revert) — i så fall scrub_secrets must have run AND blob må bestå secret-pattern-test
 - Ingen raw transcript chunk (regex: assistant/user-tag fra Claude/Codex format)
 - Source-felt tagged inn i event for audit-debug (telemetry, ikke kanonisk schema). NB: `source` indirekte autoriserer hvilke event-typer som er valid (apply → kun `patch_*`-events, eval → kun `eval_*`-events) — defense-in-depth.
 - Same `_enforce_boundary`-funksjon er importert av `bin/artifact_writer.py` (U6) for konsistent enforcement på ikke-events-artifacts (patches/, alc-agents/)

Five sub-deliverables — **all five are parallel-dispatchable** once 0a + 0b foundation lands. Each is a thin adapter (~25-40 linjer) over event_writer with its own test file and zero shared mutable state. Wave-3 dispatcher spawns 5 subagents in parallel:

- **U5.5.1 (30 min) — Expand `DEFAULT_EVENTS` taxonomy + Codex mapping:**
 - Add to `bin/install_runtime_hooks:21`: `SubagentStop`, `SessionEnd`, `Notification`, `PreCompact` (Claude)
 - Codex mapping moves OUT of Python into `skills/alc-core/references/event-sources.json` arch-#5 partial — deklarativ data ikke hardkodet dict):
 ```json
 [
 {"runtime": "claude", "name": "PreToolUse", "normalized": "pre_tool_use"},
 {"runtime": "codex", "name": "before_tool", "normalized": "pre_tool_use"},
 ...
 ]
 ```
 - install_runtime_hooks reads this file; future runtime (OpenCode, Gemini) = new data-rows, ingen kode-endring
 - Re-run `install_runtime_hooks --apply` after upgrade adds entries for new events without removing existing ones

- **U5.5.2 (45 min, redusert fra 1h) — Splitt til to thin adapters:**
 - `bin/backfill_transcripts`: engang-bruk via `--since <duration>`, leser ALLE transcripts i vinduet, kaller `event_writer.write_events_batch(...)`. Egen idempotency (event_id derived deterministisk fra path+offset så re-run gir samme ids).
 - `bin/ingest_new_transcripts`: live, invoked av hooks/post-distill, leser kun nye transcripts siden cursor i `<state>/.transcript-cursor`. Kaller `event_writer.write_event(...)`.
 - Begge sharer parsing-helpers via `bin/transcript_parser.py` (Claude + Codex transcript format readers, returner iterables av raw event-dicts)
 - Hverken script eier flock/scrub/rotate — det er `event_writer.py`s ansvar

- **U5.5.3 (45 min) — `bin/correlate_events` thin adapter:**
 - Reads `events.jsonl`, computes DAG-edges, calls `event_writer.write_events_batch(...)` for derived events (`tool_use_pair`, `subagent_run`)
 - **Drops `event-graph.json`**: dashboard queryer events.sqlite med recursive CTE for DAG-walk i stedet. Færre filer, færre sync-poenger.
 - Tester: recursive CTE returnerer riktig DAG på fixture-data (validerer at SQL er rask nok — fallback til JSON-cache hvis &gt;100ms)

- **U5.5.4 (30 min) — `bin/event_emit` thin adapter:**
 - CLI + Python API som mapper input til `event_writer.write_event(...)` med `source="background"`
 - Wraps `bin/auto_distill_session`, `bin/refresh_learning_state`, `bin/alc_eval` start/end

- **U5.5.5 (45 min, redusert fra 1h pga arch-#2) — `bin/index_events`:**
 - SQLite-skjema HENTET fra `EventV4.sqlite_ddl()` (ingen duplisert SQL)
 - Reads `<state>/events.jsonl` incrementally via `<state>/events.sqlite.cursor`
 - Idempotent + schema-version i sqlite-meta-tabell
 - Invoked av hooks/post-distill

**Schema_version 4 (R22) — new fields in `normalize_event()`:**

| Field | Type | Source |
|---|---|---|
| `event_id` | str (auto: `evt_{ts}_{shorthash}`) | computed |
| `correlation_chain` | list[{role, id}] | passed in or derived from runtime payload |
| `parent_event_id` | str | passed in or derived |
| `actor.kind` | enum: main_agent\|subagent\|background_agent\|mcp_server\|hook | required |
| `actor.name` | bounded str | required |
| `actor.model` | bounded str | optional |
| `actor.parent_actor_id` | str | optional |
| `telemetry.duration_ms` | int | optional |
| `telemetry.tokens_in` | int | optional |
| `telemetry.tokens_out` | int | optional |
| `telemetry.cache_read_tokens` | int | optional |
| `telemetry.cache_creation_tokens` | int | optional |
| `telemetry.cost_usd` | float | optional |
| `telemetry.interrupted` | bool | optional |
| `tool_server` | str (e.g. `mcp:github`, `claude-builtin`) | derived from tool name prefix |
| `error_class` | str | optional, when outcome=error |
| `schema_version` | int = 4 | constant |

Backward compat (KTD-14): readers must treat v3 rows (existing) as v4 rows with missing fields = None. Analyst queries that require new fields filter `WHERE schema_version >= 4`.

**Patterns to follow:** S6 (normalize_event shape + scrubbing), S5 (Claude JSONL parsing)

**Test scenarios:**

- **Event schema (R22):**
 - `normalize_event(raw_v3)` returns dict with schema_version=4, missing-field-tolerant
 - `normalize_event(raw_v4)` returns dict with all v4 fields populated
 - `correlation_chain` validated: list of `{role: str, id: str}`, max depth 8, max id length 128
 - `actor.kind` rejected if not in enum
 - `telemetry.*` fields silently dropped if not numeric (no crash)
 - Total event size ≤ existing MAX_HOOK_EVENT_BYTES (telemetry compression-friendly)

- **Transcript ingest (R23):**
 - Parse Claude JSONL with mix of user/assistant/tool_use/tool_result → emits normalized events with correct correlation_chain
 - Parse Codex transcript → same shape (uses CODEX_EVENT_MAP)
 - Backfill `--since 30d` produces stable event_ids (rerun same input → same event_ids; idempotent)
 - Secret in transcript → scrubbed in event (`sk-ant-...` not present in output)
 - Absolute path in transcript → relativized in event.path
 - Malformed transcript line → skip + log warning, don't crash

- **Correlation (R24, derived):**
 - PreToolUse + PostToolUse pair → derived `tool_use_pair` event with duration_ms = ts_diff
 - Subagent_start without matching end → emit warning, don't fabricate pair
 - Nested subagent (subagent spawning subagent) → correlation_chain depth ≥ 4, parent_actor_id chain intact

- **Background emit (R25):**
 - `bin/event_emit --kind distill_run --actor-name scheduled-distill ...` writes valid event
 - Wrapped `auto_distill_session` emits `distill_start` + `distill_end` events; duration_ms in `distill_end` ≈ wall-clock
 - Emit without `--parent-event-id` → event becomes a root (parent_event_id=None)

- **SQLite index (R24):**
 - `bin/index_events` on fresh state creates schema with all indices
 - Incremental run with N new lines in events.jsonl → indexes N new rows; cursor advances
 - Query: `SELECT COUNT(*) FROM events WHERE session_id = ?` returns expected count
 - Query: `SELECT * FROM events WHERE actor_kind='subagent'` returns subagent events only
 - Schema-version mismatch → refuse, suggest re-index
 - Idempotency: second run with no new events → 0 rows added, exit clean

- **End-to-end:**
 - Trigger SessionStart → entry appears in events.jsonl + events.sqlite within 1s after hook
 - Trigger Task tool use (subagent dispatch) → start+end events both indexed; correlation_chain links them
 - MCP tool call (`mcp__github__get_pull_request`) → event has `tool_server='mcp:github'`, `actor.kind='mcp_server'`

**Verification:** `python3 -m unittest tests.test_event_schema_v4 tests.test_ingest_transcripts tests.test_correlate_events tests.test_event_emit tests.test_index_events -v` passes; manual: `bin/ingest_transcripts --backfill --since 7d` on real `~/.claude/projects`, query `events.sqlite` for actor-kind distribution, verify all 5 kinds present.

---

### U6. `data-contracts/` manifest-per-unit + `bin/validate_artifacts.py`

**Goal:** Producer/consumer registry split into per-unit manifests so parallel subagent dispatch doesn't fight over one hot file. Lifecycle fields per artifact. Validator concatenates manifests on read. NEW script, does not overload existing `bin/validate_outputs.py`.

**Requirements:** R6, R12, plus parallel-friendliness (per arch-pass-5 F1)

**Dependencies:** U3 (so we know the plugin shell exists)

**Files:**
- Create: `data-contracts/base.json` (U6 itself owns this — core ALC artifacts that exist before unit-specific ones)
- Create: `data-contracts/manifests/` (empty directory ready for per-unit manifests)
- Create: `data-contracts/README.md` (explains the split + how to add a manifest)
- Create: `bin/validate_artifacts`, `bin/validate_artifacts.py` (concatenates `base.json` + all `manifests/*.json` on read)
- Create: `bin/artifact_writer.py` (pre-write enforcement helper)
- Create: `bin/render_catalogs.py` (KTD-20: auto-render all catalog .md files from Python registries — MCP_TOOLS, GENERATORS, DSL_TARGETS, QUERIES, PROPOSALS, SANDBOX_TIERS)
- Create: `tests/test_data_contracts.py`
- Create: `tests/test_artifact_writer.py`
- Create: `tests/test_render_catalogs.py` (assert no drift: rendered markdown matches current Python state)

**Approach:**
- `data-contracts/base.json` lists core ALC artifacts owned by Phase B foundation: `corpus`, `baseline`, `gates`, `insights`, `events.jsonl`, `events.sqlite`
- Each downstream unit owns its own manifest file under `data-contracts/manifests/<unit-id>.json`:
  - `manifests/u5-synthesize.json` → `session-metrics`
  - `manifests/u5_5-events.json` → `events-derived`, `event-graph` (if reintroduced)
  - `manifests/u8-analyst.json` → `patterns`, `anomalies`, `correlations`, `recommendations`
  - `manifests/u9-recommender.json` → `patch-bundle`
  - `manifests/u10_5-query.json` → derived view registrations
  - `manifests/u11-apply.json` → `patch_applied-event`, `patch_reverted-event` (semantic registration)
  - `manifests/u12-invoke.json` → `subagent_invoke_*-event`
  - `manifests/u13-eval.json` → `eval_verdict-event`
  - `manifests/u14-reviewer.json` → `agents/alc-reviewer.md`
- Each artifact entry: `id`, `path_template`, `producer`, `consumers[]`, `surface_in_dashboard`, `format`, lifecycle fields (`create`, `read`, `update`, `delete_or_retention`, `owner`, `states`, `max_age`, `max_count`, `cleanup_command`)
- **`bin/artifact_writer.py`** is the helper module imported by all writers: `write_artifact(artifact_id, payload, state_handle)` enforces path-template + size + format pre-write. Reads merged registry at startup (concat base + manifests).
- **`bin/validate_artifacts`** provides `--check-contracts --state-dir <dir>` mode for post-hoc orphan-detection; `--check-pending-writes <writer-module>` verifies writer registers properly; `--show-registry` prints the merged registry for debugging.
- **Parallel safety:** subagents working on U8, U9, U10.5, U11, U12, U13 each create their own `manifests/<unit-id>.json` file → zero merge conflict on integration. Each manifest is owned exclusively by one unit.
- Existing `bin/validate_outputs.py` is UNTOUCHED (R6)

**Patterns to follow:** S1 (Hermes pre-write validator), S8 (atomic-write semantics)

**Test scenarios:**
- `data-contracts.json` parses and contains all required artifact IDs
- Each artifact entry has required fields (id, path_template, producer, consumers, lifecycle fields)
- `bin/validate_artifacts --check-contracts` accepts clean state-dir, rejects orphan file
- `bin/validate_artifacts --check-contracts` correctly handles templated dirs (`patches/*.json`, `analyst/*.json`) with wildcard recursion
- `bin/artifact_writer.py` rejects writes that violate path-template
- `bin/artifact_writer.py` rejects writes exceeding `max_size`
- Existing `bin/validate_outputs.py` still works with its positional-arg interface (R6)
- All `fixtures/tests/test_validate_outputs_*` still pass

**Verification:** `python3 -m unittest tests.test_data_contracts tests.test_artifact_writer -v` passes; `python3 -m unittest discover -s fixtures/tests` still passes.

---

### U7. StateHandle module (`bin/state_handle.py`)

**Goal:** One canonical state resolver imported by all surfaces (MCP, dashboard, hooks, distill, recommender, apply, invoke, eval).

**Requirements:** R11

**Dependencies:** U6 (data-contracts needed to know which paths to resolve)

**Files:**
- Create: `bin/state_handle.py`
- Create: `tests/test_state_handle.py`
- Modify: `bin/init_learning_system.py` (write `state_dir` to `.agent-learning.json`)
- Modify: existing `bin/state_paths.py` (deprecate, keep as thin wrapper around StateHandle)

**Approach:**
- `StateHandle` dataclass with read-only fields: `repo`, `state_root`, `repo_state_dir`, `reports_dir`, `dashboard_dir`, `alc_agents_dirs` (dict), `alc_apply_log`, `outcomes_json`
- Constructor `StateHandle.for_repo(repo_path)` reads `.agent-learning.json` first if present; falls back to existing resolution chain in `bin/state_paths.py`
- Migration: `init_learning_system.py` now writes resolved `state_dir` to `.agent-learning.json` so subsequent calls see consistent path
- `bin/state_paths.repo_state_dir(repo)` becomes a deprecation-warning wrapper: `StateHandle.for_repo(repo).repo_state_dir`

**Patterns to follow:** S9 (resolution chain wrapped by StateHandle)

**Test scenarios:**
- `StateHandle.for_repo(repo)` reads `state_dir` from `.agent-learning.json` when present
- Falls back to env var, then default chain, identical to existing `bin/state_paths.repo_state_dir`
- `alc_agents_dirs` returns dict with keys: dev, test, evals, personal
- All paths are absolute
- MCP, dashboard, orchestrator all resolve to same `repo_state_dir` for same repo
- Existing `bin/state_paths.py` callers still work (compat layer)

**Verification:** `python3 -m unittest tests.test_state_handle -v` passes; smoke: run `bin/init_learning_system --repo $PWD` then verify `.agent-learning.json` contains `state_dir`.

---

### U8. Analyst scripts (`bin/analyst_*`) — backed by events.sqlite

**Goal:** Pattern detection, anomaly detection, correlation, scoring — driven by `events.sqlite` joins (U5.5) for actor + correlation context, with `samples.json` (U5) as supplementary aggregate input.

**Requirements:** R9 (no separate sub-skill; flat bin/-prefix), R24 (analyst joins on actor/correlation, not only session aggregates)

**Dependencies:** U5, U5.5, U6, U7

**Files:**
- Create: `bin/analyst_patterns`, `bin/analyst_patterns.py`
- Create: `bin/analyst_anomalies`, `bin/analyst_anomalies.py`
- Create: `bin/analyst_correlations`, `bin/analyst_correlations.py`
- Create: `bin/analyst_score`, `bin/analyst_score.py`
- Create: `bin/analyst_queries.py` (shared SQL query library — reused by all 4 analyst scripts)
- Create: `tests/test_analyst_patterns.py`, `tests/test_analyst_anomalies.py`, `tests/test_analyst_correlations.py`, `tests/test_analyst_score.py`
- Create: `tests/test_analyst_queries.py` (SQL-level tests against fixture sqlite)
- Create: `skills/alc-core/references/analyst-methods.md`
- Create: `skills/alc-core/references/analyst-queries-catalog.md` (the optimization-questions catalog — see below)

**Approach:**
- All 4 analyst scripts open `<state>/events.sqlite` read-only via `bin/analyst_queries.py:open_events_db(state_handle)`
- Fallback: if events.sqlite missing (e.g., U5.5 disabled or first run before any indexing), scripts fall back to `samples.json` aggregate mode (less rich but still works)
- **`analyst_patterns`:** frequency + co-occurrence + time-clustering, BUT now also:
 - Frequency by `(skill, actor_kind)` — surface "skill X mostly invoked by subagents" patterns
 - Co-occurrence pairs derived from `correlation_chain` (parent→child events within 10s window)
 - Time-of-day patterns by `actor.name` — surface "background-agent X runs only at 02:00"
- **`analyst_anomalies`:** z-score + IQR on:
 - `duration_ms` per `(actor.name, event)` — "this Bash call took 5x typical for command_class=git"
 - `tokens_in + tokens_out` per `(actor.model, skill)` — surface model-cost outliers
 - `cost_usd` per `(actor.kind)` — subagent-cost spikes vs main-agent baseline
 - Includes Claude session-level rollups (sum of all child events per session) — frustration patterns
- **`analyst_correlations`:** richer correlation matrix using DAG joins:
 - Skill loaded at SessionStart × pass-rate on subsequent PostToolUse events (gate effectiveness)
 - `(parent_actor, child_actor)` pairs → which dispatches cost most relative to outcome
 - `tool_use_pair.duration_ms` per `command_class` → which tool calls are slow
 - Cache-hit ratio per session × model — caching effectiveness
- **`analyst_score`:** combines all of above + `outcomes.json` (R8/R20) into ranked recommendations
 - Score formula: `score = impact × confidence × outcome_weight × evidence_strength`
 - `evidence_strength` = log(N) where N is the count of events backing the pattern (more events = stronger evidence)
 - `outcome_weight = (1 + n_positive - n_negative) / (1 + total)` per kind, read from outcomes.json
 - First-run (no outcomes.json): outcome_weight = 1.0 (no penalty)
- Each script writes through `bin/artifact_writer.py` (R12)
- Every output entry carries `evidence` array — now with `event_ids[]` referencing rows in events.sqlite, not just (source_file, line_range)

**Optimization-questions catalog (R24 made concrete — written to `skills/alc-core/references/analyst-queries-catalog.md`):**

The catalog enumerates which optimization question each query in `bin/analyst_queries.py` answers. Each entry: name, SQL skeleton, output shape, which analyst script consumes it.

| Catalog ID | Question | Owner |
|---|---|---|
| Q1 | Which slash-command takes longest relative to its value? | analyst_anomalies + analyst_correlations |
| Q2 | Which model is overkill for which skill (high cost, high pass-rate)? | analyst_correlations |
| Q3 | Which subagent dispatch patterns spawn most expensive subagents? | analyst_correlations (DAG join) |
| Q4 | Which background agents fail silently? | analyst_anomalies (actor_kind=background_agent) |
| Q5 | Which gates load at SessionStart but never get used in same session? | analyst_correlations (gate_loaded_ids × subsequent events) |
| Q6 | What time-of-day buckets have shortest/longest sessions? | analyst_patterns (time_of_day) |
| Q7 | Which MCP servers are bottlenecks (avg duration_ms)? | analyst_anomalies (tool_server group) |
| Q8 | Frustration patterns: Stop within 30s after PostToolUse(error)? | analyst_correlations (temporal pair) |
| Q9 | Which skills have drifted (loaded freq dropped >50% over 30d)? | analyst_patterns (time-windowed compare) |
| Q10 | Eval-loop ROI: cost of eval vs. quality of resulting recommendations? | analyst_correlations (eval cost × subsequent outcome) |

**Patterns to follow:** S10 (z-score/IQR), S7 (evidence-attachment), S11 (SQLite read-only URI mode)

**Test scenarios:**
- `analyst_queries.open_events_db()` opens read-only; refuses if schema-version mismatch
- All analyst scripts fall back to samples.json if events.sqlite absent (test: remove sqlite, run analyst, no crash)
- `analyst_patterns` produces frequency by `(skill, actor_kind)` for fixture events
- `analyst_anomalies` flags z=4 cost sample when grouped by actor.name
- `analyst_anomalies` with N<min_n per (actor, event) bucket returns empty for that bucket but processes others
- `analyst_correlations` produces gate-effectiveness table: gates loaded at SessionStart × subsequent PostToolUse outcome
- `analyst_correlations` produces DAG-derived parent×child cost-attribution from fixture event-graph
- `analyst_score` with no outcomes.json applies neutral weight
- `analyst_score` with outcomes.json down-weights kinds with n_negative > n_positive
- `analyst_score` includes evidence_strength as log(n_supporting_events)
- Recommendation entries carry evidence with `event_ids[]` array (queryable in sqlite for drill-down)
- Each script writes through `artifact_writer` (rejects writes outside path-template)
- All outputs validate against `data-contracts.json` shape
- **Catalog coverage:** each Q1-Q10 has at least one test asserting the query produces expected shape on fixture data

**Verification:** `python3 -m unittest tests.test_analyst_* tests.test_analyst_queries -v` passes; smoke: index real events.sqlite (U5.5), run analyst pipeline, verify recommendations carry `event_ids[]` evidence and that at least 3 of catalog Q1-Q10 produce non-empty output on real data.

---

### U9. Recommender (`bin/recommender_generators.py` + `bin/recommender_render`)

**Goal:** Single `generators.py` with dispatch-dict literal emits Hermes-DSL ops for all 4 target_types. `recommender_render` orchestrator reads recommendations.json → writes patch bundles. Optional `--pre-validate` flag invokes `bin/exec_sandbox --scope worktree` (U13.5) to sandbox-validate each patch before writing — patches that fail their declared validation command are dropped from the bundle with logged reason.

**Requirements:** R9 (1 generators.py not 4 propose_*), R10 (no copy_to_clipboard in pipeline), R17 (Hermes-DSL), R18 (agent quality bar baked into agent-target generator), R26 (optional sandbox pre-validation)

**Dependencies:** U6, U7, U8, U13.5 (exec_sandbox — optional, only when `--pre-validate` flag set)

**Files:**
- Create: `bin/recommender_generators.py`
- Create: `bin/recommender_render`, `bin/recommender_render.py`
- Create: `tests/test_recommender_generators.py`
- Create: `tests/test_recommender_render.py`
- Create: `skills/alc-core/references/hermes-dsl-spec.md`

**Approach:**
- `recommender_generators.py` defines `GENERATORS: dict[str, GeneratorSpec]` literal (no auto-import, no side-effects)
- Each spec produces a Hermes-DSL op given a recommendation: `(rec) -> {skill_manage_op, preflight, revert_op}`
- Supported recommendation kinds map to ops:
 - `anomaly_investigate` → `action=patch, target_type=skill, target=skills/alc-core/SKILL.md` (or notes file)
 - `skill_routing_review` → `action=patch, target_type=skill, target=<gate file>`
 - `model_swap_candidate` → `action=patch, target_type=agent, target=agents/<agent>.md` with model field swap
 - `agent_spawn_suggestion` (NEW) → `action=create, target_type=agent, target=<state>/alc-agents/dev/<name>.md` with full content matching agent-creator quality bar
 - `workflow_chain` → NOT emitted as DSL op; written to a separate `<state>/suggestions.json` for dashboard render (separate from apply pipeline, R10)
- For `target_type=agent` ops, the generator constructs content matching all agent-validator rules (see U11): name pattern, description with 2-4 examples, 500-3000 word body with Role/Responsibilities/Process/Output sections
- `recommender_render` reads recommendations.json, iterates, calls generator per recommendation kind, writes `<state>/patches/<patch_id>.json` per op

**Patterns to follow:** S1 (Hermes DSL), S2 (agent content shape); KTD-15 named-catalog (G1-G5 in `references/generator-catalog.md`)

**Test scenarios:**
- `generators.py` exports `GENERATORS` dict with at least 5 kinds registered
- For each kind, calling generator produces dict with required fields (`skill_manage_op`, `preflight`, `revert_op`)
- Anomaly-investigate generator produces op with `target_type=skill`, valid `target` path
- Agent-spawn generator produces op with `target_type=agent`, content passing agent-validator
- Model-swap generator produces op with exact `old_string` / `new_string` strings (not regex)
- `workflow_chain` recommendations NOT in `<state>/patches/`; instead in `<state>/suggestions.json`
- `recommender_render` writes one bundle per recommendation
- Each bundle's `revert_op` is the inverse of `skill_manage_op` (swapped strings, same target)
- All bundles pass `validate_artifacts` against `data-contracts.json` patch-bundle entry
- No `copy_to_clipboard` apply_strategy appears anywhere (R10)

**Verification:** `python3 -m unittest tests.test_recommender_* -v` passes; smoke: seed analyst output, run `recommender_render`, inspect generated bundles — each is a valid Hermes-DSL op.

---

### U10.5. `bin/alc_query.py` + `bin/alc_propose.py` — symmetric read/propose seams

**Goal:** Two paired modules covering ALL read AND propose-write paths used by MCP/dashboard/CLI. Per KTD-21, no caller reimplements queue-write/scrub/event-emit/read-SQL inline.

**Requirements:** R16 (capability parity), KTD-13 (apply-log + outcomes are SQL views), KTD-21 (symmetric read/propose seams)

**Dependencies:** U5.5 (events.sqlite + event_writer), U7 (StateHandle)

**Files:**
- Create: `bin/alc_query.py` (read API)
- Create: `bin/alc_propose.py` (propose/write API — symmetric with alc_query)
- Create: `tests/test_alc_query.py`
- Create: `tests/test_alc_propose.py`
- Create: `skills/alc-core/references/{query-catalog.md,propose-catalog.md}` (auto-generated per KTD-20)

**Approach:**

*`bin/alc_query.py` — READ API:*
- Read-only by construction: opens events.sqlite via `sqlite3.connect(f'file:{path}?mode=ro', uri=True)`
- API (each function takes `state: StateHandle` first arg):
 - `get_apply_log(state, since=None, kind_filter=None) -> list[dict]` — SQL view over `event IN ('patch_*')`
 - `get_outcomes(state, since=None) -> list[dict]` — SQL view over `event='eval_verdict'`
 - `get_recommendations(state) -> list[dict]` — reads recommendations.json
 - `get_pending_patches(state) -> list[dict]` — reads patches/*.json, filters by status
 - `get_event_dag(state, session_id) -> dict` — recursive CTE for DAG-walk per session
 - `get_actor_summary(state, since='7d') -> dict` — aggregations per actor.kind, used by dashboard
 - `get_skill_invocation_history(state, skill_name) -> list[dict]` — for drill-down
- No function writes. No function takes user-controlled SQL.

*`bin/alc_propose.py` — PROPOSE/WRITE API (symmetric with alc_query, per KTD-21):*
- All propose-paths go through this module (queue-writes + event emissions). No caller reimplements queue/scrub/flock/event-emit inline.
- API (each function takes `state: StateHandle` first arg):
 - `propose_gate(state, domain, category, gate, evidence?) -> dict` — appends to improvement-queue.jsonl + emits `gate_proposed` event
 - `propose_apply(state, patch_id) -> dict` — returns CLI command + one-shot token, no mutation; emits `apply_proposed` event
 - `report_outcome(state, recommendation_id, verdict, reason) -> str` — emits `outcome_reported` event (event_id returned)
 - `report_agent_event(state, ...) -> str` — emits `agent_dispatch_*` event with bounded telemetry
 - `mark_patch_status(state, patch_id, status: 'deferred'|'rejected') -> dict` — updates patch bundle status + emits `patch_<status>` event
- All functions emit events via event_writer (KTD-13) for full observability
- All inputs scrubbed via scrub_secrets + bounded() before write
- All writes use fcntl.flock on appropriate lock-file

- Tests verify each function: alc_query returns expected shape + read-only enforcement; alc_propose emits expected events + queue-row + handles concurrent calls via flock
- MCP handlers in U17 become 3-line wrappers (parse args, call alc_query.X or alc_propose.X, return result). Dashboard's `build_data_blob` is alc_query calls. Dashboard's defer/reject buttons call alc_propose.mark_patch_status.

**Patterns to follow:** KTD-15 named-catalog (each function = documented capability in `references/{query-catalog,propose-catalog}.md` — auto-generated per KTD-20 with caller cross-reference)

**Test scenarios:**
- Each query function returns expected shape on fixture data
- Read-only mode enforced (write attempt raises OperationalError)
- `get_apply_log(since='24h')` filters correctly by timestamp
- `get_event_dag(session_id)` returns hierarchical structure with correct parent-child links
- MCP handler test (U17) uses alc_query mocks — verifies no SQL in MCP handler itself
- Dashboard test (U10) uses alc_query mocks — verifies no SQL in dashboard server itself

**Verification:** `python3 -m unittest tests.test_alc_query -v` passes; smoke: invoke MCP `get_recommendations` and dashboard `/data.json` against same state, verify identical recommendations data.

---

### U10. Read-only dashboard (`skills/alc-dashboard/`)

**Goal:** Single HTML page renders all artifacts (recommendations, patches, anomalies, patterns, correlations, apply log, gates, insights, suggestions). NO Apply/Defer/Reject buttons that mutate files. Routes apply to terminal CLI.

**Requirements:** R13 (read-only), R15 (dashboard shows only context-safe data)

**Dependencies:** U6, U7, U8, U9

**Files:**
- Create: `skills/alc-dashboard/SKILL.md`
- Create: `skills/alc-dashboard/server.py` (stdlib http.server, GET only for mutation routes)
- Create: `skills/alc-dashboard/templates/dashboard.html`
- Create: `skills/alc-dashboard/static/app.js`
- Create: `skills/alc-dashboard/static/style.css`
- Create: `skills/alc-dashboard/static/alpine.min.js` (vendored, not CDN)
- Create: `tests/test_dashboard_readonly.py`
- Create: `scripts/render_unified_report.py` (orchestrator)

**Approach:**
- Server endpoints: `GET /`, `GET /data.json`, `GET /static/<file>`. NO `POST /apply`, NO `POST /defer`, NO `POST /reject`.
- Apply-action UX: each patch bundle renders with a "Run in terminal:" code block showing the exact `bin/alc_apply --patch <id> --write` command. User copies, runs in terminal, refreshes dashboard.
- Defer/reject UX: each bundle has a "Mark as:" line with code blocks for `bin/alc_apply --mark-deferred <id>` / `bin/alc_apply --mark-rejected <id>` (these are state-only CLI ops, no file mutation outside `<state>/`).
- Server binds 127.0.0.1, free port via `socket` (no hard-coded 8765); `HTTPServer.allow_reuse_address = True`; subprocess output to `DEVNULL` for tests.
- Alpine.js vendored locally (~50KB) — no CDN dep, works offline (R15: no external network calls).
- `scripts/render_unified_report.py` orchestrator chains: distill → synthesize → analyst → recommender → render. Default: starts server + opens browser to `http://127.0.0.1:<port>/`. NO `file://` open path.
- Dashboard renders 7 sections: Recommendations, Pending patches (with run-command), Anomalies, Patterns, Correlations, Apply log, Gates & insights. Plus NEW: Suggestions (workflow chains, copy-to-clipboard variants — separate from patches, R10).
- Empty-state design for each section (since real data only appears after Phase D wires the eval loop)
- AI-slop avoidance: NOT GitHub dark theme verbatim. Use a distinct color palette tied to ALC's domain semantics (score = luminance, recency = saturation, risk = hue).
- Accessibility: viewport meta tag, ARIA on tabs (role=tablist/tab, aria-selected, aria-controls), keyboard nav (arrow keys cycle tabs), gray button color contrast ≥ 4.5:1.

**Patterns to follow:** S5 (single-template-with-embedded-data pattern); Tom's design preferences (distinctive aesthetic, plain-language framing)

**Test scenarios:**
- Server `do_POST` returns 405 Method Not Allowed for any path (read-only invariant)
- `GET /` renders HTML with embedded data blob
- `GET /static/app.js` returns Alpine.js + custom JS (no CDN reference in HTML)
- HTML contains markers: recommendations, patches, anomalies, patterns, correlations, apply log, gates, suggestions
- Patch render contains exact CLI command (`bin/alc_apply --patch <id> --write`) as code block
- Empty `recommendations.json` → "No recommendations" empty-state shown, not blank section
- Server picks free port when 8765 occupied
- `HTMLPasses validator: viewport meta present, ARIA on tabs, button contrast ≥ 4.5:1`
- `scripts/render_unified_report.py --open` opens `http://127.0.0.1:<port>/`, NOT `file://`

**Verification:** `python3 -m unittest tests.test_dashboard_readonly -v` passes; manual: run full orchestrator, browse to dashboard, attempt POST → 405; copy run-command, execute in terminal, verify file changes happen via CLI (U11) only.

---

### U11. `bin/alc_apply` CLI — Hermes-DSL executor with full preflight + event emission

**Goal:** Single CLI that parses Hermes-DSL ops + dispatches per target_type + enforces preflight + **emits patch_applied/patch_reverted events via event_writer**. The ONE place file mutation happens for ALC.

**Interface-first contract (arch-pass-5 F4):** Step 1 of U11 publishes a contract module `bin/alc_apply_contracts.py` with: `validate_agent_frontmatter(content) -> list[str]`, `validate_skill_frontmatter(content) -> list[str]`, `DSL_TARGETS: dict[str, TargetSpec]`, `ApplyResult` + `RevertResult` dataclasses, `ApplyError` + `RevertError` exceptions, ABC `Executor` med abstract `apply(op)` + `revert(patch_id)`. Once `bin/alc_apply_contracts.py` is committed, U12 (`alc_invoke`) and U17 (MCP extensions) can be dispatched as parallel subagents — both designing against the contract. Final integration when all three (U11 implementation + U12 + U17) land.

**Requirements:** R3 (no arbitrary write), R4 (concurrency-safe), R10 (no copy_to_clipboard), R13 (CLI not dashboard), R14 (flock + safe JSONL), R17 (target_type dispatch), R18 (agent-validator), R21+R22 (apply ops become events for self-introspection)

**Dependencies:** U5.5 (event_writer), U6, U7, U9

**Files:**
- Create: `bin/alc_apply`, `bin/alc_apply.py`
- Create: `bin/alc_apply_dispatch.py` (the per-target_type validators + executors)
- Create: `tests/test_alc_apply_concurrency.py`
- Create: `tests/test_alc_apply_paths.py`
- Create: `tests/test_alc_apply_agent_validator.py`
- Create: `tests/test_alc_apply_skill_validator.py`

**Approach:**
- CLI usage: `bin/alc_apply --patch <id> --write` (apply), `--patch <id> --revert` (revert), `--mark-deferred <id>` / `--mark-rejected <id>` (state-only), `--list-pending`
- Dispatch table per `target_type` arch-#2 from pass-1 — validate_common + per-type addenda):
 - skill: per-type rules: name prefix, frontmatter shape. allowed_roots = `["skills/", "~/.hermes/skills/"]`, max_size = 100k
 - agent: per-type rules: full agent-creator quality bar (see below). allowed_roots = `["agents/", "<state>/alc-agents/{dev,test,evals}/", "<personal>/alc-agents/"]`, max_size = 30k
 - command: per-type rules: frontmatter shape, exec-block. allowed_roots = `["commands/"]`, max_size = 10k
 - hook: per-type rules: executable bit, shebang. allowed_roots = `["hooks/"]`, max_size = 10k
- Preflight (in order, fail-fast):
 1. `target_type` in dispatch table
 2. `Path(target).resolve()` is under one of `allowed_roots`
 3. Target file size + content ≤ `max_size`
 4. `expected_target_sha256` matches current target hash (optimistic concurrency)
 5. `validate_<target_type>_frontmatter` on new content passes
 6. Acquire `fcntl.flock` on `<state>/.apply.lock` (blocking, with timeout 5s)
 7. Re-read target, re-check hash, scrub secrets with `bin/scrub_secrets`
 8. **: Emit `patch_applied` event via event_writer** (telemetry: duration_ms so far, payload: patch_id, target, original_sha256, original_bytes_b64 (scrubbed), revert_op)
 9. Atomic write target (temp + rename)
 10. Release flock
- Revert: query events.sqlite for `patch_applied` event with matching patch_id → execute `revert_op` from event payload → emit `patch_reverted` event (with parent_event_id linking back to original apply)
- `--list-pending` reads `<state>/patches/`, filters by status field (defer / reject reads patch bundle JSON, updates `status` field via atomic write)
- `--mark-deferred` / `--mark-rejected` also emit events (`patch_deferred`, `patch_rejected`) for full state-change visibility
- Idempotency: query events.sqlite for unreverted `patch_applied` event with matching patch_id → if exists, refuse with 409-equivalent error code 2
- **No separate apply-log.jsonl file** — `bin/alc_query.py:get_apply_log(state, since=)` returns SQL view: `SELECT * FROM events WHERE event IN ('patch_applied','patch_reverted','patch_deferred','patch_rejected') ORDER BY ts DESC`. Dashboard "Apply log" tab calls this query. Backward-compat: shim function returns rows in legacy apply-log shape for tooling that expects it.

**Agent-validator implementation (R18 — matches `~/.claude/plugins/cache/claude-plugins-official/plugin-dev/unknown/agents/agent-creator.md` quality bar):**
- `name`: matches `^[a-z][a-z0-9-]{2,49}$`, no contains `helper`/`assistant`/`agent-` prefix
- `description`: starts with literal "Use this agent when", contains 2-4 occurrences of `<example>...</example>`
- body word count: 500-3000 (split on whitespace, exclude code blocks)
- body sections present: "Role" + "Responsibilities" + "Process" + "Output" (case-insensitive heading match)
- `color`: in `{blue, cyan, green, yellow, red, magenta}`
- `model`: in `{inherit, sonnet, haiku, opus}` (or absent)
- `tools`: optional list of strings (no validation of tool names — assumed runtime-checked)

**Patterns to follow:** S1 (Hermes _validate_frontmatter), S6 (scrub_secrets integration), S12 (flock pattern from alc_mcp/server.py:_append_jsonl_locked)

**Test scenarios:**
- **Concurrency (R4, R14, AD#4):**
 - Two concurrent `alc_apply` invocations on same patch_id → second fails with 409, first succeeds
 - Mid-write SIGKILL on apply → apply-log has no partial line (flock + atomic write)
 - Pre-corrupted apply-log line → `--list-pending` skips it with warning, doesn't crash
 - 1000-line apply-log with one corrupt line at position 500 → dashboard renders all valid entries
- **Path traversal (R3, SE#2):**
 - `patch_id = "../../../etc/passwd-fake"` → preflight fails: target outside allowed_roots
 - Patch with `target = "/etc/hosts"` → preflight fails: target outside allowed_roots
 - Patch with symlink in target → preflight fails (no follow-symlinks)
- **Arbitrary write (R3, SE#3):**
 - Patch with `apply_params.file = "~/.ssh/authorized_keys"` → preflight fails
 - Patch with target under allowed_roots but escape via `..` → preflight fails (resolve check)
- **Agent-validator (R18):**
 - Agent with `name = "helper"` → validator rejects ("avoid generic")
 - Agent with description not starting with "Use this agent when" → rejected
 - Agent with 1 `<example>` block → rejected (min 2)
 - Agent with 5 `<example>` blocks → rejected (max 4)
 - Agent with 400-word body → rejected (min 500)
 - Agent with 3500-word body → rejected (max 3000)
 - Agent missing Role section → rejected
 - Agent with `color = "purple"` → rejected (not in semantic set)
 - Agent with all valid fields → accepted, written to allowed_root
- **Secret scrubbing (R3, SE#4):**
 - Patch targeting `agents/claude.yaml` containing `sk-ant-...` → original_bytes_b64 in apply-log has `<REDACTED>` instead of the secret
- **Hermes-DSL roundtrip:**
 - Apply patch → file changed → revert patch → file restored to original bytes
 - Apply patch → check apply-log → revert by `patch_id` → status flips
- **Idempotency:**
 - Apply patch twice → first succeeds, second exits with code 2 (already applied)
- **copy_to_clipboard (R10):**
 - Patch with `apply_strategy = "copy_to_clipboard"` → executor rejects: not a Hermes-DSL op, must be in suggestions.json

**Verification:** `python3 -m unittest tests.test_alc_apply_*` passes; manual: apply a real (small) patch from U9 output, verify file change + revert.

---

### U12. `bin/alc_invoke` — Agent archive dispatcher; spawn-events emitted

**Goal:** Spawn agent from archive (`<state>/alc-agents/{dev,test,evals}/<name>.md`) via Claude Code Agent tool. **Wraps each spawn with `subagent_invoke_start` + `subagent_invoke_end` events via event_writer** so arkiv-agent-aktivitet er synlig for analyst.

**Requirements:** R19, R21+R22 (spawn-events for self-introspection)

**Dependencies:** U5.5 (event_writer), U7, U11 (agent-validator reused)

**Files:**
- Create: `bin/alc_invoke`, `bin/alc_invoke.py`
- Create: `tests/test_alc_invoke.py`

**Approach:**
- CLI usage: `bin/alc_invoke --agent <archive-relative-path> --task <prompt> [--output <path>] [--model <override>]`
- Reads agent file, parses frontmatter via shared agent-validator (R18, U11)
- **Pre-spawn:** emit `subagent_invoke_start` event via event_writer with `actor.kind=arkiv_agent`, `actor.name=<agent-name>`, `actor.model=<resolved-model>`, payload contains agent_path + task_prompt_hash (NOT the task text — boundary). Capture returned event_id.
- Dispatches via Claude Code Agent tool when running inside Claude Code; via Codex subagent when running inside Codex; via direct subprocess execution (with a synthetic system_prompt header) as a fallback for plain CLI use
- Runtime detection: `$CLAUDE_PLUGIN_ROOT` set → Claude; `$CODEX_PLUGIN_ROOT` (or equivalent from G0.5.2) set → Codex; otherwise fallback
- **Post-spawn:** emit `subagent_invoke_end` event with `parent_event_id=<start-event-id>`, telemetry={duration_ms, tokens_in, tokens_out, cost_usd, cache_*} (extracted from runtime result), payload contains outcome
- Returns structured result: `{agent, task, output, duration_s, model_used, cost?, event_ids: [start, end]}`
- Archive cleanup policy: dev/ agents older than 30 days deleted on next `alc_invoke` run (using lifecycle field from U6); cleanup-decisions can be data-driven post-implementation via events.sqlite query (which agents are actually invoked, by what frequency)

**Patterns to follow:** S13 (runtime detection from alc_mcp), S2 (agent-creator system_prompt spec)

**Test scenarios:**
- Invoke valid agent from dev/ → returns structured result with non-empty output
- Invoke missing agent → exits with code 1, message "agent not found at <path>"
- Invoke agent with invalid frontmatter → validator rejects, exits with code 1
- Invoke with `--model haiku` overrides agent's frontmatter model
- Old (>30 days) dev/ agents auto-deleted on next invoke
- Test/ and evals/ agents NOT subject to auto-cleanup
- Personal archive (`<personal>/alc-agents/`) accessible from any repo

**Verification:** `python3 -m unittest tests.test_alc_invoke -v` passes; manual: create test agent, invoke against fixture prompt, verify structured output.

---

### U13. `bin/alc_eval` — Eval-loop scaffold (closes ROOT 6); verdicts as events

**Goal:** Periodic eval driver. Spawns `evals/rec-quality-judge` agent against last N recommendations. **Emits `eval_verdict` events via event_writer** — eval-loop is itself observable in the unified stream. Judge agents call `bin/exec_sandbox --scope eval` (U13.5) to actually apply patch in worktree + run relevant tests, so verdicts are evidence-based (not only LLM-opinion).

**Requirements:** R8 (feedback loop in code), R20 (eval-loop closes compounder), R21+R22 (verdikter blir events), R26 (judge uses exec_sandbox for evidence)

**Dependencies:** U5.5 (event_writer), U7, U9, U12, U13.5 (exec_sandbox)

**Files:**
- Create: `bin/alc_eval`, `bin/alc_eval.py`
- Create: `tests/test_alc_eval.py`
- Create: `<state>/alc-agents/evals/rec-quality-judge.md` (initial seeded agent — passes agent-validator)

**Approach:**
- CLI usage: `bin/alc_eval --window 7d [--limit 20] [--judge evals/rec-quality-judge]`
- Reads recommendations from last N days
- For each recommendation:
 - Invokes judge agent via `bin/alc_invoke` (which itself emits `subagent_invoke_*` events per U12)
 - **Emits `eval_verdict` event via event_writer** with `actor.kind=eval_judge`, `actor.name=rec-quality-judge`, `correlation_chain` linking to evaluated recommendation (role=evaluated_rec, id=rec_id), payload contains verdict + judge_reason
- The seeded `rec-quality-judge.md` agent has the agent-creator quality shape (validated at creation by U11): "Use this agent when ... grading agent-learning recommendations ..." with 2-4 examples, Role/Responsibilities/Process/Output sections, ~800 words.
- **No separate outcomes.json file** — outcomes are derived view: `bin/alc_query.py:get_outcomes(state, since=)` returns SQL view: `SELECT recommendation_id, verdict, judge_reason, ts FROM events WHERE event='eval_verdict' AND ts >= ?`
- Next `analyst_score` run joins events.sqlite for outcome-weight per kind:
 ```sql
 SELECT json_extract(payload_json, '$.recommendation_kind') AS kind,
 SUM(CASE WHEN json_extract(payload_json, '$.verdict')='approve' THEN 1 ELSE 0 END) AS n_pos,
 SUM(CASE WHEN json_extract(payload_json, '$.verdict')='reject' THEN 1 ELSE 0 END) AS n_neg,
 COUNT(*) AS total
 FROM events WHERE event='eval_verdict' GROUP BY kind
 ```

**Patterns to follow:** S7 (output-shape conventions from distill_learning)

**Test scenarios:**
- Eval against synthetic recommendations.json (3 recs) writes outcomes.json with 3 entries
- Each entry has `verdict in {approve, reject, modify}`
- `analyst_score` next run reads outcomes.json and weights down kind with 2/3 reject
- Re-running `analyst_score` without outcomes.json change produces identical recommendations.json (deterministic)
- Eval-loop with `--limit 0` → no-op, outcomes.json unchanged
- Missing judge agent → exits with code 1, instructive error
- Judge agent returning malformed JSON → counted as `modify` verdict with warning, doesn't crash loop

**Verification:** `python3 -m unittest tests.test_alc_eval -v` passes; smoke: run analyst → recommend → eval → re-analyst, observe score change for repeated kinds.

---

### U13.5. `bin/exec_sandbox` — tiered exec primitive for evidence-based validation

**Goal:** A single CLI + Python module that runs commands in bounded sandboxes (3 tiers: read / worktree / eval), emits events for full observability, and powers the eval-loop's evidence collection + recommender's pre-validation + arkiv-agent toolkit + operator dev-exploration.

**Requirements:** R26 (exec sandbox primitive), KTD-19 (tiered scopes), KTD-13 (every exec emits event)

**Dependencies:** U5.5 (event_writer for exec-event emission), U7 (StateHandle for worktree path resolution)

**Files:**
- Create: `bin/exec_sandbox`, `bin/exec_sandbox.py`
- Create: `bin/exec_sandbox_profiles.py` (declarative SCOPES dict — single source of truth for tier definitions)
- Create: `tests/test_exec_sandbox_read.py` (tier 1 enforcement)
- Create: `tests/test_exec_sandbox_worktree.py` (tier 2: spawn worktree + apply + run + cleanup)
- Create: `tests/test_exec_sandbox_eval.py` (tier 3: spawn worktree + alc_invoke subagent)
- Create: `tests/test_exec_sandbox_security.py` (boundary enforcement: no network, no write outside scope, secrets scrubbed in events)
- Create: `skills/alc-core/references/sandbox-tiers.md` (operator + agent reference for scope choice)

**Approach:**

**Tier 1 — `read` scope** (zero-mutation default):
- Allowlist commands: `git log`, `git show`, `git diff`, `git blame`, `ls`, `find`, `cat`, `head`, `tail`, `wc`, `grep`, `stat`, `python -m unittest`, `python3 -m unittest`, `pytest`, `diff`
- No write (chdir to repo root, but `umask 0444` applied to spawned dir)
- No network (env strip: `unset HTTP_PROXY HTTPS_PROXY; setenv NO_NETWORK=1` + best-effort iptables-rule when running as root, otherwise documented limitation)
- Default timeout 30s, max 120s

**Tier 2 — `worktree` scope** (mutation in throwaway worktree):
- Spawn fresh `git worktree add <tmp> <base-ref>` in `<state>/sandbox-worktrees/<exec-id>/`
- Command runs `cd <worktree> && <cmd>` — mutation contained
- After exec (success or timeout): `git worktree remove --force <tmp>`
- No allowlist (any command allowed in worktree — it's throwaway)
- No network (same env strip as tier 1)
- Default timeout 60s, max 300s

**Tier 3 — `eval` scope** (worktree + spawn-permitted):
- Same as worktree, PLUS allowed to invoke `bin/alc_invoke` for sub-spawn
- Used by `rec-quality-judge` arkiv-agent for full evidence collection
- Default timeout 300s, max 900s

**Recursion guard (W1):**
- Recursion depth tracked via explicit `--depth N` CLI flag (NOT env var — survives env strip when called from tier 1/2 with stripped env)
- max-depth check at exec_sandbox.py main(): refuse if `--depth >= 2`
- Tier-3 exec that spawns sub-exec via alc_invoke MUST pass `--depth $(CURRENT_DEPTH + 1)`
- alc_invoke accepts an `--alc-sandbox-depth N` CLI flag from its caller and forwards it to any nested `bin/exec_sandbox` invocation via `--depth N+1`. No env-var fallback — keeping a single mechanism (explicit CLI flag) means recursion is enforceable even when env is stripped at sandbox entry (KTD-19).

**Boot-time crash-recovery (A2):**
- On every exec_sandbox.py invocation: scan `<state>/sandbox-worktrees/` for stale dirs
- Stale = directory exists but no matching events.sqlite row with `status='running'` for that exec_id
- Cleanup: `git worktree remove --force <stale-dir>` + emit `exec_sandbox_recovered` event (so analyst can see crash-rate)
- Idempotent: re-running scan with no stale dirs is a no-op

**Event emission (KTD-13) — every exec writes:**
```
event: exec_sandbox_run
actor: {kind: operator|judge|recommender|arkiv_agent, name: <caller>}
payload: {scope, command (scrubbed), exit_code, duration_ms, worktree_dir? (if tier 2/3)}
telemetry: {stdout_bytes, stderr_bytes, max_rss_kb?}
correlation_chain: [..., {role: triggered_by, id: <parent-event-id>}]
```

stdout/stderr capped at 100KB per exec, scrubbed for secrets before event emission. Full output written to `<state>/sandbox-runs/<exec-id>/{stdout,stderr,exit_code}` for the caller to read (lifecycle: 7-day retention per data-contracts).

**CLI usage:**
```bash
bin/exec_sandbox --scope read --cmd "python3 -m unittest fixtures.tests.test_distill_learning" --repo $PWD --timeout 60
bin/exec_sandbox --scope worktree --base-ref alc-plugin-v2 --cmd "patch -p1 <patches/p-001.diff && python3 -m unittest" --repo $PWD --timeout 120
bin/exec_sandbox --scope eval --base-ref alc-plugin-v2 --cmd "bin/alc_invoke --agent evals/rec-quality-judge --task patches/p-001.json" --repo $PWD
```

**Python API:**
```python
from exec_sandbox import run, ExecResult, ExecScope

result: ExecResult = run(
    scope=ExecScope.WORKTREE,
    command="...",
    repo=repo,
    base_ref="alc-plugin-v2",
    timeout_s=120,
    actor={"kind": "judge", "name": "rec-quality-judge"},
)
# result.exit_code, result.stdout_path, result.stderr_path, result.duration_ms, result.event_id
```

**Patterns to follow:** S12 (fcntl.flock for exec-id allocation), S15 (non-blocking subprocess pattern from auto_distill_session), Hermes-DSL revert pattern for cleanup-on-failure

**Test scenarios:**

*Tier 1 (read):*
- Allowed command `ls -la` → exits 0, stdout captured, event emitted
- Non-allowlisted command `rm -rf .` → exits with code 3 (forbidden), no execution
- Command exceeding timeout → killed, exit code 124, event marks `timeout: true`
- Write attempt (`touch /tmp/x`) → blocked by umask + chdir constraints
- Network call (`curl example.com`) → blocked by env strip (best-effort)

*Tier 2 (worktree):*
- `--scope worktree --cmd 'touch x.tmp && ls x.tmp'` → writes to worktree, success, worktree cleaned up
- Worktree path is under `<state>/sandbox-worktrees/<exec-id>/` (not in repo)
- After exec: `git worktree list` shows worktree removed
- SIGKILL mid-exec → worktree still cleaned up via `try/finally` + signal handler
- Two concurrent execs → both get fresh worktrees, no collision

*Tier 3 (eval):*
- `--scope eval --cmd 'bin/alc_invoke --agent evals/judge ...'` → subagent dispatched, event chain links exec_sandbox_run → subagent_invoke_start (parent_event_id)
- Tier 3 command CANNOT spawn another tier 3 (recursion guard via explicit `--depth` CLI flag forwarded through alc_invoke; max-depth refuse at `--depth >= 2`)

*Event emission:*
- Every exec call appends one `exec_sandbox_run` event to events.jsonl
- Event payload's `command` field is secret-scrubbed (test: command with `--token sk-ant-XXXX` → event shows `--token <REDACTED>`)
- stdout >100KB → truncated in event payload, full file at `<state>/sandbox-runs/<exec-id>/stdout`

*Security boundaries:*
- Tier 1 command with path traversal `cat ../../etc/passwd` → blocked (chdir resolves; canonical path check rejects parent escapes)
- Tier 2 exec attempting write to `~/` outside worktree → command runs but write fails (umask + chdir)
- Recursion limit: tier 3 → tier 3 via alc_invoke chain → rejected at depth 2

**Verification:** `python3 -m unittest tests.test_exec_sandbox_* -v` passes; manual: run all three tiers with sample commands, inspect events.jsonl for exec_sandbox_run rows + sandbox-runs/<id>/ for captured stdout.

---

### U14. `agents/alc-reviewer.md` — single committed persona

**Goal:** One persona with distinct pre-apply role. Drops alc-analyst and alc-recommender personas (pass-through).

**Requirements:** R9 (1 persona not 3)

**Dependencies:** U3

**Files:**
- Create: `agents/alc-reviewer.md`
- Modify: `agents/claude.yaml` (add alc-reviewer mapping; remove analyst/recommender entries if any from V1)
- Modify: `agents/openai.yaml` (same)
- Create: `tests/test_agents.py`

**Approach:**
- `alc-reviewer.md` follows agent-creator quality bar (validated by U11's agent-validator)
- Role: pre-apply reviewer. Reads proposed Hermes-DSL op + current target file → returns `{verdict, reason, suggested_diff?}`
- Invokable via MCP (U17) or directly via `bin/alc_invoke --agent agents/alc-reviewer.md --task <patch-id>`
- yaml mappings reference the .md file relative to plugin root

**Patterns to follow:** S2 (agent-creator canonical example); existing claude.yaml + openai.yaml mappings

**Test scenarios:**
- `agents/alc-reviewer.md` passes agent-validator (U11)
- Frontmatter has all required fields (name, description w/ 2-4 examples, color in semantic set)
- Body has Role/Responsibilities/Process/Output sections
- yaml mappings reference the file by correct path
- yaml mappings do NOT reference alc-analyst or alc-recommender personas
- `bin/alc_invoke --agent agents/alc-reviewer.md --task <fixture-patch>` returns JSON verdict

**Verification:** `python3 -m unittest tests.test_agents -v` passes.

---

### U15. `commands/alc-report.md` — single command with flags

**Goal:** One slash command with flags replaces V1's four commands.

**Requirements:** R9 (1 command not 4)

**Dependencies:** U10 (orchestrator exists)

**Files:**
- Create: `commands/alc-report.md`
- Create: `tests/test_commands.py`

**Approach:**
- Flags: `--analyst-only`, `--recommend-only`, `--apply <id>`, `--eval`, `--open` (default), `--no-open`
- Maps to `scripts/render_unified_report.py` with flags
- No /alc-analyze, /alc-recommend, /alc-apply commands (all subsumed)
- Command body uses `${ALC_PLUGIN_ROOT}` (set by wrapper, per KTD-10), not `${CLAUDE_PLUGIN_ROOT}` directly

**Patterns to follow:** Claude commands in `~/.claude/commands/`; flag conventions from `bin/extract_sessions` (--days, --max-sessions)

**Test scenarios:**
- Command parses with frontmatter (name, description)
- Command body executes a single bash block
- Bash block uses `${ALC_PLUGIN_ROOT}` not `${CLAUDE_PLUGIN_ROOT}`
- All flags from `render_unified_report.py --help` are referenced in description
- No commands/alc-{analyze,recommend,apply}.md exist

**Verification:** `python3 -m unittest tests.test_commands -v` passes; manual: invoke `/alc-report --analyst-only` and `/alc-report --eval` in a session, verify both work.

---

### U16. Hooks (python-direct, no bash heredoc)

**Goal:** SessionStart loads gates + skill context; Stop runs auto_distill + dashboard refresh. Hook handlers are python files, not bash wrapping python.

**Requirements:** (architectural cleanup per ROOT 13 AR#9)

**Dependencies:** U4 (alc-core exists), U10 (dashboard exists)

**Files:**
- Create: `hooks/hooks.json`
- Create: `hooks/session-start` (bash, simple file-cat operation — bash justified)
- Create: `hooks/refresh_dashboard.py` (python direct, NOT bash wrapping python)
- Create: `tests/test_hooks.py`

**Approach:**
- `hooks.json` declares SessionStart (matcher `startup|clear|compact`) + Stop (matcher `.*`) hooks
- `session-start` is a 5-line bash script that `cat`s latest gates + skill context — bash is the right tool for file concatenation
- `refresh_dashboard.py` is invoked directly by Stop hook; imports `skills/alc-dashboard/server.py:build_data_blob` and writes refreshed `data.json` + `dashboard.html`
- Uses `${ALC_PLUGIN_ROOT}` (KTD-10); wrapper script in plugin root provides this for both Claude + Codex
- All hook handlers respect telemetry boundaries (R15: no raw prompts, no transcript chunks logged)

**Patterns to follow:** S3 (superpowers hooks.json shape), S15 (non-blocking fork from auto_distill_session)

**Test scenarios:**
- `hooks.json` parses as valid JSON
- `session-start` is executable (chmod +x)
- `refresh_dashboard.py` is executable + python shebang
- `refresh_dashboard.py` runs against a synthetic state dir, writes valid data.json + dashboard.html
- `hooks.json` references `${ALC_PLUGIN_ROOT}` correctly (NOT bare `${CLAUDE_PLUGIN_ROOT}`)
- SessionStart on empty state dir doesn't crash; produces minimal output

**Verification:** `python3 -m unittest tests.test_hooks -v` passes; manual: trigger Stop hook in a Claude session, verify dashboard data.json updates.

---

### U17. MCP extensions + capability catalog (alc_mcp/server.py)

**Goal:** Add 4 new MCP tools, drop direct mutation, refactor handlers to thin wrappers over alc_query (U10.5). Publish an explicit MCP capability catalog (M1-M10) parallel to Q1-Q10/G1-G5/DSL_TARGETS — agents can discover what alc_mcp exposes without reading server.py.

**Requirements:** R3 (no MCP mutation), R16 (parity: every dashboard surface has MCP equivalent), KTD-15 (named-catalog mønster utvidet til MCP)

**Dependencies:** U7 (StateHandle), U10.5 (alc_query), U11 (alc_apply_contracts for `propose_apply` shape)

**Files:**
- Modify: `alc_mcp/server.py` (refactor handlers + register new tools + auto-emit MCP_TOOLS catalog)
- Create: `alc_mcp/catalog.py` (canonical MCP_TOOLS dict — single source of truth for tools)
- Create: `alc_mcp/tests/test_mcp_catalog.py` (test that registered tools match catalog exactly)
- Create: `alc_mcp/tests/test_recommender_tools.py` (new tools' handlers)
- Create: `skills/alc-core/references/mcp-catalog.md` (human-readable M1-M10 reference)
- Modify: `alc_mcp/README.md` (link to catalog ref)

**MCP capability catalog (M1-M10) — published in `alc_mcp/catalog.py`:**

| M-ID | Tool name | Kind | Backing impl | Mutation? |
|------|-----------|------|--------------|-----------|
| M1 | `get_gates` | read | `alc_query.get_gates(repo, scope?)` | none |
| M2 | `get_skill_context` | read | `alc_query.get_skill_context(repo)` | none |
| M3 | `get_recommendations` | read | `alc_query.get_recommendations(repo)` | none |
| M4 | `list_pending_patches` | read | `alc_query.get_pending_patches(repo)` | none |
| M5 | `get_dashboard_url` | read | `state_handle.dashboard_url(repo)` | none |
| M6 | `propose_apply` | propose | returns CLI command for `bin/alc_apply --patch <id> --write` + one-shot token | none (caller decides) |
| M7 | `propose_gate` | propose | appends to `improvement-queue.jsonl` (existing behavior) | queue-only |
| M8 | `report_outcome` | observe | event_writer.write_event(event='outcome_reported', actor.kind=mcp_caller) | events.jsonl only |
| M9 | `report_agent_event` | observe | event_writer.write_event(event='agent_dispatch_*', actor.kind=mcp_caller) | events.jsonl only |
| M10 | `exec_sandbox` | exec | `bin/exec_sandbox` (U13.5) — tiered: read/worktree/eval | bounded (worktree-only for tier 2/3) |

**Catalog schema (each MCP_TOOLS entry):**
```python
MCP_TOOLS: dict[str, MCPToolSpec] = {
    "get_gates": MCPToolSpec(
        id="M1",
        kind="read",
        summary="Return approved gates loaded for repo. Bounded list, no raw memory.",
        backing="alc_query.get_gates",
        parameters_schema={...},
        returns_schema={...},
        examples=[...],
        version=1,                  # W2 from pass-7: schema-evolution support
        min_compatible_version=1,   # agent can use this if its known version >= this
    ),
    # ... M2-M10
}
```

When a tool's signature/return-shape changes incompatibly, bump `version`. Agents call `list_capabilities()` and compare each tool's `version` to their own known version (caller-side responsibility). `min_compatible_version` lets the server signal "v2 callers can still use this, v1 callers cannot".

**Capability-discovery surface:**
- New built-in MCP tool `list_capabilities(repo) -> list[dict]` returns the M1-M10 catalog entries (without the handler functions, just metadata). Agents call this first to discover what alc_mcp can do.
- `alc_mcp/__init__.py` exports `MCP_TOOLS` so external code can import the catalog directly.
- Test `test_mcp_catalog.py` asserts: every registered tool in server.py has matching MCP_TOOLS entry; every catalog entry has registered tool; M-IDs are unique and sequential.

**Approach (per KTD-13 + KTD-15):**
- Read-tools (M1-M5) → thin wrappers over `alc_query.<func>`. No SQL or file I/O directly in server.py.
- Propose-tools (M6-M7) → do NOT mutate target file. M6 returns CLI command; M7 queues for review (existing behavior preserved).
- Observe-tools (M8-M9) → emit via `event_writer.write_event` per KTD-13. Existing tools' behavior preserved semantically; internal implementation refactored.
- Importantly: NO `apply_patch` tool that mutates files in-process (V1 plan had this; agent-native audit AN#3 rejected it).
- All tool handlers ≤ 5 lines: parse args → call backing function → return result.

**Patterns to follow:** S13 (alc_mcp tool registrations), StateHandle (U7); tools-as-primitives per agent-native-audit; KTD-15 named-catalog (Q1-Q10 for analyst is reference precedent)

**Test scenarios:**
- `test_mcp_catalog`: every M1-M10 entry has matching server.py registration; no orphan tools either way
- `test_mcp_catalog`: catalog M-IDs are unique, sequential, and metadata fields complete (id, kind, summary, backing, parameters_schema, returns_schema, examples non-empty)
- `handle_list_capabilities(repo)` returns 9 entries with correct shape
- `handle_get_recommendations(repo)` returns list (empty if no recommendations.json); SQL/IO is in alc_query, not handler
- `handle_list_pending_patches(repo)` filters out applied/rejected patches via alc_query
- `handle_propose_apply(repo, patch_id)` returns CLI command string, does NOT modify any file, does NOT spawn subprocess
- `handle_get_dashboard_url(repo)` returns http:// when server running, file:// fallback otherwise
- `handle_report_outcome(repo, ...)` emits `event_writer.write_event(event='outcome_reported')` — verified via in-memory writer mock
- No `handle_apply_patch` function exists (R3 enforcement at code-grep level)
- All existing handler tests (`get_gates`, `report_outcome`, etc.) still pass — semantic preservation
- MCP catalog is importable as `from alc_mcp import MCP_TOOLS` from external code

**Verification:** `python3 -m unittest discover -s alc_mcp/tests -v` passes; manual: invoke `list_capabilities` from a Claude session via MCP, verify response matches M1-M10 catalog; invoke each tool, verify outputs.

**capability-map.md cross-reference (U19):** the M-IDs from this catalog are referenced in `skills/alc-core/references/capability-map.md` (R16) so every dashboard-rendered action is mappable to its MCP-tool-equivalent. Capability-map-test asserts every dashboard surface has at least one MCP M-tool partner.

---

### U18. Codex sync (`scripts/sync-to-codex-plugin.sh`) — pedagogically present, may no-op on G0.5.2 red

**Goal:** Cross-runtime manifest parity, IF G0.5.2 was green for Codex discovery.

**Requirements:** R7 (conditional)

**Dependencies:** U3 (manifests exist)

**Files:**
- Create (conditional): `scripts/sync-to-codex-plugin.sh`
- Modify: `tests/test_cross_runtime.py` (add parity-after-sync test)

**Approach:**
- IF G0.5.2 fully green: script mirrors `.claude-plugin/plugin.json` → `.codex-plugin/plugin.json`, stripping Claude-only fields (hooks)
- IF G0.5.2 green for AGENTS.md only: script verifies AGENTS.md content is up-to-date with CLAUDE.md (content-level parity test, not file-level)
- IF G0.5.2 red: skip this unit entirely; mark `.codex-plugin/` as "not supported, see RESULTS.md"

**Patterns to follow:** S4 (superpowers sync-to-codex-plugin.sh)

**Test scenarios (conditional on G0.5.2):**
- Script is executable
- Running script after editing `.claude-plugin/plugin.json` produces matching `.codex-plugin/plugin.json`
- Parity test passes after sync
- Codex-only fields (none currently expected) absent from Claude manifest

**Verification (conditional):** `python3 -m unittest tests.test_cross_runtime.TestSyncScript -v` passes; manual: invoke `/alc-report` in both Claude and Codex sessions, verify both work.

---

### U19. Validation phase: context-boundary tests + capability-map + e2e smoke

**Goal:** Final phase. Three NEW test surfaces ensure the durable-write features are safe + the agent-native parity holds + the pipeline actually produces real data.

**Requirements:** R15 (context boundary), R16 (capability parity), R2 (pipeline works on real data)

**Dependencies:** U1-U18

**Files:**
- Create: `tests/test_context_boundary.py`
- Create: `tests/test_capability_map.py`
- Create: `tests/test_e2e_pipeline_real_data.py`
- Create: `skills/alc-core/references/capability-map.md`
- Modify: `data-contracts.json` (audit for completeness)
- Decision document: `<state>/dashboard-migration-decision.md` (commits the ROOT 3 / FE#1 migration decision)

**Approach:**
- **Context-boundary tests (R15) — forenklet pga:** boundary håndheves nå pre-write i `bin/event_writer.py:_enforce_boundary` + samme funksjon kalt fra `bin/artifact_writer.py`. U19's test reduseres til ÉN test: `test_boundary_enforcement.py` som asserter at `_enforce_boundary` riktig avviser hver kategori (secret, abs-path, oversized-string, oversized-blob unntak for patch_*, raw-transcript). Plus ÉN regresjons-test: bygg et bevisst boundary-bryt-event, pass til write_event, asserter ValueError + ingenting skrevet til disk. Per-artifact post-hoc-scans droppet — enforcement-invariant gjør dem overflødige.
- **Capability-map tests (R16):** parse `skills/alc-core/references/capability-map.md` (a matrix: user-action × command × MCP tool × CLI). Assert: every dashboard-rendered action has at least 2 of (command, MCP tool, CLI). Every MCP tool has at least 1 of (command, CLI). Cross-reference with `alc_mcp/catalog.py:MCP_TOOLS` (U17): every M-ID in MCP catalog appears at least once in capability-map; every dashboard surface has at least one M-ID partner.
- **E2E pipeline test (R2):** runs the FULL pipeline on real data (not seeded). Asserts: `recommendations.json` is non-empty when corpus contains skill-mentions; anomalies are flagged when samples contain z>3 outlier; patches/ contains at least 1 bundle.
- **Dashboard migration decision (ROOT 3):** commit a decision document that records: which path (keep both / port-and-delete / coexist) was chosen, why, and how the existing `dashboard/`'s `muted-domains.json` behavior is preserved. This is a written decision, not code — but it's a mandatory phase exit criterion.

**Patterns to follow:** U6 test_data_contracts.py (artifact-scanning); S8 (muted-domains.json semantics preserved per R5)

**Test scenarios:**
- Context boundary: write a file containing `/home/tth/secrets.txt` to a state path → test fails
- Context boundary: write a file with line of 500 chars → test fails
- Context boundary: write a file with `sk-ant-api03-...` → test fails (regex catch)
- Capability map: parse map file, assert all dashboard actions have ≥2 invocation paths
- Capability map: missing entry → test fails with clear message
- E2E: run full pipeline against fixture corpus with known properties → assert recommendation count, anomaly count, patch count match expectations
- Dashboard migration decision document exists and contains: (a) decision (keep both / port / coexist), (b) muted-domains.json preservation plan, (c) timeline

**Verification:** all tests pass; baseline test count from U1 + new tests from U2-U18 are all green; full suite green.

---

### U20. `alc-cloudflare-sync` — optional cross-repo memory via D1 + Vectorize (post-MVP)

**Status:** post-MVP, opt-in per repo. **Scope-collapse safe**: hele sub-skillet dropps om G0.5.1 returnerer RED. W12 i wave-tabellen er ikke auto-dispatched fra LFG — operatør kjører separat etter Phase F merge.

**Goal:** Mirror lokal `events.sqlite` til Cloudflare D1 + bygg Vectorize-index over actor-bærende events for cross-repo / cross-maskin semantic memory. ALC's lokale identitet uendret — sync er additiv replikator, ingen runtime-avhengighet på CF.

**Requirements:** R27

**Dependencies:** U5.5 (events.sqlite må eksistere), U6 (data-contracts for events), U10.5 (`alc_query.py` som read-API). **IKKE** dep på U10/U13 — sync er sidekanal.

**Files:**
- Create: `skills/alc-cloudflare-sync/SKILL.md` (tredje sub-skill ved siden av alc-core + alc-dashboard)
- Create: `skills/alc-cloudflare-sync/references/architecture.md`, `setup.md`
- Create: `bin/alc_sync_cloudflare`, `bin/alc_sync_cloudflare.py` (CLI: `--push`, `--query`, `--init`, `--status`)
- Create: `bin/cloudflare_client.py` (thin wrapper over httpx; ingen `cloudflare`-SDK-dep)
- Create: `cloudflare/wrangler.jsonc` + `cloudflare/src/index.ts` (Worker som tar imot batches, embedder via Workers AI, skriver til D1 + Vectorize)
- Create: `cloudflare/migrations/0001_events_schema.sql` (D1-mirror av `EventV4.sqlite_ddl()`)
- Create: `tests/test_alc_sync_cloudflare.py` (mocked CF endpoints; ingen ekte nettverk)
- Modify: `.agent-learning.json` schema — legg til valgfri `cloudflare_sync: {enabled: bool, worker_url: str, api_token_env: str, vectorize_index: str, d1_database: str}`
- Modify: `bin/state_handle.py` — eksponer `cloudflare_sync_config` (None hvis ikke konfigurert)

**Approach:**

1. **Trust-boundary først, ikke siste:** sync-pipeline kan KUN sende events som har passert `_enforce_boundary` allerede (KTD-16). Worker-API'et avviser også `payload.raw_*` felter på input — defense-in-depth.
2. **Push-modell** (ikke pull):
   - `bin/alc_sync_cloudflare --push` leser `events.sqlite` siden cursor `<state>/.cloudflare-sync.cursor`, batcher 100 events, POST til Worker-endpoint.
   - Worker validerer schema (bruker `EventV4.jsonschema()`-generert skjema), embedder bounded summary-felt via Workers AI (`@cf/baai/bge-base-en-v1.5`), skriver til D1 + Vectorize.
   - **Fail-soft (KTD-17):** hvis Worker er nede / API-token utløpt → log warning + behold cursor, retry neste push. ALC fortsetter å fungere lokalt.
3. **Query-modell** (read-side):
   - `bin/alc_sync_cloudflare --query "stack trace X"` → embeddings-query → Worker → Vectorize semantic search → returnerer rangerte `event_id`s + bounded summary.
   - **Hybrid join** i `alc_query.py`: lokalt SQL-query + CF semantic-query, merge resultater. Lokalt vinner ved tie (lokalt er ground truth).
4. **Embedding-policy** (begrenset surface):
   - Embed kun: `event.summary` (bounded, scrubbed), `actor.name`, `tool_server`, `error_class`.
   - **IKKE** embed: payload-bodies, tool-inputs, tool-outputs — selv om scrubbed.
5. **Token-håndtering:**
   - CF API-token leses fra env-var navngitt i config (default `CLOUDFLARE_API_TOKEN`). Aldri persistert i `.agent-learning.json`.
   - Token-struktur: scoped til *kun* Workers AI + Vectorize + D1 for prosjekt-account. Ingen account-wide tokens.
6. **Cross-repo memory som førsteklasses use-case:**
   - Hver event tagged med `repo_id` (eksisterer allerede i `state_paths`).
   - Query kan ta `--scope all | repo:<id> | recent:7d`.
   - Vectorize-index har metadata-filter på `repo_id`, `actor_kind`, `ts_bucket`.
7. **Wrangler-config:**
   - `wrangler.jsonc`: `vectorize_indexes: [{binding: "EVENTS_INDEX", index_name: "alc-events"}]`, `d1_databases: [{binding: "DB", database_name: "alc-events"}]`, `ai: {binding: "AI"}`
   - Deploy: `cd cloudflare && wrangler deploy`. Operatør-drevet, ikke automatisk.

**Test scenarios:**

- **Disabled-default:** alle eksisterende tester passerer uendret med `cloudflare_sync.enabled=false`
- **Push happy path:** 100 events i sqlite → push → Worker mottar batch med riktig schema (mocked endpoint)
- **Trust-boundary:** forsøk å pushe event med raw `payload.tool_output` → klient avviser før HTTP-call
- **Failover:** Worker returnerer 503 → cursor uendret, neste push prøver samme batch på nytt; ingen events mistet
- **Token-rotering:** token i env-var endres mellom pushes → klient leser ny token uten restart
- **Cross-repo query:** query med `--scope all` returnerer hits fra ≥2 forskjellige `repo_id`-verdier
- **Schema-version:** D1-mirror schema_version=4; push av v3-row blokkeres (upgrade lokalt først)
- **Idempotens:** rerun samme batch → D1 INSERT...ON CONFLICT(event_id) DO NOTHING; Vectorize upsert; ingen duplicates

**Patterns to follow:**
- `skills/cloudflare/agents-sdk` (lokal mirror under `~/.claude/skills/`) for Worker-init og bindings
- Eksisterende `bin/auto_distill_session` for cursor-pattern
- `event_writer.write_events_batch` for batch-skrive-mønster lokalt (samme idempotency-shape)

**Verification:**
```
python3 -m unittest tests.test_alc_sync_cloudflare -v       # all green, mocked HTTP
bin/alc_sync_cloudflare --init --dry-run                     # genererer wrangler.jsonc, peker på unikt CF account
cd cloudflare && wrangler deploy --dry-run                   # validerer schema + bindings
bin/alc_sync_cloudflare --push --limit 10                    # send 10 events til faktisk Worker
bin/alc_sync_cloudflare --query "premise validation" --scope all   # returnerer hits fra D1+Vectorize
```

**Execution note:** Test-first. Hele unitet feiler graceful om CF ikke er tilgjengelig; integration-testene mocker HTTP — skriv testene før Worker-koden.

**Scope-collapse path:** G0.5.1 RED → drop U20. G0.5.2 RED → behold U20 men kjør kun fra Claude. G0.5.3 RED → drop U20 (ingen vits å speile dårlige data).

---

