# Gate System Review

Multi-reviewer audit of the gate pipeline in `agent-learning-compounder/`. Five specialized reviewers (correctness, adversarial, data-integrity, reliability, testing) each examined the in-scope code independently; findings below are deduplicated and ranked by severity. Findings flagged **[CONVERGED]** were independently surfaced by two or more reviewers.

## Scope

- `bin/export_gates` — gate_id derivation and markdown rendering
- `bin/evaluate_gate_effectiveness` — correlation + causal scoring
- `bin/gates_promote` / `bin/gates_inherit` — federation lifecycle
- `bin/causal_probe` — deterministic A/B probe assignment
- `bin/refresh_learning_state` — gate-scoring orchestration sections
- Related: `bin/collect_hook_event`, `bin/queue_dedup`, `fixtures/tests/test_*.py`

## Severity rubric

- **Critical** — silent data loss or wrong learning outcomes; production-blocker on the next federated rollout
- **High** — adversarial breakage of cohort math or federation contract; design-level fix
- **Medium** — correctness issues with bounded blast radius; mechanical fix
- **Low / advisory** — code-quality and observability gaps

---

## Critical — silent data loss / wrong learning

### C1. `export_gates` deletes inherited gates on every re-run
`bin/export_gates:175-226, 263`. The exporter rebuilds `latest-approved-gates.md` from the source report only — blocks containing `derived_from:` lines (written by `gates_inherit`) are wiped on the next export. Routine re-export silently destroys federation provenance. Downstream effect: `_inherited_gates` returns `{}` and what should be `inherited_gate_demote_candidate` rows become `gate_retirement_candidate` rows, encouraging operators to retire federated gates affecting sibling repos.

**Fix:** Read the existing file before writing; preserve any block with a `derived_from:` line, append/merge new blocks from the report.

### C2. Shared registry has no content hash; gate text can be swapped silently **[CONVERGED]**
`bin/gates_inherit:41-49` validates that `record["gate_id"]` matches the filename-derived id, but never recomputes `_gate_id(record["domain"], record["gate_category"], record["gate"])`. An operator (or attacker) with write access to `~/.local/state/agent-learning/shared/gates/` can edit the `gate` field after promotion; every inheritor pulls the mutated text under the original gate_id. Effectiveness scoring keeps rolling cohorts under the original key while the runtime instruction has silently changed.

**Fix options:** (a) add `gate_text_sha256` to the registry record at promote time and verify on inherit; (b) recompute `_gate_id` from the record and refuse on mismatch. Option (b) is a one-liner using the existing `export_gates._gate_id`.

### C3. Editing gate text silently drifts `gate_id` with no alias chain
`bin/export_gates:18-22` derives `gate_id = sha256("{domain}|{category}|{gate_text.strip()}")[:12]`. A minor edit to gate text produces a new id. There is no `previous_gate_ids` alias table, so:
- Probe registrations under the old id are orphaned (probes.json still has them, scoring sees no matches)
- Federated copies in other repos retain the old text under the old id; origin diverges undetected
- Cohort statistics restart from N=0 with no carry-over

**Fix:** require an explicit `--rename old_id:new_id` flag for re-export when a gate's id would change, or maintain an alias chain in the exported markdown.

### C4. Effectiveness scoring resets when `hook-events.jsonl` rotates
`bin/collect_hook_event:330-365` rotates the live log to `<name>.<stamp>.bak` (up to 3 backups). `bin/evaluate_gate_effectiveness.load_sessions:33` reads only the live file — no glob, no merge. Effective cohort window = `DEFAULT_MAX_HOOK_EVENT_BYTES = 5 MB`. After a rotation, a gate with `n_loaded=200` can revert to `needs_review` overnight; previously confident labels flip without warning.

**Fix:** `load_sessions` accepts a list of paths, or globs `<name>*.bak` alongside the live file. Sessions are correlation_id-keyed so cross-file merge is straightforward.

### C5. v1 hook events silently bias cohort B toward "absent"
`bin/evaluate_gate_effectiveness:33-55` reads `correlation_id`, `gate_loaded_ids`, `probe_decisions` directly without a `schema_version` check. v1 events lack these fields:
- `if not cid: continue` drops v1 session_end rows entirely
- v1 sessions with `correlation_id` but no `gate_loaded_ids` land in the absent cohort for *every* gate, inflating `n_absent` and biasing delta toward failure
- Result: legitimate gates can be queued for retirement during the migration window

**Fix:** in `load_sessions`, require `row.get("schema_version", 1) >= 2` before counting toward cohorts. Or label everything `needs_review` until the operator confirms `replay_hook_events` has been run.

### C6. Truncate-in-place rewrites are not crash-atomic **[CONVERGED]**
Three locations rewrite under `LOCK_EX` with `fh.truncate()` + write loop:
- `bin/refresh_learning_state:117-169` — `_post_dedup` on `improvement-queue.jsonl`
- `bin/refresh_learning_state:30` — `write_json` for baseline/skill-map/etc.
- `bin/causal_probe:41-52` — `_locked_probes` on `probes.json`

The comment at `refresh_learning_state:128` honestly acknowledges *"not crash-atomic — a process death mid-write leaves the file truncated"*. SIGKILL/OOM-kill between truncate and write loop can wipe the improvement queue (weeks of accumulated candidates) or leave `probes.json` truncated (next `load_probes` raises `JSONDecodeError`, all probe decisions go offline).

**Fix:** write to `path.with_suffix(".tmp")`, `fsync`, `os.replace`. Mechanical change, large reliability gain.

### C7. One malformed JSONL row in `hook-events.jsonl` aborts the entire scoring pass
`bin/evaluate_gate_effectiveness:38` calls `row = json.loads(line)` with no try/except. Meanwhile `bin/refresh_learning_state:67-69` wraps the same parse in try/except and skips. **Inconsistent error policy across readers of the same file.** When `_queue_retirement_candidates` invokes effectiveness scoring (line 226), a single torn line — easily produced via the `LOCK_SH` + `PIPE_BUF` issue below (H4) — propagates as `JSONDecodeError`, which `main` doesn't catch (it only handles `ValueError`), aborting the entire refresh.

**Fix:** wrap line 38 in try/except with skip+log, matching `queue_candidate_adjustments` behavior.

---

## High — adversarial / contract failures

### H1. Cohort smearing across co-loaded gates
`bin/evaluate_gate_effectiveness:84-117`. The scoring loop iterates each gate independently but contributes the session's outcome with no per-gate weighting or attribution. A single session loading 64 gates (`MAX_GATE_LOADED_IDS`) and ending with `outcome=correction` adds +1 to *every* loaded gate's `correction_rate_loaded`. ~10 such sessions across the federation can flip every co-loaded gate to `correlated_with_failure`. The agent is effectively rewarded for retiring everything it loaded during a hard session. The docstring acknowledges the correlation-vs-causation distinction; the cohort design doesn't mitigate it.

**Fix direction:** per-(session, gate) attribution requires either a smarter signal (which gate was loaded for *this specific tool call*) or down-weighting by `1/N_loaded`. Design change.

### H2. Retirement feedback loop closes without causal gating
`bin/refresh_learning_state:228-231`. The retirement filter checks only the correlational label (`correlated_with_failure`, `no_signal`). The entire causal-probe machinery exists but **is not consulted by the action that actually disrupts production**. Cascade: retire overlapping gate A → gate B's "absent" cohort changes composition (sessions that used to load both now load only A) → B's delta drops → B queued for retirement → repeat. The retirement pass produces its own justification.

**Fix:** require `causal_signal == "correlated_with_failure"` (or a min-N causal probe with consistent sign) before queueing retirement. Demotion of inherited gates likewise.

### H3. Probe assignment is solvable client-side
`bin/causal_probe:68-71` — `int(sha256(f"{session_id}|{gate_id}")[:8], 16) % 10000 < int(rate * 10000)`. `session_id` is derived from `bin/collect_hook_event:73-77, 150` which only rejects UUID format; arbitrary slugs pass through. An agent that wants to skip a probed gate can rejection-sample session_id candidates client-side until the hash lands in the skip bucket. At `rate=0.1`, expected ~10 tries; at `rate=0.5`, ~2 tries. With `PROBE_COHORT_MIN_N=5`, one bad actor can flip `causal_signal` for arbitrary gates.

**Fix direction:** mix in a server-side secret salt that the agent cannot observe (breaks determinism guarantee in tests — accept this), or assign probe decisions server-side at session start and emit them as immutable hook events.

### H4. Hook events write under `LOCK_SH` while lines routinely exceed `PIPE_BUF`
`bin/collect_hook_event:417-423`. Append uses `O_APPEND` + `LOCK_SH` — atomic only up to `PIPE_BUF` (4096 on Linux). `MAX_GATE_LOADED_IDS * MAX_GATE_LOADED_ID_LEN = 64 × 64 = 4096B` for `gate_loaded_ids` alone; add `probe_decisions` of 64 dicts and JSON overhead and most v2 hook events exceed 4096 bytes. Concurrent appenders can interleave bytes → readers see torn JSON lines → combined with C7, full scoring outage.

**Fix:** either (a) switch the writer to `LOCK_EX` for the duration of the write (and `LOCK_SH` for readers), or (b) cap the serialized size below `PIPE_BUF`. Option (a) is simpler.

### H5. `gates_promote` has no concurrency control **[CONVERGED]**
`bin/gates_promote:140`. `out_path.write_text(json.dumps(record) + "\n", ...)` — not flock-guarded, not tmp+rename. Two operators promoting the same gate_id (e.g., from different origin repos that independently discovered the same gate text) race; last writer wins silently. Concurrent reader (`gates_inherit:141 record_path.read_text` → `json.loads`) can observe a truncated file and surface as a misleading "invalid shared gate record" error. Asymmetric with `gates_inherit` which is properly locked.

**Fix:** write to `<gate_id>.json.tmp`, `fsync`, `os.replace`. Also adopt the conflict-detection pattern from `gates_inherit` so concurrent promoters from different origins surface as `EXIT_CONFLICT` instead of silent overwrite.

### H6. Promote/inherit validation asymmetry permits federation DoS
`bin/gates_promote:72-87` does not run the equivalent of `gates_inherit.validate_record`. Empty `--origin-repo`, newlines in `--origin-repo`, or other malformed inputs reach the shared registry. Every subsequent `gates_inherit` fails at `validate_record:41-49`. One bad promote silently bricks future inheritance until an operator hand-edits the JSON.

**Fix:** call `validate_record`-equivalent checks at promote time before writing.

---

## Medium — bounded blast radius

### M1. No repo-level lock — concurrent refreshes can produce mutually inconsistent state files
`bin/refresh_learning_state:348-471`. Per-file `LOCK_EX` guards individual writes but releases between them. Two concurrent refreshes can produce a baseline.json from run A interleaved with a skill-map.json from run B. `write_json` uses `path.write_text(...)` (no tmp+rename), making each individual file safe against torn reads but the *set* inconsistent.

**Fix:** acquire `LOCK_EX` on `{repo_state}/.refresh.lock` at the top of `refresh()` and release at the end.

### M2. `_inherited_gates` silently flips retire-vs-demote on malformed blocks
`bin/refresh_learning_state:172-198`. Requires both `gate_id` and `derived_from` to mark a gate inherited. A malformed block (missing `derived_from` due to partial write, CRLF, missing trailing newline) is silently skipped, dropping the gate from `inherited_map`. The retirement filter then queues a `gate_retirement_candidate` for what is actually a federated gate. Operator acting on the queue retires a gate that affects sibling repos.

**Fix:** fail closed — treat any block with `gate_id` but no `derived_from` as inherited-unknown-origin (route through demote path), or raise loudly.

### M3. `gates_inherit` parser breaks on CRLF and missing-leading-newline **[CONVERGED]**
`bin/gates_inherit:57-77`. `text.split("\n- domain:")` requires LF only, and requires a newline *before* the first `- domain:`. A file written or edited through a CRLF editor, or one starting directly with `- domain:`, splits incorrectly:
- `_existing_derived_from` returns `None` → idempotency claim breaks; rerun appends duplicate blocks
- `gate_already_present` uses a different MULTILINE regex that *does* handle CRLF, so one helper reports the gate present while the other reports it absent

**Fix:** use `re.split(r"(?m)^- domain:\s*", text)` (a pattern used elsewhere in the codebase, e.g. `export_gates:125`).

### M4. `_queue_retirement_candidates` doesn't dedup by gate_id
`bin/refresh_learning_state:240-289`. Row id includes `now_unix` and a within-batch counter; two refreshes in different seconds produce different ids for the same gate. Downstream relies on trigram dedup of the `text` field, which embeds `delta={c['delta']:.3f}` — as delta drifts across refreshes, trigram-Dice can drop below the 0.80 threshold and accumulate one row per drift step.

**Fix:** match the pattern used by `queue_candidate_adjustments` — stable id `sha256(gate_id|kind)[:16]`, check `seen` membership before appending.

### M5. Retirement threshold asymmetry
`bin/refresh_learning_state:226-231` filters on `n_loaded >= min_n_retire` (default 20) but accepts any non-needs_review label. Labels require both cohorts `>= min_n=10` inside `evaluate_gates`, so a gate can be queued for retirement with `n_loaded=20, n_absent=10` — half the strictness on the comparison side. Docstring implies symmetric stricter thresholds.

**Fix:** add `row["n_absent"] >= min_n_retire` to the filter, or document the asymmetry.

### M6. `gate_id` derivation has trivial collision and Unicode normalization hazards
`bin/export_gates:18-22`. Hash input is `f"{domain}|{category}|{gate_text.strip()}"`. The `|` separator is not escaped: `domain="a|b"` collides with `category="b|c"`. `.strip()` doesn't apply Unicode normalization — `Café` (NFC) and `Café` (NFD) produce different ids while rendering identically. Operator-trivial collisions silently merge gates; Unicode-normalization splits one logical gate into N tracked ids — none reach min_n.

**Fix:** use a non-ambiguous separator (e.g., `\0` or a length-prefixed encoding) and call `unicodedata.normalize("NFC", ...)` before hashing. Note this is itself a `gate_id` change — would need to be coordinated with C3.

---

## Low / advisory

- **A1.** `gates_inherit` conflict error reports `from ''` when the existing row is a local (non-inherited) gate. Misleading diagnostic. (`bin/gates_inherit:76, 167-184`)
- **A2.** `gates_promote` doesn't verify the source markdown's `gate_id` matches `_gate_id(domain, category, gate)`. A hand-edited registry can promote arbitrary text under any id. (`bin/gates_promote:63-69`)
- **A3.** `causal_probe.decide` doesn't revalidate `rate ∈ [0, 1]` from probes.json — a hand-edited file with `rate=2.0` makes every session skip; `rate=-0.1` makes every session load. (`bin/causal_probe:68-71, 91-98`)
- **A4.** Probe `rate=0.0` and `rate=1.0` produce empty cohorts → `causal_signal == "needs_review"` forever; misuse near boundaries (e.g., `rate=0.99`) starves the probe-skip cohort, silently disabling causal analysis with no warning. (`bin/causal_probe:74-81`)
- **A5.** `_post_dedup`'s second pass only runs when this run queued new retirement/demote/domain rows — stale duplicates from prior runs survive on dedup-skipped runs. (`bin/refresh_learning_state:426-427`)
- **A6.** No audit trail when a gate's effectiveness label flips between refreshes. The full result dict is computed but never persisted; only the queue row records "label = correlated_with_failure" without the prior state. (`bin/refresh_learning_state:201-289, 391-396`)
- **A7.** `fcntl.flock` is used everywhere with no timeout. A wedged process holding the lock hangs every subsequent refresh indefinitely. NFS semantics for `flock` are also unreliable — should be documented as local-FS only.
- **A8.** `render_registry`'s `max_domains` truncation silently drops probe metadata for gates of capped-out domains. Probe assignment continues, but inheritors pull a registry that omits it. (`bin/export_gates:175-226`)
- **A9.** `evaluate_gate_effectiveness` reads the entire event log into a defaultdict — no streaming aggregation. Memory pressure failure mode on long-lived repos.

---

## Cross-cutting risk: correlational and causal signals share data

`bin/evaluate_gate_effectiveness:42-55, 85-100`. Probe-skipped sessions are counted in both:
- the **absent** cohort (for correlational scoring), because the gate is not in `s["gates"]`
- the **probe_skipped** cohort (for causal scoring)

The two signals are not statistically independent when probes are active. Operators reading correlational and causal labels as two independent signals are deceived — at `rate=0.5`, half the absent cohort is probe-skipped, so the correlational delta is contaminated by deliberate non-loads, no longer estimating the natural counterfactual.

**Implication:** "both labels agree" carries less evidence than it appears to. Either define the contract (probe-skipped sessions excluded from absent cohort) or document the overlap clearly.

---

## Testing gaps — by blast radius of the bug they would not catch

1. **No frozen-value test for `_gate_id`.** Federation contract is unanchored. A one-character change to the hash recipe silently invalidates every cross-repo gate id; existing "determinism" tests pass under the new recipe because both legs use it.
   ```python
   assert _gate_id("cloudflare", "docs-check", "Re-read current Cloudflare docs.") == "<known-hex>"
   ```
2. **No frozen-value test for `causal_probe.decide`.** Same federation argument. A change to (a) input order to `f"{gate_id}|{session_id}"`, (b) slice `[:8]→[:16]`, or (c) modulus base would still be deterministic and ~rate-correct, but every in-flight cohort assignment flips.
3. **No threshold boundary tests.** delta = exactly 0.20, exactly −0.10, dead-band → `no_signal` label has zero direct coverage.
4. **PROBE_COHORT_MIN_N boundary (N=4 vs N=5) and `causal_correlated_with_failure` / `causal_no_signal` labels untested.**
5. **Queue row schemas under-asserted.** `id` format, `text` template, `ts`, `evidence.delta`, `evidence.n_absent` never checked for `gate_retirement_candidate` or `inherited_gate_demote_candidate` rows.
6. **No v1 / mixed-schema fixtures** for `evaluate_gate_effectiveness.load_sessions`.
7. **No CRLF / no-leading-newline fixtures** for `gates_inherit` idempotency claims.
8. **`promoted_at` format not pinned.** Drift from `strftime("%Y-%m-%dT%H:%M:%SZ")` to `.isoformat()` would break all future conflict detection in `_existing_derived_from`.
9. **Exit-code contracts only asserted as non-zero**, not specific values (`gates_promote` 3 vs 4; `gates_inherit` 2 vs `EXIT_CONFLICT=3`).
10. **Empty-cohort and `outcome=None` paths in `evaluate_gate_effectiveness` untested.**
11. **`_post_dedup` correctness on heterogeneous candidate kinds untested.** Risk: two `gate_retirement_candidate` rows for distinct gate_ids collapsed by trigram similarity → silent candidate loss.
12. **No concurrent-register test for `causal_probe._locked_probes`** (parallel to `gates_inherit`'s conflict tests).
13. **No retirement-feedback-loop test.** Seed events with overlapping gates A and B, run two refresh cycles, assert retiring A does not make B silently look worse.

---

## Recommended fix order

In dependency order, smallest-mechanical-fix-with-biggest-payoff first:

1. **C1** (export_gates preserves inherited blocks) — active data loss, reproducible, ~50 LOC change.
2. **C7 + H4** (try/except around `load_sessions:38` JSON parse + writer `LOCK_EX`) — removes the silent-outage path.
3. **C6** (tmp+rename across `_post_dedup`, `_locked_probes`, `write_json`) — mechanical, large reliability win.
4. **C2** (recompute `_gate_id` on inherit, or add `gate_text_sha256`) — closes federation poisoning.
5. **C4** (effectiveness scoring reads rotated `.bak` files) — restores cohort window.
6. **C5** (`schema_version` check in `load_sessions`) — defends migration window.
7. **M1** (repo-level lock for refresh) — closes cross-file inconsistency.
8. **M2 + M3** (parser robustness) — closes silent retire-vs-demote flip.
9. **Add frozen-value tests for `_gate_id` and `causal_probe.decide`** — ~30-line PR that locks down both federation contracts permanently.
10. **C3** (gate_id alias chain) — design change; coordinate with M6 if changing the hash recipe.

The adversarial findings **H1** (cohort smearing) and **H2** (retirement without causal gating) and **H3** (probe gameability) are design-level — they require deciding what guarantees the system is making before fixing code. Worth a written spec amendment, not a code change in isolation.

---

## Methodology

Five reviewers spawned in parallel via `Agent` with specialized subagent types:

- `compound-engineering:ce-correctness-reviewer` — logic errors, edge cases, intent-vs-implementation
- `compound-engineering:ce-adversarial-reviewer` — actively constructed failure scenarios
- `compound-engineering:ce-data-integrity-guardian` — append-only invariants, locking, schema migration
- `compound-engineering:ce-reliability-reviewer` — error handling, partial failure, observability
- `compound-engineering:ce-testing-reviewer` — coverage gaps, brittleness, contract pinning

Each reviewer received the same scope but worked independently. Findings were merged here with explicit attribution where two or more reviewers independently surfaced the same issue (**[CONVERGED]** tag).
