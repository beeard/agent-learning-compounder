# PR 5 — Close the warm-loop seam at install time and on every Stop

> **For the next Claude session.** Self-contained brief. Drop the contents
> of this file into the next session and start.

## Where we are

Commits on `master` (not pushed):

| Commit | What |
|---|---|
| `ed49da4` | PR 4 review fix — revert `SCHEMA_VERSION` to 3 (flat-row mismatch), thread `repo=` through 4 more event_writer callers, fix the 4 exec_sandbox test fixtures |
| `0a95dc4` | PR 4 — fix project-scope event ingestion (B1+B3+B12+B4-narrow) |
| `c221cf2` | `install.sh` auto-builds the React dashboard bundle when pnpm is present |
| `014fe7a` | PR 3 — dashboard surfaces user + project scopes |
| `986ccd0` | PR 2 — scope-aware read API + MCP catalog + `next_action` signal |
| `c24d01b` | PR 1 — rename `personal` → `user`; add `StateHandle.for_user`/`for_project` |

What PR 4 fixed:

- New hook events stamped schema=3 with hashed `repo` now flow through
  `EventV4.upgrade_from` into `events.sqlite`.
- `event_writer.write_event(..., repo=R)` lands writes in
  `<state_root>/repos/<repo-id>/events.jsonl` — the path every reader uses.
- `index_events` no longer advances its cursor when every row quarantines.
- `refresh_learning_state` drains `events.jsonl` → `events.sqlite` before
  `extract_skill_usage` runs.

What PR 4 left behind: **the bridge from `hook-events.jsonl` to
`events.jsonl` is still manual.** Hook activity goes to
`hook-events.jsonl` (via `collect_hook_event`); `index_events` reads
`events.jsonl`. The one-time pipe is `bin/replay_hook_events`, which on
this repo has been run exactly once (the 4,309-row event backfill that
PR 4 finally indexed). For new installs, `hook-events.jsonl` fills as
sessions run but never reaches `events.sqlite` until an operator runs
`replay_hook_events --input ... --output ...`. That's the gap PR 5
closes.

## PR 5 goal and definition of done

**Goal.** Wire the warm-loop seam — `replay_hook_events` →
`index_events` — into the install bootstrap and the Stop hook so a fresh
install lands with a populated `events.sqlite` and stays populated
without operator action. Document the manual one-liner for operators
upgrading from pre-PR4.

**Done when:**

1. `install.sh --bootstrap-repo <repo>` runs `replay_hook_events`
   (if `hook-events.jsonl` has rows the operator hadn't already
   replayed) then `index_events` against the per-repo state, **as
   part of the bootstrap**, after `alc_init`.
2. The Claude Stop hook (`hooks/hooks.json`) and Codex equivalent
   (`install_runtime_hooks.py` emits) run `replay_hook_events` then
   `index_events` so `events.sqlite` stays current with whatever the
   session's `collect_hook_event` writes lay down.
3. A new regression test exercises **both paths in one shot** (the
   reviewer's explicit ask after PR 4):
   - A legacy schema-3 flat row already on disk (carrying `repo`
     as an absolute path).
   - A freshly-emitted `collect_hook_event.normalize_event(...)` row.
   Both flow through the bootstrap chain into `events.sqlite`;
   `alc_query.get_actor_summary` reflects both.
4. `CHANGES.md` (or a new `docs/dev/operator-upgrade-pr4.md`) carries
   the manual one-liner for consumers upgrading from a pre-PR4
   install:
   ```
   rm <repo>/.agent-learning/repos/<id>/events.sqlite.cursor
   python3 .../bin/replay_hook_events \
       --input <repo>/.agent-learning/repos/<id>/hook-events.jsonl \
       --output <repo>/.agent-learning/repos/<id>/events.jsonl \
       --skip-malformed
   python3 .../bin/index_events \
       --state <repo>/.agent-learning/repos/<id>/
   ```

**Out of scope for PR 5:**

- The bigger transcript backfill question (`backfill_transcripts`,
  `extract_sessions` from `~/.claude/projects` / `~/.codex/sessions`).
  The bootstrap audit § 5 recommends a bounded inline backfill; that's
  a scope-expanding decision and belongs in its own PR. PR 5 only
  closes the hook→sqlite seam.
- B5 (correlation_id), B6 (domain-rules corpus), B7 (vendored .mjs
  paths), B8 (replay docs beyond the operator one-liner), B9–B11, B13.
- The `state_paths` → `StateHandle` deprecation sweep (B10).
- Making `replay_hook_events` incremental (today it's one-shot
  input→output). Per-session Stop hook runs are small enough that
  full-replay-then-index per Stop is fine. See "Decision 3" below if
  you want to revisit.

## Files PR 5 touches

| File | Change |
|---|---|
| `install.sh` | Add the replay + index calls to the `--bootstrap-repo` branch, after `alc_init` (around line 415). Behind `--no-first-run-index` opt-out flag (env: `ALC_FIRST_RUN_INDEX=0`). |
| `agent-learning-compounder/hooks/hooks.json` | Add `replay_hook_events` + `index_events` invocations to the `Stop` list, after the existing `refresh_dashboard.py` and `render_state_surface` lines. Either as two separate `command` entries or a thin wrapper script (see Decision 2). |
| `agent-learning-compounder/bin/install_runtime_hooks.py` | Verify the Codex Stop hook emits matching commands — if `event_sources` only covers `collect_hook_event` today, extend the manifest emission to also schedule replay+index. |
| `agent-learning-compounder/bin/alc_bootstrap_pipeline` *(new, optional)* | Single entry that runs `replay_hook_events --input hook-events.jsonl --output events.jsonl --skip-malformed` then `index_events.run(state)`. Audit § 4 Option B; recommended because both `install.sh` and the Stop hook call the same code path. Keeps the install patch tiny. |
| `agent-learning-compounder/hooks/refresh_dashboard.py` *(if Decision 2 = "wrap")* | Could grow to call the new orchestrator before rendering, so the dashboard refresh always reads from a fresh sqlite. |
| `agent-learning-compounder/tests/test_pr5_install_warm_loop.py` *(new)* | Dual-path bootstrap smoke (see § "The dual-path smoke" below). |
| `agent-learning-compounder/CHANGES.md` | Note install-time warm-loop is now automatic; document the pre-PR4 upgrade one-liner. |
| `docs/dev/operator-upgrade-pr4.md` *(new, optional)* | Standalone upgrade doc if `CHANGES.md` is too cramped. |

## Design decisions the next session needs to make

### Decision 1 — Inline in `install.sh` vs new `alc_bootstrap_pipeline` script

**Option A — Inline two `python3 …` calls in `install.sh`.**
Smallest delta. The bootstrap branch grows by ~10 lines. The Stop hook
gets two separate `command` entries (replay then index). Both surfaces
own their own copy of the chain.

**Option B — New `bin/alc_bootstrap_pipeline` script that owns the
chain.** Both `install.sh` and the Stop hook call it. Audit § 4
Option B. Cleaner long-term, single testable entry point, matches
backlog item #06 ("a second pipeline shape has appeared"). Recommended.

The script can be ~30 lines:

```python
# bin/alc_bootstrap_pipeline
import argparse, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import index_events
from replay_hook_events import main as replay_main
from state_handle import StateHandle

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo", required=True, type=pathlib.Path)
    p.add_argument("--skip-replay", action="store_true")
    args = p.parse_args()
    state = StateHandle.for_repo(args.repo)
    hook_events = state.repo_state_dir / "hook-events.jsonl"
    events_jsonl = state.events_jsonl
    if not args.skip_replay and hook_events.is_file() and hook_events.stat().st_size:
        replay_main(["--input", str(hook_events), "--output", str(events_jsonl),
                     "--skip-malformed"])
    index_events.run(state.repo_state_dir)

if __name__ == "__main__":
    raise SystemExit(main())
```

(Refine — `replay_hook_events.main()` may need adjustment; check before
copying. The current CLI is `bin/replay_hook_events --input … --output …`
and reads `sys.argv` directly.)

**Recommendation: B.**

### Decision 2 — How the Stop hook adds the chain

The Stop hook today is two entries in `hooks/hooks.json`:

```json
"Stop": [{ "matcher": ".*", "hooks": [
  {"type": "command", "command": "${CLAUDE_PLUGIN_ROOT}/hooks/refresh_dashboard.py"},
  {"type": "command", "command": "${CLAUDE_PLUGIN_ROOT}/bin/render_state_surface --repo $PWD --format session-report"}
]}]
```

Three shapes:

**Option α — Add one more `command` entry for the orchestrator.**
Cleanest config-wise; explicit ordering (replay+index runs before
`refresh_dashboard.py`, which then reads from a warm sqlite).

**Option β — Have `refresh_dashboard.py` call the orchestrator
first.** Less config churn but couples two concerns (hook surface
becomes "refresh + render"). Hidden side effect.

**Option γ — A new `hooks/warm_loop_index.py` thin wrapper that
shells the orchestrator.** Matches the existing
`refresh_dashboard.py` pattern; adds the file overhead but keeps
each Stop entry single-purpose.

**Recommendation: α + γ together** — α for config clarity, γ so
`install_runtime_hooks.py` has a stable wrapper path to install (the
runtime hook installer prefers wrapper scripts over inline argv).

### Decision 3 — Replay incremental or full each Stop?

`replay_hook_events` is currently one-shot input→output (not
incremental). On every Stop hook, it would rewrite `events.jsonl` from
the full `hook-events.jsonl`. Idempotent because `index_events` is
cursor-driven on `events.jsonl` — so only NEW lines are inserted into
sqlite. Cost: scales with `hook-events.jsonl` size. After
`replay_hook_events`'s 5 MB rotation, that's ~5 MB max.

**Option I — Full replay each Stop.** Simplest. Today's
`hook-events.jsonl` on this repo is ~1.2 MB / 4 K rows → tens of ms.
The 5 MB rotation cap bounds worst case at ~50 ms per Stop. Fine.

**Option II — Make replay incremental** (add a cursor on
`hook-events.jsonl`). Faster but adds a new on-disk piece (cursor),
which the architecture has been disciplined about avoiding for
non-essential cases. Defer until measurement says it's needed.

**Recommendation: I.** Leave incremental for if/when Stop-hook timing
becomes a complaint.

### Decision 4 — Install-time replay window

`hook-events.jsonl` on a fresh install is empty. Replay during install
is a no-op for first-time consumers, and writes potentially-large
events.jsonl for operators who already accumulated hook history. The
existing rotation (5 MB) bounds it. Inline `replay → index` at install
is safe even on the empty case (replay no-ops, index no-ops).

**Just do it.** No flag needed beyond `--no-first-run-index` for the
operator who explicitly wants to defer.

## The dual-path smoke (the regression that would have caught PR 4 P1)

The reviewer flagged that PR 4 shipped without proving the new
collector row path end-to-end. PR 5's install/bootstrap smoke must
exercise BOTH paths in one shot:

```python
# tests/test_pr5_install_warm_loop.py — shape, fill in details
class WarmLoopBootstrapTests(unittest.TestCase):
    def test_install_warm_loop_indexes_both_legacy_and_fresh(self):
        # 1. Set up a fresh test repo with .agent-learning init'd.
        # 2. Drop a legacy schema-3 flat row with abs `repo` directly
        #    into events.jsonl (mimics rows already on disk pre-PR4).
        # 3. Emit a fresh collect_hook_event.normalize_event(...) row
        #    into hook-events.jsonl (mimics current collector output).
        # 4. Run the bootstrap orchestrator (or install.sh's bootstrap
        #    branch in a subprocess).
        # 5. Assert alc_query.get_actor_summary(state).total == 2
        #    and actor_kinds includes both row's kinds.
```

If you do Option B (orchestrator script), the test can call
`alc_bootstrap_pipeline.main(["--repo", str(repo)])` directly. If you
do Option A (inline only), invoke the bootstrap branch via subprocess
against a tmp repo.

Either way, **this test is the gate** — it would have caught the
schema-stamp mismatch in PR 4 and it must pass in PR 5 against both
the install-time and Stop-hook code paths.

See `/home/tth/.claude/projects/-home-tth-work-active-agent-learning-compounder/memory/feedback-schema-version-bumps.md`
— the rule "schema-version changes need a live collect→index→query
test" applies to install/bootstrap changes too. The orchestrator IS the
producer side here.

## Concrete starting steps

```bash
cd /home/tth/work/active/agent-learning-compounder/agent-learning-compounder

# 1. Confirm the replay → index chain works against this repo's state
#    (sanity check that the surface we're about to wire still behaves).
REPO_STATE=$(python3 -c '
import pathlib, sys
sys.path.insert(0, "bin")
from state_handle import StateHandle
print(StateHandle.for_repo(pathlib.Path("..").resolve()).repo_state_dir)
')
python3 bin/replay_hook_events \
    --input  "$REPO_STATE/hook-events.jsonl" \
    --output "$REPO_STATE/events.jsonl" \
    --skip-malformed
python3 bin/index_events --state "$REPO_STATE/"
sqlite3 "$REPO_STATE/events.sqlite" 'SELECT COUNT(*) FROM events;'
# Expect ≥ 4 310 on this machine (PR 4's live verification baseline);
# any positive count on another machine means the chain works. PR 5
# doesn't change the indexer, just where it gets called from.

# 2. Read install.sh:380-420 to see exactly where alc_init is invoked.
#    The new orchestrator call goes after alc_init, before the
#    "bootstrapped" message.

# 3. Read hooks/hooks.json to see the Stop list shape. Decide α/β/γ
#    per Decision 2.

# 4. Read bin/replay_hook_events to confirm the CLI surface the
#    orchestrator should call.

# 5. Read bin/install_runtime_hooks.py around the events list (line 27)
#    to see how Stop hooks are mapped per-runtime. If the existing
#    install_runtime_hooks wiring already covers wrapping the Stop
#    command, the new wrapper script just slots in.
```

## Tests to run after PR 5

```bash
cd agent-learning-compounder

python3 -m unittest discover -s fixtures/tests   # must stay green (252)
python3 -m unittest discover -s tests            # must stay green (371)
python3 scripts/run_pressure_tests.py            # 4 pressure gates

# Focused PR 5 suites:
python3 -m unittest \
    tests.test_pr5_install_warm_loop \
    tests.test_pipeline_b1_b3_b12 \
    tests.test_install_bootstrap \
    fixtures.tests.test_replay_hook_events \
    2>&1 | tail
```

Manual end-to-end on a tmp repo:

```bash
tmp=$(mktemp -d)
git -C "$tmp" init -q
git -C "$tmp" commit --allow-empty -m seed --no-gpg-sign

# Pre-drop a legacy v3 row to prove dual-path:
mkdir -p "$tmp/.agent-learning/repos/$(python3 -c '
import sys; sys.path.insert(0,"bin")
from state_handle import StateHandle
import pathlib
print(StateHandle.repo_id(pathlib.Path("'"$tmp"'")))')"

# Run the bootstrap branch.
bash install.sh --bootstrap-repo "$tmp" --runtime claude --apply-runtime-hooks

# Check events.sqlite exists and has rows.
python3 -c "
import sys, pathlib
sys.path.insert(0, 'bin')
import alc_query
from state_handle import StateHandle
state = StateHandle.for_repo(pathlib.Path('$tmp'))
print(alc_query.get_actor_summary(state, since='30d'))
"
```

## Constraints (don't violate)

- **Don't expand scope to transcript backfill.** Bootstrap audit § 5
  recommends a bounded `backfill_transcripts` + `extract_sessions`
  inline at install. That's its own PR. PR 5 = warm `events.sqlite`
  from `hook-events.jsonl`, nothing more.
- **No new state files.** `replay_hook_events` writes to the existing
  `events.jsonl`; `index_events` writes to the existing
  `events.sqlite` + cursor. The orchestrator must not create new
  on-disk pieces.
- **Don't re-introduce the SCHEMA_VERSION trap.** If you're tempted to
  bump anything in `collect_hook_event` / `event_schema` again,
  re-read `feedback-schema-version-bumps.md`. The end-to-end gate is
  non-negotiable.
- **`install.sh` mustn't fail hard if the orchestrator chokes.**
  Wrap in a `|| { warn ; continue }` pattern matching the existing
  `alc_init` block at line 415–417. Bootstrap proceeds; operator
  re-runs the orchestrator manually.
- **Codex and Claude must reach parity.** If you add a wrapper to
  `hooks.json` (Claude), update `install_runtime_hooks.py` so the
  Codex `hooks.json` gets the equivalent command. Both runtimes
  should warm the sqlite on Stop.
- **Keep the orchestrator idempotent.** Replay is full each run;
  index is cursor-driven and only inserts new rows. Re-runs after
  the bootstrap (e.g. operator running `alc_init --rebuild` later)
  must not duplicate rows.

## When you're done

Commit message convention:

```
feat(install): warm events.sqlite on bootstrap + Stop hook (PR 5)
```

Update memory:

- `scope-rename-rollout.md`: mark PR 5 shipped. Add commit refs.
  The 5-PR rollout is complete after this.
- `feedback-schema-version-bumps.md`: cross-link the new
  `test_pr5_install_warm_loop` test as the second example of the
  end-to-end gate this rule produces.
- Consider promoting `feedback-schema-version-bumps.md` into a
  CLAUDE.md note if the orchestrator and `collect_hook_event`
  schema seam keeps being a stumbling block.

Push when the user says push.

## References

- `docs/dev/bootstrap-wiring-audit-2026-05-27.md` — the full audit of
  what install runs today vs what the loop needs (especially § 4
  "Proposed wiring" and § 5 "Sync vs background tradeoffs").
- `docs/dev/pipeline-audit-2026-05-27.md` — the full bug taxonomy that
  PR 4 worked through; B5–B13 lists what PR 5 explicitly does NOT
  tackle.
- `docs/dev/pr4-next-session.md` — sibling brief, same shape.
- `tests/test_pipeline_b1_b3_b12.py` — PR 4's regression suite;
  PR 5's `test_pr5_install_warm_loop` should follow the same pattern
  (StateHandle.for_repo against a tmp repo, env scrubbed in setUp).
- `/home/tth/.claude/projects/-home-tth-work-active-agent-learning-compounder/memory/feedback-schema-version-bumps.md`
  — the durable lesson from PR 4's P1: schema/pipeline changes need a
  live producer→consumer regression. PR 5's dual-path smoke is the
  same rule applied to install-time wiring.
