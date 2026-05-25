# LFG Invocation Prompt — ALC Plugin Refactor v2

Paste this prompt into a fresh Claude Code session (or `/lfg`) to delegate the full plan execution per the wave-orchestration strategy.

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
- GitHub: `https://github.com/beeard/agent-learning-compunder` (typo to fix manually: `gh repo rename agent-learning-compounder`)

**Source-tree conventions** (from CLAUDE.md, observe these):
- Dual-name files: `bin/<name>` (canonical) + `bin/<name>.py` (symlink); same for `reference-lib/` ↔ `references/.md`
- Tests: `tests/` smoke + `fixtures/tests/` full suite + `scripts/run_pressure_tests.py` durable-write gate
- Run from inner `agent-learning-compounder/` dir
- Distribution: `./install.sh --codex --verify` (or `--claude`) copies inner source-tree to runtime roots

---

## Prompt to paste

```
/lfg execute the implementation plan at:

  docs/plans/2026-05-25-001-refactor-alc-plugin-rewrite-plan.md

Working directory: /home/tth/work/active/agent-learning-compounder-v2/
All code work happens in subdir: agent-learning-compounder/ (per CLAUDE.md convention)
Branch: alc-plugin-v2 (already pushed to origin/alc-plugin-v2)

This plan supersedes docs/plans/2026-05-25-alc-plugin-refactor.md. Skip plan-creation phase; the plan is finalized through 5 review-passes (architecture review, ce-doc-review with 7 reviewers, agent-native audit, adversarial deep-review, plus 4 internal arch-passes with all findings baked in).

EXECUTION STRATEGY: wave-based parallel subagent dispatch per the plan's "Parallel Execution Plan" section. Critical path = ~12 wall-clock steps vs 21 units → ~40% reduction over serial execution.

PHASE A (BLOCKS ALL SUBSEQUENT WORK):
- W1: Spawn one subagent for U1 (worktree + baseline test snapshot). On completion, verify baseline test count recorded.
- W2: STOP for operator. U2 is three validation gates (G0.5.1 premise, G0.5.2 cross-runtime, G0.5.3 hook-events schema). These require manual judgment (≥6h human work, partly empirical). Operator drives. Do NOT auto-proceed to Phase B until RESULTS.md commits decision: "Phase B green-light" OR "Scope collapse: drop Phase D-F, ship synthesizer + SessionStart nudges only".

PHASE B (Foundation) — if Phase A green-lit:
- W3: Spawn 2 parallel subagents for U3 (plugin shell) + U5 (synthesizer)
- W4: After U3 done → spawn 4 parallel subagents for U4 (refactor SKILL.md) + U6 (data-contracts manifest-per-unit + validator) + U14 (alc-reviewer persona) + U18 (codex sync, no-op if G0.5.2 red)
- W5: After U6 done → spawn 3 parallel for U7 (StateHandle) + U5.5.0a (event_schema dataclass) + U5.5.0b (event_writer with boundary)
- W6: After U5.5.0b done → spawn 5 parallel for U5.5.1 (DEFAULT_EVENTS taxonomy) + U5.5.2 (transcript ingest split) + U5.5.3 (correlate_events) + U5.5.4 (event_emit) + U5.5.5 (index_events sqlite)

PHASE C (Core pipeline):
- W7: Spawn 2 parallel for U8 (analyst scripts backed by events.sqlite) + U10.5 (alc_query.py shared read API)
- W8: Sequential U9 (recommender + generators.py emitting Hermes-DSL ops)

PHASE D (Apply + invocation):
- W9a: U11 publishes bin/alc_apply_contracts.py FIRST (just contracts: validate_agent_frontmatter, validate_skill_frontmatter, DSL_TARGETS, ApplyResult/RevertResult dataclasses, Executor ABC). ~15 min.
- W9b: After contract committed → spawn 4 parallel for U10 (read-only dashboard) + U11-impl (executor implementation) + U12 (alc_invoke) + U17 (MCP extensions). U12 and U17 design against bin/alc_apply_contracts.py contract module — they don't need to wait for U11 implementation.

PHASE E1+E2:
- W10: Spawn 3 parallel for U15 (/alc-report command) + U16 (hooks) + U13 (eval-loop, depends on U12)

PHASE F:
- W11: Sequential U19 (context-boundary regression + capability-map + e2e smoke with REAL data, not seeded)

GATE-CHECK BETWEEN WAVES (parent orchestrator runs):
  python3 -m unittest discover -s tests 2>&1 | tail -5
  python3 -m unittest discover -s fixtures/tests 2>&1 | tail -5
  python3 bin/validate_artifacts --check-contracts --state-dir .agent-learning 2>&1 | tail -5

Wave fails if any test broken OR validate_artifacts reports orphan files. Block next wave, debug, retry.

SUBAGENT DISPATCH CONFIG per wave member:
  - Fresh worktree per subagent (../alc-plugin-v2/exp-<wave>-<unit>)
  - Pass subagent the plan path + their specific unit-id + the gate-check command for self-verification before signaling completion
  - Subagents commit on their branch, parent reviews + merges to alc-plugin-v2 main branch
  - Use compound-engineering:ce-correctness-reviewer + ce-testing-reviewer on each unit's diff before merge

CONSTRAINTS:
- Python 3.11+ stdlib only (no new deps without operator approval)
- Cross-runtime: Claude + Codex (Codex conditional on G0.5.2)
- Existing dashboard/ (FastAPI + React) NOT touched until U19's migration-decision commits direction
- Existing bin/validate_outputs.py UNCHANGED (R6) — new validator is bin/validate_artifacts
- Context boundary enforced in event_writer.py + artifact_writer.py (KTD-16) — subagents do NOT need to per-artifact-scan
- All apply/eval/invoke emit events via event_writer (KTD-13) — no separate apply-log.jsonl or outcomes.json

ON FAILURE:
- If a unit's tests fail after 3 retries: pause, surface diagnostics to operator
- If a wave's gate-check fails: revert that wave's commits, redispatch only failing units with adversarial-reviewer feedback
- If Phase A G0.5.1 returns RED (premise unvalidated): execute Out-of-Scope Plan B — ship U3+U4+U5 only, document scope collapse in RESULTS.md, skip Phase D-F

FINAL PR:
- Branch: alc-plugin-v2
- Title: "refactor(alc): plugin v2 — Hermes-DSL apply, unified observability, agent archive"
- Body: link to plan + summary of all 6 phases + test results + dashboard screenshot
- Reviewers: skip request_copilot_review; operator approves manually

Start with W1. After W1 commits, stop and surface to operator: "W1 complete. W2 is operator-driven (3 validation gates). Ready to proceed when RESULTS.md commits green-light."
```

---

## Notes for operator

- **Total wall-clock estimate:** ~9-12 hours if Phase A green-lit; ~5-6 hours if scope collapses to synthesizer-only.
- **Subagent budget:** max fan-out is 5 (W6). At 1.5 tokens-per-thousand-input × ~50K tokens per subagent dispatch × 5 subagents = ~$0.40 per wave. Total estimate: $5-15 for full execution including reviews.
- **Operator gates:** W2 is the one mandatory operator gate. All other waves are auto-dispatched if gate-check passes.
- **Resume:** if interrupted, LFG can resume from last completed wave. Each wave commits independently.
- **Scope-collapse path:** Phase A's G0.5.1 returning RED is a planned outcome, not a failure. Document in RESULTS.md and execute the collapsed scope (synthesizer + nudges).

## Pre-flight checklist before pasting the prompt

- [ ] On branch `alc-agent-dispatch-telemetry` or similar (not on `main`)
- [ ] `git status` clean (no uncommitted work)
- [ ] `~/.hermes/` exists (for reference patterns — S1 dependency)
- [ ] Claude Code with subagent-driven-development skill available
- [ ] At least 4 hours of focused time available for W2 (operator-driven validation gates)
- [ ] Other-session's `alc-session-metrics-adapter.mjs` accessible at `/home/tth/alc-agent-native-audit-export-2026-05-25T17-16-05/scripts/`

## After execution

The plan's Phase F (U19) produces:
- `<state>/dashboard-migration-decision.md` (committed: legacy dashboard/ fate)
- Full test suite green (existing + new from U1-U18)
- e2e smoke succeeds without seeded recommendations.json
- events.sqlite contains rows from all 5 actor_kinds + patch_applied + eval_verdict (KTD-13 verification)

Merge worktree branch into main when all gates pass.
