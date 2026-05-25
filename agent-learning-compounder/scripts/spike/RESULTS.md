# ALC Plugin Rewrite — Phase A Spike Results

Date: 2026-05-25
Branch: alc-plugin-v2
Working tree: /home/tth/work/active/agent-learning-compounder-v2/

## W1 — Baseline test snapshot (U1)

- `python3 -m unittest discover -s fixtures/tests`
  - Ran `251` tests in `25.882s`
  - `OK (skipped=4)`
- `python3 -m unittest discover -s tests`
  - Ran `1` test in `0.000s`
  - `OK`
- `python3 scripts/run_pressure_tests.py`
  - `pressure checks passed: 4`

### Dashboard import check

- `import dashboard` succeeds.
- `dashboard.build_app()` raises expected dep gate: `ImportError: fastapi required for dashboard (pip install fastapi uvicorn)`

---

## W2 — Phase A validation gates (U2)

Run each spike driver, then fill in the rubric below.

### G0.5.1 — Premise validation

Driver: `agent-learning-compounder/scripts/spike/spike_validate_premise.sh`

**Question:** Does running a specialist analyst against the operator's real `~/.claude/projects` corpus surface ≥ 3 non-obvious AND actionable recommendations in the top-10?

**Grading rubric (after running the driver):**

For each of the top-10 anomalies the driver prints, mark `Y` / `N`:

| # | Bucket | Non-obvious? | Actionable? | Both? |
|---|--------|--------------|-------------|-------|
| 1 |        | _            | _           | _     |
| 2 |        | _            | _           | _     |
| 3 |        | _            | _           | _     |
| 4 |        | _            | _           | _     |
| 5 |        | _            | _           | _     |
| 6 |        | _            | _           | _     |
| 7 |        | _            | _           | _     |
| 8 |        | _            | _           | _     |
| 9 |        | _            | _           | _     |
| 10 |       | _            | _           | _     |

**Tally `Both? = Y`:** ___ / 10

**Verdict:**
- [ ] **GREEN** (≥ 3) — premise validated; proceed to Phase B
- [ ] **RED** (< 3) — scope collapse: drop Phase D–F; ship U3 + U4 + U5 (synthesizer + nudges only)

**Notes / specific examples:**

> _(fill in: which anomalies were the strongest signals; which felt obvious vs surprising)_

---

### G0.5.2 — Cross-runtime assumption check

Driver: `agent-learning-compounder/scripts/spike/spike_validate_runtime.sh`

Plus manual AGENTS.md smoke (the driver prints the exact one-liner).

**Per-check verdicts:**

| Check | GREEN | YELLOW | RED |
|-------|:-----:|:------:|:---:|
| `${CLAUDE_PLUGIN_ROOT}` exported in active Claude session | _ | _ | _ |
| Codex `.codex-plugin/` discovery convention works | _ | _ | _ |
| Codex AGENTS.md auto-load (token-echo smoke) | _ | _ | _ |

**Composite verdict** (drives U3's Codex scope per plan):
- [ ] **GREEN, full** — keep `.codex-plugin/` + `AGENTS.md`
- [ ] **YELLOW (AGENTS.md only)** — drop `.codex-plugin/`, keep content parity in `AGENTS.md`
- [ ] **RED** — drop Codex entirely; ALC remains Claude-only

**Notes:**

> _(fill in: exact codex version, AGENTS.md echo result, any blockers)_

---

### G0.5.3 — Data-schema discovery + path validation

Driver: `agent-learning-compounder/scripts/spike/spike_validate_schema.sh`

**Per-check verdicts:**

| Check | GREEN | YELLOW | RED |
|-------|:-----:|:------:|:---:|
| `hook-events.jsonl` found on disk + schema captured | _ | _ | _ |
| `schema_version` v3 → v4 migration target identified | _ | _ | _ |
| `{id, tokens, duration_s}` recoverable from claude-insights | _ | _ | _ |
| `{cost_usd}` recoverable (raw or computed from tokens × pricing) | _ | _ | _ |

**Composite verdict:**
- [ ] **GREEN** — U5.5 + U5 have a real corpus to target
- [ ] **YELLOW (cost only)** — acceptable; U5 derives cost from tokens × pricing table
- [ ] **RED (no hook-events)** — v4 schema work runs on synthetic fixtures only

**Notes:**

> _(fill in: where hook-events.jsonl lives, observed schema versions, what's missing)_

---

## Phase B decision

Recorded here after all three gates above are graded.

- `g0_5_1_premise`        = pending
- `g0_5_2_cross_runtime`  = pending
- `g0_5_3_data_schema`    = pending
- `scope_collapse`        = pending  (true iff G0.5.1 = RED)
- `phase_b_green_light`   = pending  (true iff G0.5.1 = GREEN and gate-checks survive)

When complete, replace `pending` with the verdict; commit; re-launch `./scripts/run-lfg.sh` to dispatch W3.
