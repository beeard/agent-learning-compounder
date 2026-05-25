# Sandbox Tiers (`exec_sandbox`)

`bin/exec_sandbox` runs bounded commands in one of three scopes.

## `read`
- Purpose: safe inspection without mutations.
- Allowed command prefixes:
  - `git log`, `git show`, `git diff`, `git blame`
  - `ls`, `find`, `cat`, `head`, `tail`, `wc`, `grep`, `stat`
  - `python -m unittest`, `python3 -m unittest`, `pytest`, `diff`
- Timeouts: default 30s, max 120s
- Network: blocked (`NO_NETWORK=1`, proxy vars unset)
- Writes outside repo path are rejected by command/path guard.

## `worktree`
- Purpose: allow command mutation in isolation.
- Command prefix restrictions: none.
- Execution path: `<state>/sandbox-worktrees/<exec-id>/`
- Cleanup: worktree removed after each run (including timeout/error).
- Timeouts: default 60s, max 300s
- Network: blocked

## `eval`
- Purpose: same as `worktree`, used for agent/recorder evidence collection.
- Intended use: allow `bin/alc_invoke`-style dispatch; nested tier-3 launches must be guarded by `--depth`.
- Timeouts: default 300s, max 900s
- Network: blocked

## Recursion and recovery
- Recursion control: `--depth` flag; `--depth >= 2` is rejected.
- Boot-time recovery: any stale worktree under `sandbox-worktrees` without active `running` row in `events.sqlite` is removed and emits `exec_sandbox_recovered`.

## Observability
- Each run emits one `exec_sandbox_run` event (payload includes `scope`, scrubbed command, exit code, duration, and stdout/stderr byte counters).
- Full streams are also stored in `<state>/sandbox-runs/<exec-id>/{stdout,stderr,exit_code>`.
