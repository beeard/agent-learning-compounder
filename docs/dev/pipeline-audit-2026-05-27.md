# ALC data-pipeline audit — 2026-05-27

> Trace every link from hook firing through analyst surfaces, against the real
> 1.2 MB / 4309-row corpus at
> `/home/tth/work/active/agent-learning-compounder/.agent-learning/repos/agent-learning-compounder-45819fdf8f74/`.
> Goal: list every broken link, not just the three already known.

## Summary

> 2026-05-27 status update: The original audit is retained as historical
> evidence. Runtime Wiring and State Scope were completed first; Refresh Run
> now closes the warm-loop orchestration gap by routing bootstrap/Stop-hook
> warming through `bin/refresh_run.py`, appending hook replay rows behind a
> cursor, indexing project `events.jsonl`, and keeping `refresh_learning_state`
> as the full-refresh CLI adapter. Dashboard Read Model and Proposal Lifecycle
> remain follow-up architecture work.

| Severity | Count |
|---|---|
| Showstopper (loop is silently broken end-to-end) | 4 |
| Major (whole feature inert in production) | 5 |
| Minor (cosmetic / drift / dead code) | 5 |

**Top three findings (rank-ordered):**

1. **Schema-version mismatch is the load-bearing failure.** `bin/collect_hook_event` writes `schema_version: 3` with absolute `repo` paths. `bin/event_schema.EventV4.upgrade_from` calls `_enforce_boundary` on the *raw* v3 row before stripping the `repo` field — and `_ABS_PATH_RE` matches any `/home/...` string. Every single row from production hardware is rejected at the v3→v4 seam. Confirmed: 4309/4309 rows quarantined when indexed.
2. **No production code path runs the indexer.** `index_events` is invoked only from `bin/alc_apply` / `bin/alc_apply_dispatch.py` (operator patch-apply). Not from `init_learning_system`, `alc_init`, `install.sh --bootstrap-repo`, `refresh_learning_state`, `render_unified_report`, the Stop hook, MCP tools, dashboard, or `auto_distill_session`. So `events.sqlite` only gets new rows when an operator manually applies a patch — and even then, the only rows that arrive come from `alc_apply`'s own `event_emit` calls (which write valid v4 via `event_writer`).
3. **`event_writer` writes to the wrong path.** `event_writer._state_root()` calls `resolve_state_dir()` with **no `repo=` argument**, so it returns the env-or-XDG root and writes `events.jsonl` directly under `state_root/`, **not** under `state_root/repos/<repo-id>/`. Every consumer (`StateHandle.events_jsonl`, `index_events`, `refresh_learning_state`, `alc_query`) expects the repo-scoped path. The two callers of `event_writer` (`backfill_transcripts`, `ingest_new_transcripts`) therefore deposit transcripts in a directory nothing reads.

## Pipeline map

### Ideal flow (the loop the system was advertised to close)

```
runtime hook fires
    │
    ▼ install_runtime_hooks --adapter
collect_hook_event ──writes──▶ repos/<id>/hook-events.jsonl   (schema_version=3)
    │
    ▼ replay_hook_events
events.jsonl   (schema_version=?)
    │
    ▼ index_events
events.sqlite  (schema_version=4)
    │
    ├──▶ alc_query (read API) ──▶ MCP / dashboard / alc_init session-context
    ├──▶ analyst_score / analyst_anomalies / analyst_correlations / analyst_patterns
    └──▶ recommender_render ──▶ patches/*.json

separately:
extract_sessions (transcripts) ──▶ corpus.txt ──▶ distill_learning ──▶ latest-report.md
                                              ──▶ propose_domain_rules
                                              ──▶ evaluate_gate_effectiveness (reads hook-events.jsonl)
```

### Reality

```
collect_hook_event ──writes──▶ hook-events.jsonl  ✅  (4343 rows present)
        ✗ no orchestration calls replay
        ✗ replay would emit schema_version=3 anyway (stamped by SCHEMA_VERSION = 3)

[manual] replay_hook_events ──writes──▶ events.jsonl (still v3, repo=/home/...)
                                                    │
                                                    ▼ index_events
                                            EventV4.upgrade_from
                                            └── _enforce_boundary(raw_v3) ──▶ REJECTS on "/home/" in repo
                                                    quarantined: 4309 / 4309
                                                    events.sqlite: 0 rows  ✗

event_writer (write_event/write_events_batch)
        ✗ writes to state_root/events.jsonl  — NOT state_root/repos/<id>/events.jsonl
        used by: backfill_transcripts, ingest_new_transcripts, alc_apply, eval

alc_query / dashboard / MCP read state_root/repos/<id>/events.sqlite ──▶ 0 rows ✗
analyst_score / analyst_anomalies ──▶ no signal ✗
refresh_learning_state ──▶ evaluate_gate_effectiveness ──▶ {gates: []}  (no correlation_id in any real row) ✗
```

The loop has **never closed** on this machine. The 1.3 MB `events.jsonl` next to
`hook-events.jsonl` is a one-shot manual replay, not the product of an
orchestration step. The `events.sqlite` at the repo-state path has zero rows.
A second `events.sqlite` exists at `state_root/` (also zero rows), proof that
something also tried `event_writer`-style writes there.

## Bugs

### B1 — Schema-version mismatch lethal at the v3→v4 boundary  (SHOWSTOPPER)

**What's wrong.** `collect_hook_event` emits v3 rows that contain a `repo`
field set to the absolute repo path
(`event["repo"] = str(repo.resolve())`, `bin/collect_hook_event:126`).
`event_schema.EventV4.upgrade_from` enforces the boundary check on the raw
v3 dict **before** mapping fields into the v4 envelope
(`bin/event_schema.py:361`). `_ABS_PATH_RE = re.compile(r"/home/|/Users/|...")`
matches any string containing `/home/`, so the `repo` field guarantees
rejection.

**Evidence.**

```
$ cp .../repos/<id>/events.jsonl /tmp/alc-audit-test/
$ python3 bin/index_events --state /tmp/alc-audit-test
warn.index_events_skipped offset=... reason=absolute path forbidden by boundary enforcement
... (×4309)
warn.index_events_total_skipped count=4309
$ sqlite3 /tmp/alc-audit-test/events.sqlite "SELECT COUNT(*) FROM events;"
0
```

Direct check:

```
$ python3 -c "from event_schema import EventV4; EventV4.upgrade_from(real_row)"
ValueError: absolute path forbidden by boundary enforcement
```

**Suggested fix.** Either (a) strip drop-only fields from the v3 row before
`_enforce_boundary` in `upgrade_from`, or (b) have `collect_hook_event` write
a relative / hashed `repo` token in the first place (parallel to how `path` is
normalized via `agent_dispatch.normalize_path`), or (c) drop `repo` from the
boundary scan because no downstream surface stores it. Option (b) is the
cleanest — `agent_dispatch.normalize_path` already does this for every other
path field.

---

### B2 — Writer ↔ reader filename mismatch and missing orchestration  (SHOWSTOPPER)

**What's wrong.** Two writers, two filenames, and the canonical reader expects
the second filename:

| Writer | File | Schema |
|---|---|---|
| `collect_hook_event` (every hook fire) | `repos/<id>/hook-events.jsonl` | v3 |
| `event_writer.write_event{,s_batch}` | `state_root/events.jsonl` (wrong dir) | v4 |
| `replay_hook_events` (manual only) | wherever `--output` points | v3 (stamps `SCHEMA_VERSION=3`) |

Readers:

| Reader | Expected path | Expected schema |
|---|---|---|
| `index_events` | `repos/<id>/events.jsonl` | v4 (with v3 upgrade-from) |
| `state_handle.StateHandle.events_jsonl` | `repos/<id>/events.jsonl` | n/a |
| `correlate_events` | `state_root/events.jsonl` (drift) | v4 |
| `alc_query.*` | `repos/<id>/events.sqlite` | v4 |

`collect_hook_event` was never migrated to either v4 or to writing
`events.jsonl`. Replay was supposed to bridge it, but the doc
(`reference-lib/event-schema-evolution` line 29) claims "Output is always at
the latest schema version" while the code (`replay_hook_events.replay_normalize`)
calls `collect_hook_event.normalize_event`, which stamps
`SCHEMA_VERSION = 3`. So replay's output is still v3 — and would still be
rejected by `index_events` after fixing B1, except the row's `repo` field
already doomed it.

**Evidence.**

```
$ grep -n SCHEMA_VERSION bin/collect_hook_event
35:SCHEMA_VERSION = 3
210:    event["schema_version"] = SCHEMA_VERSION

$ python3 bin/replay_hook_events --input /tmp/.../hook-events.jsonl --output /tmp/.../events.jsonl.replay
$ head -1 /tmp/.../events.jsonl.replay | python3 -c 'import sys,json; print(json.loads(sys.stdin.read())["schema_version"])'
3
```

**Suggested fix.** Pick one of two paths:

- **Bridge path:** keep `hook-events.jsonl` as the v3 collector log, add a v3→v4
  transform in `replay_hook_events` (it should *upgrade*, not just re-normalize),
  and wire `replay → index_events` into `refresh_learning_state` and
  `install.sh --bootstrap-repo`.
- **Migrate path:** rewrite `collect_hook_event` to emit v4 via `event_writer`
  directly (matches CHANGES.md's intent). This obsoletes replay and removes a
  whole class of drift.

Either way, **one** filename and **one** schema must be the contract.

---

### B3 — `event_writer` writes to the wrong directory  (SHOWSTOPPER)

**What's wrong.** `event_writer._state_root()` (line 60–61):

```
def _state_root() -> pathlib.Path:
    return resolve_state_dir().expanduser()
```

`resolve_state_dir()` with no args returns either `$AGENT_LEARNING_STATE_DIR`
or `$XDG_STATE_HOME/agent-learning` or `~/.local/state/agent-learning`. None
of those is the repo-scoped sub-path. `_events_path` then drops the file
directly at `state_root/events.jsonl`, skipping the `repos/<repo-id>/` layer
that `StateHandle.for_repo` (and every reader) navigates to.

**Evidence.**

```
$ ls /home/tth/work/active/agent-learning-compounder/.agent-learning/
config.json   events.sqlite   events.sqlite.cursor   repos
                ^^^^^^^^^^^^^ orphan, 0 rows
$ ls /home/tth/work/active/agent-learning-compounder/.agent-learning/repos/<id>/
events.sqlite     events.jsonl     hook-events.jsonl     ...
^^^^^^^^^^^^^^^^ what readers expect, 0 rows
```

Two separate `events.sqlite` instances at two different roots, both empty —
proof the system has been writing in two places and neither was the one being
read.

**Suggested fix.** `event_writer` must take a `repo` (or `StateHandle`) and use
`resolve_state_dir(repo=repo) / "repos" / repo_id(repo)` as its base. Every
caller of `write_event` / `write_events_batch` must pass repo context. Add a
regression test that writes via `event_writer` and reads via `alc_query`
against the same `StateHandle`.

---

### B4 — No orchestrator runs the pipeline end-to-end  (SHOWSTOPPER)

**What's wrong.** `replay_hook_events`, `index_events`, `correlate_events`,
`backfill_transcripts`, `ingest_new_transcripts` are all production scripts —
but nothing in production calls them. Confirmed by import + subprocess grep
across `bin/`, `scripts/`, `dashboard/`, `alc_mcp/`, `hooks/`, `install.sh`,
`commands/*.md`:

| Script | Production caller |
|---|---|
| `replay_hook_events` | **none** (only `fixtures/tests/test_replay_hook_events.py`) |
| `index_events` | `bin/alc_apply`, `bin/alc_apply_dispatch.py` only |
| `correlate_events` | **none** (only `tests/test_correlate_events.py`) |
| `backfill_transcripts` | **none** (only `tests/test_backfill_transcripts.py`) |
| `ingest_new_transcripts` | **none** (only `tests/test_ingest_new_transcripts.py`) |
| `evaluate_gate_effectiveness` | `refresh_learning_state` (but yields `{gates: []}` because no real row has `correlation_id`) |
| `propose_domain_rules` | `refresh_learning_state` (but `corpus_path = repo_state / "session-corpus.txt"` is never produced by any production caller) |

`refresh_learning_state` reads `hook-events.jsonl` directly (line 516,
`event_log = events or repo_state / "hook-events.jsonl"`), so it sees the
v3 collector output but only consumes the subset used by
`extract_skill_usage`. The `evaluate_gate_effectiveness` branch needs
`correlation_id` / `gate_loaded_ids` / `probe_decisions`, which `agent_dispatch`
never sets on real Bash/Read/Edit events.

`render_unified_report.py` (the `/alc-report` slash command):

1. `extract_sessions` ~/.claude/projects → corpus.txt
2. `distill_learning` → latest-report.md
3. `synthesize_samples` → samples.json (via the **hardcoded** `INSIGHTS_EXTRACTOR` path at `bin/synthesize_samples:24` — see B7)
4. `analyst_score` → recommendations.json (reads events.sqlite — empty)
5. `recommender_render` → patches/*.json

It does **not** run `refresh_learning_state`, `replay_hook_events`, or
`index_events`, so the analyst steps run on an empty sqlite even when the
operator triggers a report explicitly.

**Reproducer.**

```
$ python3 -c "
import sys; sys.path.insert(0,'bin')
import alc_query, state_handle, pathlib
h = state_handle.StateHandle.for_repo(pathlib.Path('/home/tth/work/active/agent-learning-compounder'))
print(alc_query.get_actor_summary(h, since='30d'))
print(alc_query.get_outcomes(h, since='30d'))
"
{'since': '30d', 'total': 0, 'by_actor_kind': []}
[]
```

After 4309 collected hook events, alc_query sees nothing.

**Suggested fix.** Add a pipeline step to (a) `install.sh --bootstrap-repo`
and (b) `refresh_learning_state` that runs `replay → index_events`. Once B1
and B2 are addressed, `index_events` itself is incremental + idempotent and
safe to call from a Stop hook.

---

### B5 — Gate-effectiveness path is structurally inert  (MAJOR)

**What's wrong.** `evaluate_gate_effectiveness.load_sessions` ignores any row
without `correlation_id` (`bin/evaluate_gate_effectiveness:71`). The real
4309-row corpus has zero rows with that field. None of the production hook
events produced by `collect_hook_event` for ordinary Bash/Read/Edit tool calls
carries `correlation_id`, `gate_loaded_ids`, or `probe_decisions` (those are
optional v2/v3 fields that need a caller to populate them). So
`evaluate_gate_effectiveness` always returns `{"gates": []}` against real data
— quietly. `refresh_learning_state._queue_retirement_candidates` then has
nothing to do, and the gate-retirement / inheritance/demote candidate stream
never fires. Same for `causal_probe` cohorts.

**Evidence.**

```
$ python3 bin/evaluate_gate_effectiveness --events real-hook-events.jsonl --output /tmp/out.json
$ cat /tmp/out.json
{"gates": []}

$ python3 -c "import json; keys=set();
[keys.update(json.loads(l).keys()) for l in open('real-hook-events.jsonl')];
print(sorted(keys))"
['agent_effort', 'agent_id', 'agent_model', 'agent_role', 'command_class',
 'event', 'path', 'repo', 'runtime', 'schema_version', 'session_id',
 'skill', 'tool', 'ts']
# no correlation_id, no gate_loaded_ids, no instructions_loaded events
```

**Suggested fix.** Either (a) generate `correlation_id` per session in
`collect_hook_event` (deterministically per `session_id` + start ts), and emit
synthetic `instructions_loaded` events from the SessionStart hook with the
gate ids currently loaded; or (b) document that the gate-effectiveness
subsystem requires explicit instrumentation that the default install does not
do, and gate the entire pipeline path behind a flag so silent zeroes do not
look like signal.

---

### B6 — `propose_domain_rules` reads a corpus nothing produces  (MAJOR)

**What's wrong.** `refresh_learning_state._queue_domain_rule_candidates` reads
`repo_state / "session-corpus.txt"` (line 563). No production caller writes
that file. `extract_sessions` writes wherever its `--output` points;
`render_unified_report` puts it at `reports/corpus.txt`; nothing puts it at
`repo_state/session-corpus.txt`. The TODO comment at lines 561–562 already
admits the wiring is forward-looking. So domain-rule mining is silently a
no-op in production. Refresh logs `"refresh: queued 0 domain_rule_candidate
row(s)"`, which is indistinguishable from "the miner ran and found nothing."

**Suggested fix.** Either delete the call (cleanest) or have refresh run
`extract_sessions --output repo_state/session-corpus.txt` itself.

---

### B7 — Hardcoded user-specific paths in `synthesize_samples`  (MAJOR)

**What's wrong.** `bin/synthesize_samples` lines 24–25:

```python
INSIGHTS_EXTRACTOR = "/home/tth/alc-agent-native-audit-export-2026-05-25T17-16-05/scripts/claude-insights-extracted.mjs"
SESSION_ADAPTER   = "/home/tth/alc-agent-native-audit-export-2026-05-25T17-16-05/scripts/alc-session-metrics-adapter.mjs"
```

These exist on Tom's machine but ship with the skill package. Anywhere else
the file isn't present `subprocess.run([..., INSIGHTS_EXTRACTOR, ...])` will
fail; `render_unified_report` would then bubble that as a `CommandError`. The
slash command `/alc-report` always invokes this step.

**Suggested fix.** Vendor the two .mjs files into `agent-learning-compounder/`
and use a path relative to the skill root (`pathlib.Path(__file__).resolve().parents[1] / "scripts" / ...`),
or make Path A pure-Python.

---

### B8 — Reference doc is wrong about replay output schema  (MAJOR)

**What's wrong.** `reference-lib/event-schema-evolution` line 29:
> "Output is always at the latest schema version."

The code stamps `SCHEMA_VERSION = 3`, the constant in `collect_hook_event:35`.
The test `test_replay_hook_events.test_v2_row_upgrades_and_keeps_supported_fields`
asserts `rows[0]["schema_version"] == 3`. So the doc says one thing and the
code does another. This is the surface that probably created the original
B1 confusion: "replay upgrades to v4 → so index_events should accept replayed
rows" — but replay's "latest" is v3, not v4. The actual v3→v4 path lives
inside `EventV4.upgrade_from` and is only invoked by `index_events`.

**Suggested fix.** Update the doc, or bump `SCHEMA_VERSION` to 4 and rewrite
`collect_hook_event.normalize_event` to emit the v4 envelope so the v3 layer
goes away.

---

### B9 — `bin/synthesize_samples` claims a wrapper but is the canonical script  (MINOR)

**What's wrong.** Docstring at `bin/synthesize_samples:4–8`:
> "This is Path A for U5: a Python wrapper around the native audit-export adapter…
> NOTE: `data-contracts.json` wiring for the `session-metrics` artifact is added
> in U6; this script intentionally does not modify it here."

The U5/U6 references are intra-team work-order language that doesn't translate
to anyone reading the production source. Drop or rewrite. Same pattern in
`reference-lib/event-schema-evolution` ("Phase 2B", "Phase 3B") and
`refresh_learning_state` ("KTD-16", "M5", "H2", "C7", "P3B-B").

---

### B10 — `state_paths` is deprecated but still in active use  (MINOR)

**What's wrong.** Every script that imports `state_paths` triggers
`DeprecationWarning` on import. The module re-exports through `StateHandle`,
so semantics are preserved, but visible-stderr churn on every invocation:

```
DeprecationWarning: state_paths is deprecated; use bin.state_handle.StateHandle
for canonical state resolution
```

Triggered by `collect_hook_event`, `refresh_learning_state`, `init_learning_system`,
`export_gates`, `ingest_new_transcripts`, `backfill_transcripts`,
`recommender_render`, and 10+ others. Migrate them; remove the shim.

---

### B11 — `auto_distill_session` is wired in `hooks/hooks.json` only via the comments in `skills/alc-core/SKILL.md`  (MINOR)

**What's wrong.** The plugin's `hooks/hooks.json` declares `SessionStart` and
`Stop` hooks that run `refresh_dashboard.py` and `render_state_surface`. Neither
of those runs `auto_distill_session`, even though `skills/alc-core/SKILL.md`
line 123 says "wire it into a Claude Code Stop hook." This is documented-but-
not-shipped behaviour. The dashboard exposes an `auto_distill` button
(`dashboard/__init__.py:186`), but no automated hook actually fires it.

---

### B12 — Two `events.sqlite.cursor` failure modes  (MINOR)

**What's wrong.** When `index_events` runs against a file where every row is
quarantined, it still advances the cursor to EOF and writes
`events.sqlite.cursor = file_size`. Future runs become no-ops even after the
boundary bug is fixed, because `cursor == file_size`. Operator must
manually `rm events.sqlite.cursor` after fixing B1 / B2 to backfill the data
they collected. Cursor reset is also not bumped on schema change.

**Suggested fix.** When `skipped > 0` and `added == 0`, do not advance the
cursor. Or store cursor + last-row-success-ts and force a rewind on schema
upgrade.

---

### B13 — `event_writer` and `correlate_events` accept the wrong state path  (MINOR drift)

`correlate_events` reads `state_root / "events.jsonl"` (line 267) — same wrong
directory as `event_writer` writes to. Symmetric drift; same fix as B3.

## Orphaned scripts (zero production callers)

Found by grepping for `from <name>` / `import <name>` / shelling out across
`bin/`, `scripts/`, `dashboard/`, `alc_mcp/`, `hooks/`, `install.sh`,
`commands/*.md` (excluding the script's own files, `__pycache__`, `tests/`, and
`fixtures/tests/`):

| Script | Status |
|---|---|
| `bin/replay_hook_events` | only tests call it (also a manual operator tool) |
| `bin/backfill_transcripts` | only tests call it |
| `bin/ingest_new_transcripts` | only tests call it |
| `bin/correlate_events` | only tests call it |
| `bin/evaluate_classifier` | only tests call it (`fixtures/tests/test_classifier_eval.py`) |
| `bin/evaluate_skill_routing` | only tests + roadmap test |
| `bin/gates_inherit` | only federation tests; production-flag (`--apply`) never invoked by orchestrator |
| `bin/gates_promote` | only federation tests; same |
| `bin/causal_probe` | only tests; refresh reads its output indirectly via `evaluate_gate_effectiveness` |
| `bin/queue_dedup` | imported only by `refresh_learning_state` (genuinely live, not orphan) |
| `bin/propose_domain_rules` | imported only by `refresh_learning_state` (live but no-op — see B6) |
| `bin/evaluate_gate_effectiveness` | imported only by `refresh_learning_state` (live but returns empty — see B5) |
| `bin/auto_distill_session` | referenced from docs + dashboard button, not from hooks.json — see B11 |

`backfill_transcripts` and `ingest_new_transcripts` are particularly damning —
they're the *only* paths in the codebase that could populate v4
`events.jsonl` for transcript-derived events, and nothing calls them. Combined
with B3 they would write to the wrong directory even if called.

## Reproductions used in this audit

```bash
# 1. boundary rejection (B1, B2)
mkdir -p /tmp/alc-audit-test
cp /home/tth/work/active/agent-learning-compounder/.agent-learning/repos/agent-learning-compounder-45819fdf8f74/events.jsonl /tmp/alc-audit-test/
cd /home/tth/work/active/agent-learning-compounder/agent-learning-compounder
python3 bin/index_events --state /tmp/alc-audit-test
# warn.index_events_total_skipped count=4309

# 2. replay emits v3, not v4 (B8)
python3 bin/replay_hook_events --input /tmp/alc-audit-test/hook-events.jsonl --output /tmp/alc-audit-test/replay.jsonl
head -1 /tmp/alc-audit-test/replay.jsonl | python3 -c 'import json,sys;print(json.loads(sys.stdin.read())["schema_version"])'
# 3

# 3. collect_hook_event writes the wrong filename + schema (B2)
mkdir -p /tmp/alc-audit-test/repo
echo '{"event":"pre_tool_use","tool":"Bash"}' | python3 bin/collect_hook_event --repo /tmp/alc-audit-test/repo --state-dir /tmp/alc-audit-test
cat /tmp/alc-audit-test/repos/repo-*/hook-events.jsonl
# {"event":"pre_tool_use","repo":"/tmp/alc-audit-test/repo","runtime":"unknown",...,"schema_version":3,...}

# 4. event_writer writes to root, not repo subdir (B3)
ls /home/tth/work/active/agent-learning-compounder/.agent-learning/events.sqlite        # 0 rows here
ls /home/tth/work/active/agent-learning-compounder/.agent-learning/repos/*/events.sqlite # 0 rows here too

# 5. read surface is dead (B4)
python3 -c "
import sys; sys.path.insert(0,'bin')
import alc_query, state_handle, pathlib
h = state_handle.StateHandle.for_repo(pathlib.Path('/home/tth/work/active/agent-learning-compounder'))
print(alc_query.get_actor_summary(h, since='30d'))
"
# {'since': '30d', 'total': 0, 'by_actor_kind': []}

# 6. gate effectiveness yields nothing (B5)
python3 bin/evaluate_gate_effectiveness --events /tmp/alc-audit-test/hook-events.jsonl --output /tmp/alc-audit-test/ge.json
cat /tmp/alc-audit-test/ge.json
# {"gates": []}
```

## Recommended fix order

The order matters — earlier fixes unblock later validation.

1. **B1 — fix the boundary check.** Either strip `repo` before `_enforce_boundary`
   in `EventV4.upgrade_from`, or make `collect_hook_event` normalize `repo` to
   `repo_id(...)` (a hashed token) instead of the raw absolute path. This
   unblocks any backfill of the 4309 rows already on disk.
2. **B2/B8 — pick one filename + one schema.** Either bump `collect_hook_event`
   to v4 via `event_writer` (preferred, lower-drift), or make
   `replay_hook_events` actually call `EventV4.upgrade_from` to produce v4 and
   make `events.jsonl` the canonical filename. Update the reference doc.
3. **B3 — make `event_writer` repo-aware.** Pass `StateHandle` or `repo` to
   every `write_event*` call site. Add a regression test that round-trips
   through `alc_query`.
4. **B4 — wire the orchestrator.** `install.sh --bootstrap-repo` should call
   `replay → index_events` after init; `refresh_learning_state` should call
   `index_events` after collecting recent events; the Stop hook in
   `hooks/hooks.json` should call `index_events` (it's incremental and fast).
5. **B12 — fix the cursor.** Don't advance cursor when all rows were
   quarantined; otherwise even after B1 is fixed the existing 4309 rows
   require manual cursor reset to backfill.
6. **B5 — populate `correlation_id` and emit `instructions_loaded`** from the
   SessionStart hook, so gate effectiveness gets real signal.
7. **B6 — write `session-corpus.txt` in `refresh_learning_state`** by calling
   `extract_sessions` itself (or wire the existing extracted corpus into the
   expected path).
8. **B7 — vendor or rewrite `synthesize_samples`** so `/alc-report` works on
   any machine.
9. **B11 — wire `auto_distill_session` from `hooks/hooks.json`** (or remove the
   dashboard button and the SKILL.md claim).
10. **B9 / B10 / B13 — cosmetic cleanup.** Drop work-order-tracker language
    from production source; finish the `state_paths → StateHandle` migration;
    fix the `correlate_events` path symmetric to B3.

After (1)–(4) the loop is end-to-end runnable on this corpus; the 4309 rows
of real telemetry will land in `events.sqlite`, `alc_query` will return rows,
the analyst scripts will produce signal, and the dashboard / MCP / session-
context will reflect actual usage. (5)–(7) bring the gate-effectiveness and
domain-rule features back from inert. (8)–(10) clean the seams.
