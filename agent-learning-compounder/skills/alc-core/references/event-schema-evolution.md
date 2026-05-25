# Hook Event Schema Evolution

The hook event JSONL log carries a `schema_version` integer on every row written
by `bin/collect_hook_event`. Older rows that predate this stamp are treated as
`schema_version: 1` on read.

## Versions

| Version | Added | Removed | Notes |
| --- | --- | --- | --- |
| 1 | (initial) | — | implicit; no stamp on disk |
| 2 | `schema_version`, `correlation_id`, `gate_loaded_ids`, `probe_decisions` | — | Phase 1 added the first three; Phase 3B (causal probes) added `probe_decisions` to the same v2 schema |
| 3 | `agent_role`, `agent_backend`, `agent_id`, `dispatch_id`, `agent_mode`, `agent_model`, `agent_effort`, `agent_sandbox`, `agent_write_scope`, `agent_worktree`, `agent_branch`, `parent_correlation_id` | — | Bounded agent-dispatch telemetry for subagents/background workers; repo config can disable model and scope capture |

`correlation_id` ties events from a single agent session together for Phase 2B
gate effectiveness analysis. `gate_loaded_ids` records which approved gates the
session actually loaded into context. `probe_decisions` is a list of
`{gate_id, decision}` dicts where `decision` is `load` or `skip`, recording
the per-gate A/B cohort assignment for a session under active probe.
`agent_*` fields record which delegated execution shape ran and the bounded
scope it was allowed to touch. They are for lifecycle improvement, not transcript
storage: prompts, tool output, raw diffs, and secret-shaped values remain
forbidden. Alias mapping and per-field caps are centralized in
`bin/agent_dispatch.py`; runtime-specific code should not fork that policy.

## Replay

`bin/replay_hook_events` reads a JSONL log and re-emits it through the current
collector's `normalize_event`. Output is always at the latest schema version.
The replay tool preserves the original `ts` from each input row (running it
through the same `bounded()` validator the collector applies to other string
fields), so time-series ordering survives migration.

```bash
python3 ../../bin/replay_hook_events.py \
  --input  "<state>/repos/<repo-id>/hook-events.jsonl" \
  --output "<state>/repos/<repo-id>/hook-events.latest.jsonl"
```

`--skip-malformed` tolerates corrupted lines (logs notice on stderr).
`--dry-run` reports row count without writing.

Replay refuses to write through a symlink at `--output` and refuses to read
from a non-regular `--input` (e.g. a directory).

## Policy

- Adding a field: bump schema version, list it in the table above, and
  guarantee readers can default-fill the absent field for older rows.
- Removing a field: bump schema version, list it in the Removed column, and
  document the migration in this file.
- Renaming a field: never. Add a new field, mark the old one removed at the
  next bump.
- Bounded fields only: every new field has a maximum size in bytes or items,
  enforced inside `normalize_event`. Hook logs are not blob storage.
