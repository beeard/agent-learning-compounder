# LFG Invocation Prompt — ALC Plugin Refactor v2

**Primary orchestrator:** `codex exec -m gpt-5.3-codex-spark` (operator preference).
**Fallback orchestrator:** Claude Code `/lfg` (see bottom).

The prompt below is written so the orchestrating model drives the wave plan, spawns
per-unit subagents via `codex exec` (recursive) into isolated git worktrees, and runs
gate-checks between waves. The execution strategy and gate criteria are unchanged from
the prior Claude-Code version — only the dispatch primitive changes.

## REPO LAYOUT

```
~/work/active/agent-learning-compounder/                    ← canonical dev repo (master, GitHub remote)
└── agent-learning-compounder/                              ← inner skill source-tree

~/work/active/agent-learning-compounder-v2/                 ← V2 WORKTREE (alc-plugin-v2 branch)
└── agent-learning-compounder/                              ← inner skill source-tree (work here)

~/.agents/skills/agent-learning-compounder/                 ← LIVE RUNTIME (frozen during V2)
                                                              Re-installed via install.sh after Phase F merge.
```

**Working directory for LFG:** `/home/tth/work/active/agent-learning-compounder-v2/`
- Tests + commands run from: `/home/tth/work/active/agent-learning-compounder-v2/agent-learning-compounder/`
- Branch: `alc-plugin-v2` (pushed to `origin/alc-plugin-v2`)
- GitHub: `https://github.com/beeard/agent-learning-compounder` (rename already done)

**Source-tree conventions** (from CLAUDE.md, observe these):
- Dual-name files: `bin/<name>` (canonical) + `bin/<name>.py` (symlink); same for `reference-lib/` ↔ `references/.md`
- Tests: `tests/` smoke + `fixtures/tests/` full suite + `scripts/run_pressure_tests.py` durable-write gate
- Run from inner `agent-learning-compounder/` dir
- Distribution: `./install.sh --codex --verify` (or `--claude`) copies inner source-tree to runtime roots

---

## How to invoke (codex exec, primary path)

From the worktree root:

```bash
cd /home/tth/work/active/agent-learning-compounder-v2/
codex exec \
  -m gpt-5.3-codex-spark \
  -s workspace-write \
  --ignore-user-config \
  -c 'model_reasoning_effort="medium"' \
  - <<'EOF'
[paste "Prompt to paste" block below]
EOF
```

Flags rationale:
- `-m gpt-5.3-codex-spark` — fast Codex-tuned model variant (operator preference).
- `-s workspace-write` — orchestrator needs to commit, create worktrees, and read repo
  state. Keep `danger-full-access` off; per-unit subagents inherit the same scope
  inside their worktree.
- `--ignore-user-config` — strips the operator's `~/.codex/config.toml` (MCP servers,
  pre-activated skills, memories, hooks). Measured prelude drop: 19,357 → 6,904 input
  tokens (~64% reduction) on a smoke turn. Across 28+ subagent dispatches over a full
  LFG run, this saves ~340K input tokens. Orchestrator gets all its context from the
  pasted prompt + worktree files; nothing from the user config is needed.
- `-c 'model_reasoning_effort="medium"'` — explicit override since `--ignore-user-config`
  discards the config's default. `high` is overkill for pure orchestration; `medium`
  balances dispatch-quality vs cost. Per-unit subagents can opt for higher effort in
  their own `codex exec` calls if a unit needs deeper reasoning.

Stream-of-output goes to stdout. Capture with `tee` if you want a transcript:

```bash
codex exec -m gpt-5.3-codex-spark -s workspace-write --ignore-user-config \
  -c 'model_reasoning_effort="medium"' \
  2>&1 | tee logs/lfg-$(date +%Y%m%dT%H%M%S).log
```

---

## Prompt to paste

```
Execute the implementation plan at:

  docs/plans/2026-05-25-001-refactor-alc-plugin-rewrite-plan.md         (executive view: overview, KTDs, roadmap, verification)
  docs/plans/2026-05-25-001-refactor-alc-plugin-rewrite-plan-units.md   (implementer view: 22 detailed units)

Working directory: /home/tth/work/active/agent-learning-compounder-v2/
All code work happens in subdir: agent-learning-compounder/ (per CLAUDE.md convention)
Branch: alc-plugin-v2 (already pushed to origin/alc-plugin-v2)

This plan supersedes docs/plans/2026-05-25-alc-plugin-refactor.md.

Plan-fil-splitting (post pass-7): subagents per unit should load BOTH files first — overview for context, units for their specific U-ID spec. Total ~1768 lines split into 578 (overview) + 1190 (units) for navigable subagent context windows. Skip plan-creation phase; the plan is finalized through 7 review-passes with all findings baked in.

EXECUTION STRATEGY: wave-based parallel subagent dispatch per the plan's "Parallel Execution Plan" section. Critical path = ~12 wall-clock steps vs 21 units → ~40% reduction over serial execution.

ORCHESTRATION PRIMITIVE: you are the orchestrator. Dispatch each unit as a child `codex exec` invocation inside its own git worktree. Each child uses the same lean flags as the orchestrator — strip user config to minimize prelude bloat:

  WORKTREE=../alc-plugin-v2-exp-<wave>-<unit>          # sibling to the orchestrator worktree
  git worktree add "$WORKTREE" alc-plugin-v2           # branch off the integration branch
  codex exec \
    -m gpt-5.3-codex-spark \
    -s workspace-write \
    --ignore-user-config \
    -c 'model_reasoning_effort="medium"' \
    --cd "$WORKTREE" \
    "<unit-specific-prompt>"

(`--ignore-user-config` strips the operator's ~/.codex/config.toml — MCP servers, pre-activated skills, memories, hooks. Saves ~12K input tokens of prelude per child. Across 28+ dispatches: ~340K tokens. `--cd` sets the child's working directory to the worktree so it reads the right files. If a specific unit needs higher reasoning, that unit's prompt can request `-c 'model_reasoning_effort="high"'` — default is medium.)

For parallel waves, background each child (`&`) and `wait` for the batch before running the gate-check. Each child commits on its own branch (`alc-plugin-v2-exp-<wave>-<unit>`); after the batch, orchestrator merges children into `alc-plugin-v2` in dependency order, then removes worktrees + branches.

Per-unit prompt template (instantiate with U-ID, files, dependencies from the units doc):

  You are executing unit <U-ID> from docs/plans/2026-05-25-001-refactor-alc-plugin-rewrite-plan-units.md.
  Read BOTH plan files for context, then implement only this unit's Files + Approach + Verification.
  Honor any Execution note (test-first / characterization-first). Add tests per Test scenarios.
  Run the unit's verification locally before committing. Commit on this worktree's branch with a conventional message derived from the unit's Goal. Do NOT push.
  Report: a) unit done with commit SHA, or b) blocked with diagnostics.

PHASE A (BLOCKS ALL SUBSEQUENT WORK):
- W1: One child for U1 (worktree + baseline test snapshot). On completion, verify baseline test count recorded.
- W2: STOP for operator. U2 is three validation gates (G0.5.1 premise, G0.5.2 cross-runtime, G0.5.3 hook-events schema). These require manual judgment (≥6h human work, partly empirical). Operator drives. Do NOT auto-proceed to Phase B until RESULTS.md commits decision: "Phase B green-light" OR "Scope collapse: drop Phase D-F, ship synthesizer + SessionStart nudges only".

PHASE B (Foundation) — if Phase A green-lit:
- W3: 2 parallel children for U3 (plugin shell) + U5 (synthesizer)
- W4: After U3 done → 4 parallel for U4 (refactor SKILL.md) + U6 (data-contracts manifest-per-unit + validator) + U14 (alc-reviewer persona) + U18 (codex sync, no-op if G0.5.2 red)
- W5: After U6 done → 3 parallel for U7 (StateHandle) + U5.5.0a (event_schema dataclass) + U5.5.0b (event_writer with boundary)
- W6: After U5.5.0b done → 5 parallel for U5.5.1 (DEFAULT_EVENTS taxonomy) + U5.5.2 (transcript ingest split) + U5.5.3 (correlate_events) + U5.5.4 (event_emit) + U5.5.5 (index_events sqlite)

PHASE C (Core pipeline):
- W7: 2 parallel for U8 (analyst scripts backed by events.sqlite) + U10.5 (alc_query.py shared read API)
- W8: Sequential U9 (recommender + generators.py emitting Hermes-DSL ops)

PHASE D (Apply + invocation):
- W9a: U11 publishes bin/alc_apply_contracts.py FIRST (just contracts: validate_agent_frontmatter, validate_skill_frontmatter, DSL_TARGETS, ApplyResult/RevertResult dataclasses, Executor ABC). ~15 min.
- W9b: After contract committed → 4 parallel for U10 (read-only dashboard) + U11-impl (executor implementation) + U12 (alc_invoke) + U17 (MCP extensions). U12 and U17 design against bin/alc_apply_contracts.py contract module — they don't need to wait for U11 implementation.

PHASE E1+E2:
- W10: 3 parallel for U15 (/alc-report command) + U16 (hooks) + U13 (eval-loop, depends on U12)

PHASE F:
- W11: Sequential U19 (context-boundary regression + capability-map + e2e smoke with REAL data, not seeded)

POST-MVP (NOT auto-dispatched):
- W12: U20 (`alc-cloudflare-sync`) — opt-in cross-repo memory via D1 + Vectorize. After W11 green and operator opt-in via `.agent-learning.json` (`cloudflare_sync.enabled=true`), operator runs `codex exec -m gpt-5.3-codex-spark` against U20's spec separately. Do NOT auto-dispatch W12 from the same LFG run as W1-W11.

GATE-CHECK BETWEEN WAVES (parent orchestrator runs in the integration worktree):
  cd agent-learning-compounder
  python3 -m unittest discover -s tests 2>&1 | tail -5
  python3 -m unittest discover -s fixtures/tests 2>&1 | tail -5
  python3 bin/validate_artifacts --check-manifest-merge 2>&1 | tail -5
  python3 bin/validate_artifacts --check-contracts --state-dir .agent-learning 2>&1 | tail -5

Default gate-check uses system python3 — Phase A baseline is 251 pass / 4 skip (the four dashboard tests skip when fastapi/jinja2 absent) / 0 fail.

VENV GATE-CHECK (only when the wave touched U10 dashboard or U17 MCP):
  python3 -m venv ... (see preflight) → activate
  ../.venv/bin/python -m unittest fixtures.tests.test_dashboard 2>&1 | tail -5
  ../.venv/bin/python -m unittest fixtures.tests.test_alc_mcp 2>&1 | tail -5

Pre-existing baseline failures with venv active: 4 dashboard tests (test_index_renders, test_gates_partial_returns_table, test_queue_partial_returns_empty_state, test_probes_partial_returns_empty_state) fail with 404/503 — dashboard.py and the test fixtures drifted. These are explicitly in U10 + U19 scope and do NOT block earlier waves. Track regressions in the dashboard test set as "delta from these 4 known failures" until U10/U19.

Wave fails if any test broken OR validate_artifacts reports orphan files. Block next wave, debug, retry. After 3 retries on the same unit, pause and surface to operator.

WORKTREE LIFECYCLE per wave:
  1. Before dispatch: `git worktree add ../alc-plugin-v2-exp-<wave>-<unit> alc-plugin-v2`
  2. Dispatch child codex exec inside that worktree (background; collect PID)
  3. After all children in the wave return: review each diff, run gate-check on the integration worktree against each child's branch, then merge in dependency order
  4. `git worktree remove ../alc-plugin-v2-exp-<wave>-<unit>` and `git branch -d alc-plugin-v2-exp-<wave>-<unit>`
  5. Run gate-check on the merged integration tree before dispatching the next wave

REVIEW LOOP (between merge and gate-check, per child):
  Invoke compound-engineering:ce-correctness-reviewer + ce-testing-reviewer on each unit's diff. Block merge if either reviewer returns blocker-severity findings; re-dispatch the child with the feedback included in its prompt.

CONSTRAINTS:
- Python 3.11+ stdlib only (no new deps without operator approval; optional extras already installed for U10/U17)
- Cross-runtime: Claude + Codex (Codex conditional on G0.5.2)
- Existing dashboard/ (FastAPI + React) NOT touched until U19's migration-decision commits direction
- Existing bin/validate_outputs.py UNCHANGED (R6) — new validator is bin/validate_artifacts
- Context boundary enforced in event_writer.py + artifact_writer.py (KTD-16) — children do NOT need to per-artifact-scan
- All apply/eval/invoke emit events via event_writer (KTD-13) — no separate apply-log.jsonl or outcomes.json

ON FAILURE:
- If a unit's tests fail after 3 retries: pause, surface diagnostics to operator
- If a wave's gate-check fails: revert that wave's merge commits, redispatch only failing units with reviewer feedback
- If Phase A G0.5.1 returns RED (premise unvalidated): execute Out-of-Scope Plan B — ship U3+U4+U5 only, document scope collapse in RESULTS.md, skip Phase D-F

FINAL PR (after W11 green):
- Branch: alc-plugin-v2
- Title: "refactor(alc): plugin v2 — Hermes-DSL apply, unified observability, agent archive"
- Body: link to plan + summary of all 6 phases + test results + dashboard screenshot
- Reviewers: skip request_copilot_review; operator approves manually
- Push only after operator confirms

Start with W1. After W1 commits, stop and surface to operator: "W1 complete. W2 is operator-driven (3 validation gates). Ready to proceed when RESULTS.md commits green-light."
```

---

## Notes for operator

- **Total wall-clock estimate:** ~9-12 hours if Phase A green-lit; ~5-6 hours if scope collapses to synthesizer-only. Codex-Spark fast tier should land near the low end.
- **Subagent budget:** max fan-out is 5 (W6). gpt-5.3-codex-spark token costs are lower than gpt-5.5; with `--ignore-user-config` stripping prelude bloat (~12K tokens/dispatch × 28 dispatches = ~340K input tokens saved), rough estimate $3-8 for full execution including reviews. Without the strip, expect $5-10.
- **Operator gates:** W2 is the one mandatory operator gate. All other waves are auto-dispatched if gate-check passes.
- **Resume:** if interrupted, restart `codex exec` with the same prompt — it inspects existing merged commits on `alc-plugin-v2` and skips completed waves. Each wave commits to the integration branch independently.
- **Scope-collapse path:** Phase A's G0.5.1 returning RED is a planned outcome, not a failure. Document in RESULTS.md and execute the collapsed scope (synthesizer + nudges).

## Pre-flight checklist before invoking

- [ ] On worktree `agent-learning-compounder-v2/`, branch `alc-plugin-v2`, `git status` clean
- [ ] `codex --version` reports a build with `-m gpt-5.3-codex-spark` available (`codex doctor` should list spark in models)
- [ ] `~/.hermes/` exists (for reference patterns — S1 dependency)
- [ ] Codex `subagent-driven-development` skill OR Claude Code equivalent available in your active runtime
- [ ] Optional Python extras installed in worktree-root `.venv/` (mcp, fastapi, jinja2, uvicorn, httpx, sentence-transformers) — required by U10 (dashboard) and U17 (MCP). System Python is PEP 668 externally-managed; use the venv:
      ```bash
      # From the worktree root (agent-learning-compounder-v2/), NOT inside the inner skill tree —
      # install.sh `cp -a`'s the inner tree and would otherwise copy multi-GB .venv into runtime roots.
      python3 -m venv --system-site-packages .venv
      .venv/bin/pip install -r agent-learning-compounder/requirements-optional.txt
      ```
      Subagents that need these imports invoke `../.venv/bin/python` from `agent-learning-compounder/` (or `source ../.venv/bin/activate`). System python3 is used for default gate-checks; venv is opted into only by units that need it.
- [ ] At least 4 hours of focused time available for W2 (operator-driven validation gates)
- [ ] Other-session's `alc-session-metrics-adapter.mjs` accessible at `/home/tth/alc-agent-native-audit-export-2026-05-25T17-16-05/scripts/`

## After execution

The plan's Phase F (U19) produces:
- `<state>/dashboard-migration-decision.md` (committed: legacy dashboard/ fate)
- Full test suite green (existing + new from U1-U18)
- e2e smoke succeeds without seeded recommendations.json
- events.sqlite contains rows from all 5 actor_kinds + patch_applied + eval_verdict (KTD-13 verification)

Merge worktree branch into master when all gates pass.

---

## Fallback orchestrator (Claude Code `/lfg`)

If `codex exec` is unavailable or the operator prefers Claude Code's wave dispatch:

```
/lfg execute the implementation plan at:
  docs/plans/2026-05-25-001-refactor-alc-plugin-rewrite-plan.md
  docs/plans/2026-05-25-001-refactor-alc-plugin-rewrite-plan-units.md

Working directory: /home/tth/work/active/agent-learning-compounder-v2/
Branch: alc-plugin-v2

[paste the EXECUTION STRATEGY / PHASE A-F / GATE-CHECK / CONSTRAINTS / ON FAILURE / FINAL PR
 sections from the codex prompt above, verbatim. Replace "child codex exec" wording with
 Claude's Agent tool using isolation: "worktree", run_in_background: true.]
```

Both paths converge on the same gate criteria, the same wave plan, and the same RESULTS.md
exit conditions for Phase A. Pick one orchestrator and stay with it for the whole run —
mixing dispatch primitives mid-execution makes worktree cleanup fragile.
