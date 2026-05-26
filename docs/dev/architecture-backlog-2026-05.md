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

## Source

Full review: `/tmp/architecture-review-20260526T1318Z.html` (transient — rebuild via `/improve-codebase-architecture review` if needed).
