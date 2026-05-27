# Operator upgrade — pre-PR4 → PR 5

If you installed `agent-learning-compounder` before PR 4 landed
(2026-05-27) and your repo's `events.sqlite` looks sparse or empty
relative to the rows accumulated in `hook-events.jsonl`, run this once
after upgrading.

## Why

- **Pre-PR4** the indexer rejected every flat collector row whose `repo`
  field was an absolute path — meaning your `hook-events.jsonl` filled
  up but nothing reached `events.sqlite`.
- **PR 4** fixed the schema-stamp mismatch in `EventV4.upgrade_from` and
  threaded `repo=` through the writer callers, but the bridge between
  `hook-events.jsonl` and `events.sqlite` was still manual — you had to
  remember the two-step replay-then-index incantation.
- **PR 5** wires that bridge into bootstrap and the Stop hook, so fresh
  installs land warm and stay warm. Existing installs need a one-time
  cursor reset because the pre-PR4 indexer advanced the cursor past
  rows it had been quarantining.

## What to run

Replace `<repo>` with your repo root and `<skill-root>` with where you
installed the skill (`$HOME/.claude/plugins/agent-learning-compounder/`
for Claude plugin, `$HOME/.agents/skills/agent-learning-compounder/`
for Codex, etc.):

```sh
state="<repo>/.agent-learning/repos/$(python3 -c "
import pathlib, sys
sys.path.insert(0, '<skill-root>/bin')
from state_handle import StateHandle
print(StateHandle.repo_id(pathlib.Path('<repo>')))
")"

# 1. Drop the stale cursor so the indexer re-reads events.jsonl from byte 0.
rm -f "$state/events.sqlite.cursor"

# 2. Replay accumulated hook events into events.jsonl, then index into sqlite.
python3 <skill-root>/bin/alc_bootstrap_pipeline --repo <repo>

# 3. Sanity-check the result.
sqlite3 "$state/events.sqlite" 'SELECT COUNT(*) FROM events;'
```

You should see the count jump to roughly the number of rows in
`<state>/hook-events.jsonl` (minus a small number of quarantined rows;
the indexer prints `warn.index_events_skipped` lines for those).

## Going forward

Once you're on PR 5, the orchestrator runs at the end of every Stop hook
(via `hooks/warm_loop_index.py` for the Claude plugin and the matching
command appended to `.codex/hooks.json` / `.claude/settings.local.json`
by `install_runtime_hooks`). You don't need to repeat this dance — the
warm loop maintains itself.

If you want to skip the warm loop during install (e.g. on a very large
historical hook log), pass `--no-first-run-index` to `install.sh
--bootstrap-repo` or set `ALC_FIRST_RUN_INDEX=0` in the environment.
