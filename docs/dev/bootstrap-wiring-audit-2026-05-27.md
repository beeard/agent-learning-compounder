# Bootstrap wiring audit — 2026-05-27

> Trace what install / `alc_init` / `init_learning_system` / `refresh_learning_state`
> actually run today vs what the learning loop needs to run on a fresh install,
> driven by Tom's note that the "init refresh" used to backfill everything and
> learn from it before handing control to the operator.

## Tooling boundary at a glance

| Layer | Script | Pipeline steps it runs |
|---|---|---|
| Install | `install.sh`, `bootstrap.sh`, `scripts/alc-install.mjs` | Copy skill tree → `--verify` (3 test suites) → call `init_learning_system` → call `install_runtime_hooks --dry-run` → call `alc_init` |
| Repo init | `bin/init_learning_system` | `build_repo_baseline` + `build_map` + write empty exports + write hook + refresh **manifests** |
| First-run profiler | `bin/alc_init` | `repo_profile.detect` + `ensure_mcp` + `smoke_mcp` + `repo_profile.doc_contract_rows` + 6 `alc_query` reads + render session-context |
| Hook wiring | `bin/install_runtime_hooks` | Manifest-only by default. `--apply` writes `.codex/hooks.json` / `.claude/settings.local.json` |
| Orchestrator | `bin/refresh_learning_state` (645 lines) | `build_baseline` + `build_map` + `extract_skill_usage` + `evaluate_skill_impact` + `evaluate_gate_effectiveness` + `propose_domain_rules` + queue dedup + write exports |
| Stop-hook | `bin/auto_distill_session` | `extract_sessions` + `distill_learning` over the last `--days 1`, `--max-sessions 20`, forked to background |

## 1. Current wiring — what install actually triggers

### `install.sh --bootstrap-repo <repo>` (the canonical first-run path)

1. `install_once` → `cp -a` the inner skill into `<repo>/.agents/skills/` and/or `<repo>/.claude/skills/`; sanitize tree.
2. If `--verify`: run `fixtures/tests`, `tests/`, `scripts/run_pressure_tests.py`.
3. `python3 .../init_learning_system.py --install-repo-integration --install-hooks --self-test`
   - Builds `baseline.json` (`build_repo_baseline`) and `skill-map.json` (`map_active_skills`) — these are repo scans, not corpus work.
   - Writes empty `latest-approved-gates.md` ("- none") and empty `latest-skill-context.md` (no usage data to render).
   - Writes hook wrapper + manifest under `<repo>/.agent-learning/repos/<repo-id>/hooks/`.
   - Writes refresh manifest under `automation/agent-learning-refresh.manifest.json` — declaration only, **no scheduler registration**.
   - Self-test confirms required files exist; does not run any pipeline.
4. `python3 .../install_runtime_hooks.py --runtime <r> --dry-run` (unless `--apply-runtime-hooks`).
5. `python3 .../alc_init --repo <repo>`:
   - Orchestrates first-run profiling through `bin/repo_profile.py`, ensures `mcp` python module is importable, runs initialize + tools/list against `alc_mcp/server.py`.
   - Calls six `alc_query.*` reads (all of which gracefully return `[]`/`{}` because `events.sqlite` doesn't exist yet).
   - Renders `latest-session-context.md` with the CE playbook and doc-contract hints.

### Other modes

- `install.sh --codex|--claude|--codex-home|--plugin|--target DIR` (user-global install): copy tree, optional `--verify`, **no bootstrap, no pipeline**, no per-repo state, no `alc_init`.
- `bootstrap.sh` / `npx alc-install`: thin wrappers around `install.sh` — same behaviour as above.

### What gets RUN at install time

- Read-only repo scans (`build_repo_baseline`, `build_map`).
- Static template writes (`latest-approved-gates.md` with `- none`).
- One MCP server smoke test (`alc_init`).
- Unit + integration + pressure tests when `--verify`.

### What does NOT get run at install time

- `bin/backfill_transcripts` — never invoked by any install / init script (verified by `git log -S backfill_transcripts -- install.sh init_learning_system alc_init` returning no commits).
- `bin/ingest_new_transcripts`.
- `bin/extract_sessions` over `~/.claude/projects` or `~/.codex/sessions`.
- `bin/index_events` — `events.sqlite` is never built at install.
- `bin/distill_learning`.
- `bin/refresh_learning_state` — the full 645-line orchestrator is never invoked automatically anywhere.
- All five analysts (`analyst_score`, `analyst_patterns`, `analyst_anomalies`, `analyst_correlations`, `recommender_render`).
- `bin/auto_distill_session` — only triggered by a Stop hook, which only fires after at least one full session has happened **after** install.

## 2. Pipeline gap — what's missing for the loop to work on a fresh install

A fresh install lands with:

- `baseline.json`, `skill-map.json` populated (repo scan only).
- `latest-approved-gates.md` carrying "`- none`".
- `latest-skill-context.md` empty (no `events.sqlite`, no usage).
- `latest-session-context.md` populated by `alc_init` (repo-profile/doc-contract data from `bin/repo_profile.py`, CE playbook, and empty runtime summary).
- `hook-events.jsonl` an empty 0o600 file.
- `improvement-queue.jsonl` an empty file.
- **No** `events.sqlite`. **No** session corpus. **No** queued candidates.

So on a fresh install nothing the loop is designed to produce — gate proposals, skill-impact deltas, domain-rule candidates, dedup'd queue rows — exists. The first session the operator runs gets exactly the "compact" surface ALC promises, but those surfaces are empty until enough hook events accumulate AND `refresh_learning_state` is run AND `auto_distill_session` has had at least one Stop hook to fire on AND the operator manually runs `/alc-report` or `scripts/render_unified_report.py`.

Concretely, for the loop to be "warm" at the end of bootstrap we need to do something equivalent to:

```
backfill_transcripts --since 30d \
    --claude-dir ~/.claude/projects \
    --codex-dir  ~/.codex/sessions
index_events                              # build events.sqlite from hook-events.jsonl
extract_sessions --path ~/.claude/projects --path ~/.codex/sessions \
                 --days 30 --max-sessions 200 \
                 --output <state>/session-corpus.txt
refresh_learning_state --repo <repo>      # baseline+skill_map+usage+impact+gate-eff+
                                          # propose_domain_rules+queue dedup+exports
```

None of those is wired into the install/bootstrap path today.

There are **4 309 events** worth of telemetry sitting in this very repo's
`hook-events.jsonl` (per Tom's note in the prompt), and **1 729** transcript
files under `~/.claude/projects`. None of them flow into a fresh install's
`events.sqlite` or `improvement-queue.jsonl` until the operator manually
invokes the pipeline.

## 3. Regression archaeology — when did backfill at install get removed?

**Short answer: it was never wired.** Searching the full git history for any
prior commit that wired `backfill_transcripts` / `extract_sessions` /
`distill_learning` / `refresh_learning_state` / `index_events` into
`install.sh`, `init_learning_system`, `alc_init`, `bootstrap.sh`, or
`scripts/alc-install.mjs` returns **zero hits**:

```bash
git log --all -S'backfill_transcripts' -- install.sh bootstrap.sh scripts/alc-install.mjs
# (empty)
git log --all -p -- install.sh | grep -E '^\+.*(backfill|extract_sessions|distill_learning|refresh_learning_state)'
# (empty)
git log --all -p -- agent-learning-compounder/bin/init_learning_system | grep -E '^\+.*(backfill|extract_sessions|distill_learning)'
# (empty — only `from distill_learning import …` symbol imports)
git log --all -p -- agent-learning-compounder/bin/alc_init | grep -E '^\+.*(backfill|extract_sessions|distill_learning|refresh_learning)'
# (empty)
```

Relevant commits for the timeline:

- `0ae7832` (2026-05-24, "Vendored upstream agent-learning-compounder 2026.05.24+review7-production") — the initial vendoring. `init_learning_system` already had its current shape: build baseline, write empty exports, manifest-only refresh, no pipeline calls.
- `dfc0031` (after the vendoring, 2026-05-26 fix series, "feat(u5.5.2): transcript_parser + backfill_transcripts + ingest_new_transcripts adapters") — `backfill_transcripts` and `ingest_new_transcripts` are **introduced** here, never hooked into install.
- `d2cd2d3` (2026-05-26, "feat(first-run): alc_init brings MCP green and writes per-repo session context") — `alc_init` is introduced; it does profiling + MCP smoke + session-context render, no pipeline.
- `8cc1d36` (2026-05-26, "feat(integration): wire alc_query into alc_init + ce_playbook; add doc-contract") — `alc_init` gains the 6-read summary block (still no pipeline; reads are graceful on empty state).
- `7c11449` (2026-05-26, "refactor(alc_init): extract session-context renderers to session_context_render module") — current shape solidifies.

The design intent is explicit in `docs/dev/production-signoff.md` and
`docs/dev/self-healing-roadmap.md` § "Design Patterns Applied":

> Script-only cron readiness: init writes an automation manifest for a no-agent
> refresh routine, but does **not mutate any live scheduler** (cron, systemd
> timer, launchd, Hermes, etc.).

The doctrine all along has been "install writes the wiring, the operator (or
their scheduler) runs the pipeline." Tom's memory of the early-days experience
likely conflates one of:

- The very first manual full-pipeline run after install (when the operator
  themselves invoked `refresh_learning_state` or `/alc-report` and saw it
  parse "every fucking thing"), with
- The intended behaviour described in the self-healing roadmap, which reads
  as if the loop closes itself.

The actual mechanism that *could* have been thought of as "init backfill" is
`auto_distill_session`, but (a) it triggers off the Stop hook, not install,
and (b) it runs `extract_sessions --days 1 --max-sessions 20` — bounded to
recent activity, not a full backfill of `~/.claude/projects`.

## 4. Proposed wiring — minimum hook to bring backfill back

Bring the loop online at the end of `install.sh --bootstrap-repo`, after
`alc_init` and behind an opt-out flag. Two-step:

### 4.1 Add a small orchestrator script (recommended: extend `refresh_learning_state` rather than create a new one)

`refresh_learning_state` is the orchestrator, but it doesn't currently call
the *ingest* steps — it assumes events already exist. The architecture
backlog `#06` already flags this as the file to evolve when "a second
pipeline shape appears", which is exactly the situation here. Two viable
shapes:

**Option A — Inline in `install.sh --bootstrap-repo`** (smallest delta):

```sh
# … after alc_init …
if [ "$first_run_backfill" -eq 1 ]; then
  python3 "$bootstrap_dest/bin/backfill_transcripts" \
      --since "${ALC_BACKFILL_SINCE:-30d}" \
      --state-dir "$repo_root/.agent-learning"
  python3 "$bootstrap_dest/bin/index_events" \
      --state "$repo_root/.agent-learning/repos/<id>"
  python3 "$bootstrap_dest/bin/extract_sessions" \
      --path "$HOME/.claude/projects" \
      --path "$HOME/.codex/sessions" \
      --days "${ALC_BACKFILL_DAYS:-30}" \
      --max-sessions "${ALC_BACKFILL_MAX_SESSIONS:-200}" \
      --output "$repo_root/.agent-learning/repos/<id>/session-corpus.txt"
  python3 "$bootstrap_dest/bin/refresh_learning_state" \
      --repo "$repo_root" \
      --state-dir "$repo_root/.agent-learning"
fi
```

Order: backfill (writes JSONL) → index (builds SQLite from JSONL) →
extract (writes session-corpus.txt the propose_domain_rules step reads) →
refresh (full evaluate+propose+export pass over the now-populated state).

Default `first_run_backfill=1`, opt-out via
`--no-first-run-backfill` and `ALC_FIRST_RUN_BACKFILL=0`.

**Option B — A new `bin/alc_bootstrap_pipeline` script** that owns the
sequence and is called from both `install.sh --bootstrap-repo` and from a
new `alc_init --backfill` flag. This is cleaner long-term (single
testable entry point, same code path whether install or alc_init invokes
it) and aligns with backlog item `#06`. Recommended.

Either way the chain is the same. `refresh_learning_state` already runs
`extract_skill_usage` over `hook-events.jsonl`, `evaluate_gate_effectiveness`,
`propose_domain_rules`, dedup, and the export writes — it just needs the
upstream feeders to have done their job first.

### 4.2 Have `alc_init` call into the pipeline orchestrator

Today `alc_init` is the first-run CLI/session-context orchestrator for "what's
in your repo + is MCP green" and six graceful-empty `alc_query` reads. The
repository detection and documentation-contract vocabulary now live in
`bin/repo_profile.py`, which keeps `alc_init` out of owning those domain rules.
After the install-time backfill,
`alc_init`'s six reads would actually return rows, and the session-context
prose would synthesize a real summary instead of "no recent activity".

The merge between `alc_init` and `refresh_learning_state` is **not**
recommended in full — they have different jobs (profiler vs orchestrator)
— but `alc_init` should learn to call into the pipeline orchestrator (if
one exists per Option B above, or `refresh_learning_state` directly) when
asked to. Add `--backfill` / `--with-pipeline` flag.

## 5. Tradeoffs — sync vs background

Running the pipeline at install time is the obvious right answer for
correctness ("install works → loop is warm"), but it has real cost.

### Volume (this repo, today)

- 1 729 Claude transcript files under `~/.claude/projects`, 859 modified
  in the last 7 days.
- 4 309 hook events sitting in this repo's `hook-events.jsonl` (per the
  audit prompt).
- Codex transcripts under `~/.codex/sessions` (smaller corpus).

### Sync (install blocks until pipeline done)

- Pros: install is "obviously works". Operator runs `/alc-report` immediately
  after install and sees real numbers. Every subsequent session benefits.
  Failures surface during install, not silently at first session.
- Cons: install latency goes from ~1 minute (`--verify`) to 1 minute + ~30s
  for first-time pipeline on this volume (extrapolating from
  `auto_distill_session`'s 1-day/20-session window taking 5–10s). For
  operators with very long Claude history (e.g. 6 months of daily use),
  could be several minutes. Operator may Ctrl-C, leaving a half-built
  `events.sqlite`.

### Background (install returns immediately, pipeline forks)

- Pros: install stays snappy. Pattern already exists (`auto_distill_session`
  forks-and-detaches via `setsid -f`).
- Cons: harder to debug ("did it work?"). Operator runs `/alc-report` 30s
  later and may still see empty data. Log goes to
  `$PERSONAL/logs/auto-distill-*.log` which the operator may not know to
  check. Race window: if the operator starts a real session within 30s,
  hook events from the new session interleave with the backfill.
  Cancellation/cleanup semantics are awkward (orphan process holding
  `.refresh.lock` if killed).

### Recommendation

**Sync with a bounded window by default.** Run backfill + index + extract +
refresh inline at install time, but bound it to:

- `--days 30` for backfill (operator opts in to more via flag/env).
- `--max-sessions 200` for extract (matches `auto_distill_session`'s ratio
  on a larger window).
- A timeout: if the chain exceeds 5 minutes, abort cleanly and tell the
  operator to run `refresh_learning_state` manually.

This buys "obviously works" without the long-history latency cliff. Add a
`--background-backfill` flag for operators who want speed over visibility,
which then forks-and-detaches the same chain via the existing
`auto_distill_session` pattern.

Either way, the loop should be **runnable** post-install with one
operator-friendly command, ideally `alc_init --refresh` or
`/alc-report --rebuild`, so backfill becomes a re-runnable maintenance
operation rather than a one-shot install-time thing.

## 6. Open questions for follow-up

- Should `refresh_learning_state` learn the ingest steps, or should a
  separate `alc_bootstrap_pipeline` own the full chain and call `refresh`
  at the end? Backlog item `#06` argues for the second shape now that the
  trigger ("a second pipeline shape") has appeared.
- The refresh manifest at `automation/agent-learning-refresh.manifest.json`
  is currently a declaration; nothing reads it. A `crontab`/`systemd`/
  `launchd` template generator under `scripts/maintenance/` would let
  operators register the refresh in one copy-paste, closing the loop the
  design always promised.
- `auto_distill_session` writes to `$AGENT_LEARNING_PERSONAL` (default
  `~/.agent-learning`), not `<repo>/.agent-learning` — so its outputs
  don't currently feed the per-repo `events.sqlite` that `alc_query`
  reads. Worth checking whether this is intentional (personal vs repo
  separation) or a regression that means Stop-hook distillation never
  populates the surface the bootstrap is supposed to warm up.

## 7. Files inspected

- `/home/tth/work/active/agent-learning-compounder/install.sh`
- `/home/tth/work/active/agent-learning-compounder/bootstrap.sh`
- `/home/tth/work/active/agent-learning-compounder/scripts/alc-install.mjs`
- `/home/tth/work/active/agent-learning-compounder/agent-learning-compounder/bin/init_learning_system`
- `/home/tth/work/active/agent-learning-compounder/agent-learning-compounder/bin/alc_init`
- `/home/tth/work/active/agent-learning-compounder/agent-learning-compounder/bin/refresh_learning_state`
- `/home/tth/work/active/agent-learning-compounder/agent-learning-compounder/bin/backfill_transcripts`
- `/home/tth/work/active/agent-learning-compounder/agent-learning-compounder/bin/ingest_new_transcripts`
- `/home/tth/work/active/agent-learning-compounder/agent-learning-compounder/bin/auto_distill_session`
- `/home/tth/work/active/agent-learning-compounder/agent-learning-compounder/bin/index_events`
- `/home/tth/work/active/agent-learning-compounder/agent-learning-compounder/bin/install_runtime_hooks`
- `/home/tth/work/active/agent-learning-compounder/agent-learning-compounder/scripts/render_unified_report.py`
- `/home/tth/work/active/agent-learning-compounder/agent-learning-compounder/commands/alc-report.md`
- `/home/tth/work/active/agent-learning-compounder/agent-learning-compounder/hooks/hooks.json`
- `/home/tth/work/active/agent-learning-compounder/ARCHITECTURE.md`
- `/home/tth/work/active/agent-learning-compounder/CHANGES.md`
- `/home/tth/work/active/agent-learning-compounder/docs/dev/self-healing-roadmap.md`
- `/home/tth/work/active/agent-learning-compounder/docs/dev/production-signoff.md`
- `/home/tth/work/active/agent-learning-compounder/docs/dev/architecture-backlog-2026-05.md`
