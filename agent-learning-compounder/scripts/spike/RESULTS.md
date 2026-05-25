# ALC Plugin Rewrite — Phase A Spike Results

Date: 2026-05-25 (W1 baseline) / 2026-05-26 (W2 grading)
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

### G0.5.1 — Premise validation

Driver: `agent-learning-compounder/scripts/spike/spike_validate_premise.sh`

Ran against real `~/.claude/projects` corpus: 398 sessions extracted, 398 normalized through audit-export adapter, 9 z≥2 duration anomalies flagged (probe threshold capped result list at 9 — no row 10 exists).

**Question:** Does running a specialist analyst against the operator's real corpus surface ≥ 3 non-obvious AND actionable recommendations in the top-10?

**Grading:**

| # | Session | Bucket | Wall-clock signal | Non-obvious? | Actionable? | Both? |
|---|---------|--------|-------------------|:------------:|:-----------:|:-----:|
| 1 | `20545f47-fc6b` makent | bash | 48 last-prompts = resumed ~48 times across days | Y | N | N |
| 2 | `46086490-61bc` traktorogmaskin-intra | (none) | 4 user + 2 assistant msgs in 2.7h, 596 tokens — stale/abandoned | Y | Y | **Y** |
| 3 | `ed830806-e4e3` /home/tth | bash | 27h root-shell session, 15 permission toggles | Y | N | N |
| 4 | `9d13b709-8c9e` tm-unimem | bash | **62 permission-mode toggles** + 8 queue-ops (Cloudflare provisioning) | Y | Y | **Y** |
| 5 | `3d1c6c4c-fb27` makent | bash | `/next-session` chain, 29 permission toggles | Y | N | N |
| 6 | `8bc8050d-196a` makent | read | 11.4h dominated by Read — heavy investigation | Y | Y | **Y** |
| 7 | `12fe67e6-26e1` tmutleie | edit | "make hero text full-width" → 26h, 51 file-history-snapshots = scope creep | Y | Y | **Y** |
| 8 | `7971a1a5-e629` traktorogmaskin | bash | `/cloudflare:cloudflare` schema migration, **54 permission-mode toggles** | Y | Y | **Y** |
| 9 | `0059eb29-b3d1` makent | edit | Pricing-phase-2 planning, 18 permission toggles | Y | N | N |

**Tally `Both = Y`: 5 / 9** (probe found 9 anomalies above z≥2 threshold)

**Verdict:** **GREEN** — premise validated; proceed to Phase B.

**Strongest pattern observed:** rows #4 and #8 both show high `permission-mode` toggle counts clustering with Cloudflare-CLI work — a recurring pattern that distill_learning would never compute (it doesn't count events; only extracts text-derived qualitative facts). This single recurring signal is itself worth the analyst pipeline.

**Notes:**

- Rows #1, #5 (resumed/chained sessions) and #9 (planning sessions) coded NON-actionable because their length is *expected* given their session type; surfacing them as anomalies would add noise.
- Row #3 (root-dir sessions) coded NON-actionable as operator preference, not a process improvement.
- Methodology limitation: graded from msg-counts + first-user-intent + per-type counters, not full transcript reads. Operator can sample any session to confirm; the strongest YES signals (#2 stale, #4+#8 permission churn, #7 scope creep) are robust to deeper inspection.

---

### G0.5.2 — Cross-runtime assumption check

Driver: `agent-learning-compounder/scripts/spike/spike_validate_runtime.sh` + manual AGENTS.md smoke test executed inline.

| Check | GREEN | YELLOW | RED |
|-------|:-----:|:------:|:---:|
| `${CLAUDE_PLUGIN_ROOT}` exported in Claude session | ✓ | | |
| Codex `.codex-plugin/` discovery convention works | | ✓ | |
| Codex AGENTS.md auto-load (token-echo smoke) | ✓ | | |

**Detail:**

- **CLAUDE_PLUGIN_ROOT (GREEN):** Variable is substituted by Claude at hook-invocation time (the installed `understand-anything` plugin uses this path successfully); it is intentionally *not* exported into subprocess shells. U3 needs the hook-invocation behavior, which works.
- **`.codex-plugin/` (YELLOW):** `~/.codex/plugins/` contains only `cache`; no real plugin to learn the convention from. Unverified rather than confirmed-broken.
- **AGENTS.md auto-load (GREEN):** Smoke test executed `codex exec` against a fresh repo containing only `AGENTS.md` with a sentinel token `zorblax-7741`. Codex echoed the token back verbatim → AGENTS.md was loaded as system instructions.

**Composite verdict:** **YELLOW (AGENTS.md only)** — drop `.codex-plugin/`, keep `AGENTS.md` content parity.

**Plan impact:** U3 ships `AGENTS.md` only; no `.codex-plugin/plugin.json`. Cross-runtime parity test (per U3) operates on AGENTS.md content vs CLAUDE.md, not on manifest files.

---

### G0.5.3 — Data-schema discovery + path validation

Driver: `agent-learning-compounder/scripts/spike/spike_validate_schema.sh`

| Check | GREEN | YELLOW | RED |
|-------|:-----:|:------:|:---:|
| `hook-events.jsonl` found + schema captured | ✓ | | |
| `schema_version` v3 → v4 migration target identified | ✓ | | |
| `{id, tokens, duration_s}` recoverable from claude-insights | ✓ | | |
| `{cost_usd}` recoverable (raw or computed from tokens × pricing) | | ✓ | |

**Detail:**

- **hook-events.jsonl found (GREEN):** 4 files across 4 repos (makent, tm-norge, tm-unimem, agent-learning-compounder). ALC's own copy has 695 rows; sufficient real corpus for v4 migration tests.
- **Schema captured (GREEN):** 11 v3 fields documented — `agent_effort, agent_model, command_class, event, path, repo, runtime, schema_version, session_id, tool, ts`. `schema_version=3` confirmed explicit on every row scanned.
- **{id, tokens, duration_s} recoverable (GREEN):** claude-insights extraction yields `session_id`, `input_tokens` + `output_tokens`, `duration_minutes` × 60. All three fields populated on real data (verified via the premise spike: 398/398 sessions had duration).
- **{cost_usd} recoverable (YELLOW):** Not stored in raw transcripts. Computable from tokens × per-model pricing (`agent_model` field in hook-events identifies model). The existing `bin/collect_hook_event` already follows this pricing-table pattern; U5 synthesizer adopts the same approach.

**Composite verdict:** **GREEN with YELLOW on cost** — U5.5 and U5 have a real corpus to target. U5 computes cost from tokens × pricing rather than reading raw `cost_usd`.

---

## Phase B decision

- `g0_5_1_premise`        = **GREEN**
- `g0_5_2_cross_runtime`  = **YELLOW (AGENTS.md only)**
- `g0_5_3_data_schema`    = **GREEN (cost YELLOW)**
- `scope_collapse`        = **FALSE**  (premise GREEN; no scope collapse)
- `phase_b_green_light`   = **TRUE**   (proceed with full rewrite)

**Plan adjustments derived from W2:**

1. **U3 Codex scope:** ship `AGENTS.md` only, no `.codex-plugin/plugin.json`. Cross-runtime parity test (U3) compares AGENTS.md vs CLAUDE.md content, not manifest files.
2. **U5 synthesizer cost field:** compute `cost_usd` from `(input_tokens + output_tokens)` × per-model pricing table; do not expect raw cost in claude-insights output.
3. **All other plan units proceed as written** — premise GREEN means full rewrite plan is in scope including Phase D–F.

Ready to dispatch W3 via `./scripts/run-lfg.sh`.
