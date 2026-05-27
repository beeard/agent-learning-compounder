# PR 4 — Unblock the project-scope event pipeline

> **For the next Claude session.** Self-contained brief. Drop the contents
> of this file into the next session and start.

## Where we are

Commits on `master` (no push yet):

| Commit | What |
|---|---|
| `c221cf2` | `install.sh` auto-builds the React dashboard bundle when pnpm is present |
| `014fe7a` | PR 3 — dashboard surfaces user + project scopes |
| `986ccd0` | PR 2 — scope-aware read API + MCP catalog + `next_action` signal |
| `c24d01b` | PR 1 — rename `personal` → `user`; add `StateHandle.for_user`/`for_project` |

What PR 3 made visible: the React SPA has a "This project" tab on
`ScopedGatesPanel`. It's empty — 0 project-scope gates — because the
project-scope `events.sqlite` is empty. **PR 4 makes it possible to
populate `events.sqlite`; PR 5 wires the population step into install
so it happens automatically.**

Live state on this repo (per `docs/dev/pipeline-audit-2026-05-27.md`):

```
.agent-learning/repos/<id>/
  hook-events.jsonl       4365 rows  ← collect_hook_event writes here (correct path)
  events.jsonl            4309 rows  ← one manual replay, never re-run
  events.sqlite           0 events   ← indexer rejects every row at the v3→v4 boundary
  events.sqlite.cursor    1266024    ← already at EOF; B12 means re-runs are no-ops
```

The loop has **never closed** on this machine. PR 4 unblocks it.

## PR 4 goal and definition of done

**Goal.** Make `index_events` capable of consuming the rows that
`collect_hook_event` (and `event_writer`) produce, and have
`refresh_learning_state` run it. That's all.

**Done when:**

1. `python3 bin/index_events --state <repo>/.agent-learning/repos/<id>/`
   against the current 4,309-row `events.jsonl` lands a non-trivial
   number of rows in `events.sqlite` (≥ 4,000 — the exact number depends
   on whether any rows are genuinely malformed beyond the boundary check).
2. `alc_query.get_actor_summary(state, since='30d')` returns
   `total > 0` on this repo.
3. A new regression test round-trips a single event:
   `event_writer.write_event(..., repo=R)` → `index_events --state ...` →
   `alc_query.get_actor_summary(state)` returns that event.
4. `refresh_learning_state` calls `index_events` before
   `extract_skill_usage` so subsequent runs keep the sqlite warm without
   operator action.

**Out of scope for PR 4:**

- Wiring `index_events` into `install.sh --bootstrap-repo` or
  `hooks/hooks.json` — that is PR 5's story.
- B5 (correlation_id), B6 (domain-rules corpus), B7 (vendored .mjs
  paths), B8 (replay docs), B9–B11, B13.
- Migrating `state_paths` → `StateHandle` (B10 sweep).
- A backfill orchestrator script (`bin/alc_bootstrap_pipeline`, per
  bootstrap audit §4 option B) — also PR 5.

## The three bugs PR 4 fixes

### B1 — schema boundary check rejects every collected row (SHOWSTOPPER)

- `bin/collect_hook_event:126` writes `event["repo"] = str(repo.resolve())`
  → the row carries `"/home/..."`.
- `bin/event_schema.py:361` calls `_enforce_boundary(v3_row)` **before**
  the v3→v4 field mapping strips `repo`.
- `_ABS_PATH_RE = re.compile(r"/home/|/Users/|C:\\Users\\")`
  (`event_schema.py:32`) matches the `repo` field → ValueError.
- Result: 4,309 / 4,309 rows quarantined when `index_events` runs.

**Side benefit:** Fixing B1 by hashing `repo` in `collect_hook_event`
also softens B2 (replay-emits-v3 drift). Once v3 rows have a hashed
`repo` field, `EventV4.upgrade_from` accepts them and `replay_hook_events`
becomes a backwards-compat tool rather than a load-bearing bridge.

### B3 — `event_writer` writes to the wrong directory (SHOWSTOPPER)

- `bin/event_writer.py:60-61`:
  ```python
  def _state_root() -> pathlib.Path:
      return resolve_state_dir().expanduser()
  ```
- `resolve_state_dir()` with no `repo=` returns the env-or-XDG root.
  Drops `events.jsonl` at `<state_root>/events.jsonl`, **not** at
  `<state_root>/repos/<repo-id>/events.jsonl` where every reader looks.
- Proof on this machine: two empty `events.sqlite` files at two
  different roots (`.agent-learning/events.sqlite` and
  `.agent-learning/repos/<id>/events.sqlite`).
- Callers affected: `backfill_transcripts`, `ingest_new_transcripts`,
  `alc_apply`, `alc_apply_dispatch.py`, `alc_propose` (calls
  `event_writer.write_event` from `report_outcome` /
  `report_agent_event`), `eval`.

**Note on backfill scope.** B3 does **not** block the 4,309-row
backfill — those rows came from `collect_hook_event` (correct path) and
a one-shot manual `replay_hook_events --output …` invocation that also
landed in the right directory. B3 affects *future* writes from the
callers above. Fixing it now prevents future drift and unblocks the
`backfill_transcripts` / `ingest_new_transcripts` paths that PR 5 will
start exercising.

### B12 — `events.sqlite.cursor` advances even on all-quarantined runs (MINOR but blocks B1 backfill)

- `bin/index_events:232` always calls `_write_cursor(cursor_path, cursor)`
  at end of run, regardless of whether anything was inserted.
- When every row quarantines, the cursor still advances to EOF. Next
  run sees `cursor == file_size` → no-op. **The existing
  `events.sqlite.cursor = 1266024` on this repo is a casualty of this
  bug** — an earlier indexer run quarantined every row, advanced the
  cursor to EOF, and from then on backfill was impossible without
  `rm events.sqlite.cursor`.

**Fix:** if `added == 0` and `skipped > 0`, do not advance the cursor.

### B4 — the indexer needs a production caller (SHOWSTOPPER, scoped)

Confirmed via subprocess/import grep across `bin/`, `scripts/`,
`dashboard/`, `alc_mcp/`, `hooks/`, `install.sh`, `commands/*.md`:

| Script | Production caller |
|---|---|
| `replay_hook_events` | **none** (only fixtures/tests) |
| `index_events` | `alc_apply`, `alc_apply_dispatch.py` only |
| `correlate_events` | **none** |
| `backfill_transcripts` | **none** |
| `ingest_new_transcripts` | **none** |

PR 4 fixes the narrow subset of B4 it owns: **call `index_events` from
`refresh_learning_state` so `/alc-report` and scheduled refresh trigger
ingestion.** Install-time and Stop-hook wiring is PR 5.

## Five-PR plan (reference)

1. ✓ PR 1 — rename `personal` → `user` (shim, no behavior change)
2. ✓ PR 2 — scope-aware read APIs + MCP catalog
3. ✓ PR 3 — dashboard shows both scopes
4. **← you are here** — fix B1 + B3 + B12; wire `index_events` into `refresh_learning_state`
5. Wire `index_events` into `install.sh --bootstrap-repo` and the Stop hook so installs are warm; document the operator backfill command for upgrading consumers.

## Files PR 4 touches

| File | Change |
|---|---|
| `agent-learning-compounder/bin/collect_hook_event` | Lines 35, 126, 210 — replace raw `repo.resolve()` with a hashed token (`state_paths.repo_id(repo)` or equivalent). Wire-format change for `hook-events.jsonl` only; readers don't currently use the absolute path. Consider bumping `SCHEMA_VERSION` to 4 here if cheap (B8 sub-fix). |
| `agent-learning-compounder/bin/event_schema.py` | Optional belt-and-braces: line 361, reorder so v3→v4 field mapping runs *before* `_enforce_boundary`. Defensive — keeps the source fix from being the only safety. |
| `agent-learning-compounder/bin/event_writer.py` | Lines 60-61, 219, 231 — `_state_root` takes a `repo` (or `StateHandle`); thread it through `write_event` / `write_events_batch`. Keep the no-arg signature working with a deprecation path (or accept that all current callers can pass `repo`). |
| `agent-learning-compounder/bin/index_events` | Line 232 — guard `_write_cursor` so the cursor does not advance when `added == 0 and skipped > 0`. |
| `agent-learning-compounder/bin/refresh_learning_state` | Add an `index_events` invocation early in the run, before `extract_skill_usage`, so refresh consumes a populated sqlite. |
| `agent-learning-compounder/bin/backfill_transcripts` + `bin/ingest_new_transcripts` | Update `write_event` / `write_events_batch` call sites to pass `repo`. |
| `agent-learning-compounder/bin/alc_apply` + `bin/alc_apply_dispatch.py` + `bin/alc_propose.py` + `bin/eval*` | Same — every `event_writer` caller threads `repo`. |
| `agent-learning-compounder/fixtures/tests/` or `tests/` | New regression: `event_writer.write_event(..., repo=R)` → `index_events` → `alc_query.get_actor_summary` returns the event. This is the gate that proves B1+B3 are both fixed. |

## Design decisions the next session needs to make

### Decision 1 — B1 fix mode

**Option A — Hash the `repo` field at the source.** In
`collect_hook_event`, set `event["repo"] = state_paths.repo_id(repo)`
(same hashed token every other path field gets via
`agent_dispatch.normalize_path`). Narrow wire-format change for
`hook-events.jsonl`; downstream readers don't currently use the
absolute path. **Audit's recommendation. Recommended here too.**

**Option B — Reorder `EventV4.upgrade_from`.** Map v3 fields into the
v4 envelope first (which drops `repo`), then run `_enforce_boundary`
on the cleaned dict. No wire-format change; surface-level fix only.
Risk: the boundary check is defense-in-depth — moving it doesn't
prevent some *other* v3 row from carrying an absolute path in a
non-`repo` field.

**Option C — Both.** Hash at source (A) + reorder at the seam (B).
Belt-and-braces; two small changes instead of one. Probably the right
call for a production fix that needs to backfill rows already on disk.

### Decision 2 — `event_writer` signature

**Option α — Add `repo` as a required keyword arg.** Cleanest signature;
every existing caller must thread `repo` through. Touches more files in
one PR.

**Option β — Add `repo` as optional, deprecate the no-arg path.** Old
callers keep working (write to the wrong dir as before, with a
DeprecationWarning); new callers pass `repo`. Lower-risk landing; the
shim removal is a follow-up. Matches how PR 1 handled the
`personal → user` rename.

Recommendation: **β.** Keeps PR 4 narrowly focused on unblocking the
loop; the audit's "every caller threads repo" cleanup can ship as a
separate sweep without holding up the four-bug fix.

### Decision 3 — Backfill the existing 4,309 rows

The fixes themselves don't touch the rows already on disk. The
operator (and the test for this repo) needs to:

1. `rm <repo>/.agent-learning/repos/<id>/events.sqlite.cursor` — the
   pre-fix cursor is at EOF (B12 casualty).
2. `python3 bin/index_events --state <repo>/.agent-learning/repos/<id>/` —
   the indexer reads from offset 0 and produces ~4,309 rows.

Surface this in the commit message and/or a CHANGES entry. PR 5 will
wire it into install; for PR 4, document the manual one-liner.

## Concrete starting steps

```bash
cd /home/tth/work/active/agent-learning-compounder/agent-learning-compounder

# 1. Reproduce the lethal boundary check.
python3 -c "
import sys; sys.path.insert(0,'bin')
import json
from event_schema import EventV4
with open('../.agent-learning/repos/agent-learning-compounder-45819fdf8f74/events.jsonl') as f:
    row = json.loads(f.readline())
EventV4.upgrade_from(row)  # expect ValueError: absolute path forbidden
"

# 2. Spot every absolute-path field in a real row.
python3 -c "
import sys; sys.path.insert(0,'bin')
import json
with open('../.agent-learning/repos/agent-learning-compounder-45819fdf8f74/events.jsonl') as f:
    row = json.loads(f.readline())
for k, v in row.items():
    if isinstance(v, str) and ('/home' in v or '/Users' in v):
        print(f'  {k} = {v!r}')
"

# 3. Find every event_writer caller (to thread repo through).
grep -rn 'write_event(\|write_events_batch(' \
    agent-learning-compounder/bin agent-learning-compounder/alc_mcp \
    agent-learning-compounder/skills agent-learning-compounder/dashboard \
    agent-learning-compounder/hooks 2>/dev/null \
    | grep -v event_writer.py

# 4. After fixes, exercise the backfill on this repo.
rm -f ../.agent-learning/repos/agent-learning-compounder-45819fdf8f74/events.sqlite.cursor
python3 bin/index_events \
    --state ../.agent-learning/repos/agent-learning-compounder-45819fdf8f74/
sqlite3 ../.agent-learning/repos/agent-learning-compounder-45819fdf8f74/events.sqlite \
    'SELECT COUNT(*) FROM events;'
# Expect ≥ 4,000 (4,309 minus any genuinely malformed rows).
```

## Tests to run after PR 4

```bash
cd agent-learning-compounder

python3 -m unittest discover -s fixtures/tests   # must stay green
python3 -m unittest discover -s tests            # must stay green
python3 scripts/run_pressure_tests.py            # 4 pressure gates

# Pipeline-adjacent suites (high signal for PR 4):
python3 -m unittest \
    fixtures.tests.test_replay_hook_events \
    tests.test_correlate_events \
    tests.test_backfill_transcripts \
    tests.test_ingest_new_transcripts \
    2>&1 | tail
```

New regression to add — the simplest end-to-end gate that proves
B1+B3 are both fixed:

```python
# event_writer.write_event(payload, repo=R)
# index_events --state <state-for-R>
# alc_query.get_actor_summary(state) → contains the written event
```

## Live verification on this repo

After applying the fixes, running the backfill, and pointing the
dashboard at the project state:

```bash
cd agent-learning-compounder
python3 -c "
import sys, pathlib
sys.path.insert(0, 'bin')
import alc_query
from state_handle import StateHandle
# StateHandle.for_repo takes the repo root (the outer dir that contains
# .agent-learning/, NOT the inner skill dir).
state = StateHandle.for_repo(pathlib.Path.cwd().parent)
print('actor_summary:', alc_query.get_actor_summary(state, since='30d'))
print('apply_log rows:', len(alc_query.get_apply_log(state)))
"
# expect actor_summary.total > 0
```

The React SPA's "This project" tab on `ScopedGatesPanel` will only
populate once the analyst chain produces project-scope gates from the
populated sqlite. PR 4 builds the *plumbing* (sqlite populates,
`alc_query` returns rows). Whether real gates appear depends on the
analyst chain (out of PR 4 scope).

## Constraints (don't violate)

- The boundary check is defense-in-depth against leaked absolute paths
  in telemetry. **Don't weaken the check itself.** Fix the source of
  the bad input (B1 option A) and/or strip drop-only fields at the seam
  (option B).
- `hook-events.jsonl` is append-only. Don't rewrite it — fix the
  indexer / schema seam to handle the rows it contains.
- `events.sqlite` schema is v4. Keep it v4. PR 4 changes how v3 rows
  *flow into* v4; it does not change v4's shape.
- Keep `index_events` incremental + idempotent. Operators may call it
  many times.
- Don't introduce a new schema version. If you bump `collect_hook_event`'s
  `SCHEMA_VERSION` to 4 (B8 sub-fix), match the v4 envelope `event_writer`
  already produces — don't define a new variant.

## When you're done

Commit message convention:

```
fix(pipeline): unblock project-scope event ingestion (PR 4)
```

(Or `fix(events)` — pick whichever scope the rollout series settles on.)

Update memory:

- `scope-rename-rollout.md`: mark PR 4 shipped; PR 5 stays as install-
  time pipeline wiring (`install.sh` + `hooks/hooks.json` + operator
  backfill docs).
- Note in CHANGES that operators upgrading need to
  `rm events.sqlite.cursor` + `python3 bin/index_events --state ...`
  once before the auto-refresh path kicks in.

Push when the user says push.

## References

- `docs/dev/pipeline-audit-2026-05-27.md` — full bug taxonomy (B1–B13)
  with line-number-precise evidence and reproducers.
- `docs/dev/read-surface-audit-2026-05-27.md` — what's empty *because*
  of these bugs; useful for confirming which `alc_query` reads come
  back to life after PR 4.
- `docs/dev/bootstrap-wiring-audit-2026-05-27.md` — install-time wiring
  context. PR 5 territory.
- `docs/dev/dashboard-audit-2026-05-27.md` — confirms PR 3's "This
  project" tab will only meaningfully populate once PR 4 (and the
  analyst chain) run.
