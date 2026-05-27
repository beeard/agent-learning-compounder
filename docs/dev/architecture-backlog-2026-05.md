# Architecture deepening backlog — 2026-05-26

Surfaced by `/improve-codebase-architecture review` on 2026-05-26. Wave 1+2
candidates (#01, #02, #03, #04) are being implemented separately. **These
two are deliberately deferred until a concrete driver shows up.** They
should be resurrected by anyone running the next architecture review.

> 2026-05-27 note: Runtime Wiring is complete as the first step from
> `architecture-review-20260527-183248`:
> `bin/runtime_topology.py` now owns mode-specific runtime selection and hook
> command/config rendering for dev setup, release install, and drift checks; see
> `docs/dev/runtime-boundary.md` and
> `agent-learning-compounder/tests/test_runtime_topology.py`.
> State Scope is complete as the second step: `bin/state_handle.py` now owns
> project/user/background target selection, read-scope validation, user report
> paths, and event write-target classification for `event_writer`, `alc_query`,
> distillation, render, MCP, and project writer surfaces.
> Refresh Run is complete as the third step: `bin/refresh_run.py` now owns
> warm/full refresh profiles, incremental hook replay into project
> `events.jsonl`, event indexing, the top-level refresh lock, stage ordering,
> and structured result reporting while `bin/refresh_learning_state` remains
> the CLI adapter. Dashboard Read Model is complete as the fourth step:
> `bin/dashboard_read_model.py` now owns FastAPI, static-render, and stdlib
> dashboard read payload assembly. Proposal Lifecycle is complete as the fifth
> step: `bin/proposal_lifecycle.py` now owns proposal identity, lifecycle
> records, proposal event payloads, and read mirrors over queue, patch, and
> suggestion artifacts while `bin/alc_propose.py` remains the CLI/MCP adapter.

## #05 — Pipeline-protocol for the analyst quartet

**Files:** `bin/analyst_patterns.py`, `bin/analyst_anomalies.py`, `bin/analyst_correlations.py`, `bin/analyst_score.py`, would become `bin/analyst_pipeline.py`

**Deferred because:** Four analysts is below the pain threshold. The deletion test showed no concentrated complexity in the current quartet — each analyst is domain-specific and earns its keep on its own. The boilerplate-removal value at N=4 isn't worth the abstraction-overhead cost.

**Resurrect when ANY of:**
- A fifth analyst is on the horizon (boilerplate repeats once more)
- We need conditional analyst execution (skip-if, run-if-data-fresh-enough)
- We need shared progress reporting / shared error handling
- Subprocess startup cost becomes measurable in CI

**Estimated effort when triggered:** ~4h. Define `Analyst` protocol + `Pipeline` class, convert four analysts to strategies, update `render_unified_report` to call pipeline once instead of four subprocesses.

## #06 — Refresh Run module boundary for `refresh_learning_state`  ✅ addressed 2026-05-27

**Files:** `bin/refresh_run.py`, `bin/refresh_learning_state`, `bin/alc_bootstrap_pipeline`

**Status:** Addressed by Refresh Run. The public `refresh_learning_state`
command delegates to `refresh_run.run_full(...)`; bootstrap and Stop-hook warming
delegate to `refresh_run.run_warm(...)`. Stage algorithms remain unchanged, but
ordering, locking, event ingestion, indexing, and result reporting now have one
module boundary.

**Still deferred:** skip/rerun CLI flags and proposal lifecycle ranking.

**Verification:** `tests/test_refresh_run.py`, `tests/test_pr5_install_warm_loop.py`,
refresh retirement, queue dedup, domain-rule, bootstrap, runtime-topology, and
runtime-boundary tests.

## #07 — `events.jsonl` has two writers; replay truncates  ✅ addressed 2026-05-27

**Files:** `bin/event_writer.py` (appends), `bin/replay_hook_events` (truncates via O_TRUNC), `bin/alc_bootstrap_pipeline` (calls replay each Stop)

**Surfaced by:** PR 5 (2026-05-27, commit `f6311a6`). The PR 5 design brief explicitly chose full-replay-each-Stop (Decision 3, Option I) over an incremental cursor on `hook-events.jsonl`. Implemented per brief; this entry records the latent correctness gap so the next architecture review doesn't re-derive it.

**Original gap:** Two surfaces wrote to `<repo_state>/events.jsonl`:
1. `event_writer.write_event(..., repo=R)` — append-only, called from `bin/alc_eval`, `bin/alc_propose.py`, `bin/alc_invoke`, `bin/exec_sandbox`, `bin/sandbox_run_state.py`, `bin/alc_apply_dispatch.py`, `bin/ingest_new_transcripts`, `bin/event_emit`, `bin/correlate_events`.
2. `replay_hook_events --output events.jsonl` — O_TRUNC + rewrite from `hook-events.jsonl`.

PR 5 wired (2) onto every Stop hook via `bin/alc_bootstrap_pipeline`. If any (1) call lands between Stops, the next Stop's replay truncates `events.jsonl` and the (1)-sourced rows are lost. The indexer cursor wouldn't help — those rows never got indexed before the truncate.

**Status:** Addressed by Refresh Run. Production warm/full refresh no longer calls
`replay_hook_events` in the truncating `--output events.jsonl` mode. It appends
newly normalized hook rows behind `hook-events.jsonl.replay.cursor.json`, refuses
symlinked `events.jsonl`, skips malformed hook rows, and then indexes the
project-scoped `events.jsonl`.

**Manual compatibility:** `bin/replay_hook_events` remains as an operator tool;
the production warm path is `refresh_run.run_warm(...)`.

## #08 — Proposal Lifecycle module boundary  ✅ addressed 2026-05-27

**Files:** `bin/proposal_lifecycle.py`, `bin/alc_propose.py`,
`bin/alc_query.py`, `bin/recommender_render`, `bin/alc_eval`,
`alc_mcp/catalog.py`

**Status:** Addressed by Proposal Lifecycle. Proposal identity, lifecycle
record construction, status/event payload helpers, and normalized read mirrors
now live in `bin/proposal_lifecycle.py`. `alc_propose` delegates proposal event
payload construction while preserving public return shapes. `alc_query`
exposes proposal queue and lifecycle read mirrors, backed by MCP tools M19 and
M20. Recommender-rendered patches/suggestions and eval verdicts now carry
lifecycle correlation metadata when source recommendation identity is known.

**Still deferred:** analyst quartet pipeline protocol (#05), dashboard URL
server-marker hardening, and package distribution bundle work.

**Verification:** `tests/test_proposal_lifecycle.py`,
`tests/test_alc_propose.py`, `tests/test_alc_query.py`,
`tests/test_recommender_render.py`, `tests/test_alc_eval.py`, MCP catalog and
capability parity tests, plus dashboard read-model tests.

## Source

Full review: `/tmp/architecture-review-20260526T1318Z.html` (transient — rebuild via `/improve-codebase-architecture review` if needed).

PR 5 wiring decision: `docs/dev/pr5-next-session.md` § "Decision 3 — Replay incremental or full each Stop?".
