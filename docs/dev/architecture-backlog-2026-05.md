# Architecture deepening backlog — 2026-05-26

Surfaced by `/improve-codebase-architecture review` on 2026-05-26. Wave 1+2
candidates (#01, #02, #03, #04) are being implemented separately. **These
two are deliberately deferred until a concrete driver shows up.** They
should be resurrected by anyone running the next architecture review.

## #05 — Pipeline-protocol for the analyst quartet

**Files:** `bin/analyst_patterns.py`, `bin/analyst_anomalies.py`, `bin/analyst_correlations.py`, `bin/analyst_score.py`, would become `bin/analyst_pipeline.py`

**Deferred because:** Four analysts is below the pain threshold. The deletion test showed no concentrated complexity in the current quartet — each analyst is domain-specific and earns its keep on its own. The boilerplate-removal value at N=4 isn't worth the abstraction-overhead cost.

**Resurrect when ANY of:**
- A fifth analyst is on the horizon (boilerplate repeats once more)
- We need conditional analyst execution (skip-if, run-if-data-fresh-enough)
- We need shared progress reporting / shared error handling
- Subprocess startup cost becomes measurable in CI

**Estimated effort when triggered:** ~4h. Define `Analyst` protocol + `Pipeline` class, convert four analysts to strategies, update `render_unified_report` to call pipeline once instead of four subprocesses.

## #06 — Pipeline-protocol for `refresh_learning_state`

**Files:** `bin/refresh_learning_state.py` (645 lines), would become `bin/learning_pipeline.py` + thin CLI wrapper

**Deferred because:** Current orchestrator is intelligible top-to-bottom and works. The 15+ helper modules already encapsulate their step logic — the orchestrator is thin. Pipeline-protocol adds composability cost without a paying user.

**Resurrect when ANY of:**
- We need to skip / rerun individual steps via CLI flag
- Conditional branches appear (e.g., "skip distill if no new sessions")
- Parallel branches become valuable
- A second pipeline shape appears (e.g., a lightweight "incremental refresh" path)
- The main file passes 800 lines or main() passes 200 lines

**Estimated effort when triggered:** ~5h. `PipelineStep` protocol, `Pipeline` class with named steps + dependency graph + skip/only flags, convert refresh_learning_state to thin CLI wrapper.

## #07 — `events.jsonl` has two writers; replay truncates

**Files:** `bin/event_writer.py` (appends), `bin/replay_hook_events` (truncates via O_TRUNC), `bin/alc_bootstrap_pipeline` (calls replay each Stop)

**Surfaced by:** PR 5 (2026-05-27, commit `f6311a6`). The PR 5 design brief explicitly chose full-replay-each-Stop (Decision 3, Option I) over an incremental cursor on `hook-events.jsonl`. Implemented per brief; this entry records the latent correctness gap so the next architecture review doesn't re-derive it.

**The gap:** Two surfaces write to `<repo_state>/events.jsonl`:
1. `event_writer.write_event(..., repo=R)` — append-only, called from `bin/alc_eval`, `bin/alc_propose.py`, `bin/alc_invoke`, `bin/exec_sandbox`, `bin/sandbox_run_state.py`, `bin/alc_apply_dispatch.py`, `bin/ingest_new_transcripts`, `bin/event_emit`, `bin/correlate_events`.
2. `replay_hook_events --output events.jsonl` — O_TRUNC + rewrite from `hook-events.jsonl`.

PR 5 wired (2) onto every Stop hook via `bin/alc_bootstrap_pipeline`. If any (1) call lands between Stops, the next Stop's replay truncates `events.jsonl` and the (1)-sourced rows are lost. The indexer cursor wouldn't help — those rows never got indexed before the truncate.

**Not biting today because:** on this repo, the (1) callers are infrequent (alc_eval / alc_propose / sandbox runs are operator-triggered, not session-implicit). Live verification on 2026-05-27 showed 0 lost rows so far. The latent risk grows as ALC usage broadens (e.g., per-session sandbox runs, automated eval cycles).

**Resurrect when ANY of:**
- A regression appears where `event_writer`-sourced rows disappear from `events.sqlite` after a Stop.
- `bin/exec_sandbox` or `bin/alc_eval` starts running automatically in-session (turns (1) into a session-implicit writer).
- The user complains about Stop-hook latency (replay rewrites scale with `hook-events.jsonl` size; the 5 MB rotation caps it but isn't free).
- The "incremental refresh path" trigger from #06 fires for any other reason — the two refactors share a sequencing concern and may want to be done together.

**Estimated effort when triggered:** ~3h. Either (a) add an incremental cursor on `hook-events.jsonl` so replay appends rather than truncates (cleanest; matches PR 5 brief's "Decision 3 Option II"), or (b) split the two writer paths into separate JSONLs (`events.from_hooks.jsonl` + `events.from_writer.jsonl`) and have `index_events` read both — heavier change touching more callers.

## Source

Full review: `/tmp/architecture-review-20260526T1318Z.html` (transient — rebuild via `/improve-codebase-architecture review` if needed).

PR 5 wiring decision: `docs/dev/pr5-next-session.md` § "Decision 3 — Replay incremental or full each Stop?".
