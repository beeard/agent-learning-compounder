# Runtime Boundary

Development happens in this repository. Runtime installs are artifacts.

## Rule

- Edit source under `/home/tth/work/active/agent-learning-compounder`.
- Treat user-scope runtime trees as read-only evidence:
  - `/home/tth/.agents`
  - `/home/tth/.claude`
  - `/home/tth/.codex`
  - `/home/tth/.agent-learning`
  - `/home/tth/.local/state/agent-learning`
- Do not patch installed runtime copies to fix development bugs.
- Do not change global hook/config files as part of development.
- Promote source to user runtimes only through an explicit install/release step.

## Runtime mode separation

`bin/runtime_topology.py` is the source of truth for runtime wiring mode:

- **Dev mode**
  - Writes only repo-local development hooks.
  - Uses `.runtime/agent-learning-user` and `.runtime/agent-learning-state`.
  - Uses repo-source command roots so dev hooks stay inside this repository.
- **Release mode**
  - `install_runtime_hooks` is explicit and requires `--apply`.
  - Writes `.claude/settings.local.json` or `.codex/hooks.json` depending on runtime/scope.
  - Can target user scope only when `--scope user` is requested.
- **Drift mode**
  - `check_runtime_drift` is read-only.
  - Compares against repo-local runtime artifacts by default.
  - Adds user-scope artifacts only when `--include-user-runtimes` is set.

## Repo-Local Dogfood Surfaces

Use repo-local runtime and state paths while developing:

- `.claude/settings.local.json` for Claude sessions started from this repo.
- `.codex/hooks.json` only when intentionally testing Codex from this repo.
- `.agent-learning/` for repo state.
- `.runtime/agent-learning-user/` for dev auto-distill user-scope outputs.
- `.runtime/agent-learning-state/` for background event writes that are not
  bound to a repo state handle.

These paths are ignored by git and may be deleted/recreated.

## Drift Check

Run this read-only check before release or when runtime behavior looks wrong:

```bash
python3 agent-learning-compounder/bin/check_runtime_drift
```

By default it checks only repo-local runtime artifacts. To audit installed
user runtimes without changing them:

```bash
python3 agent-learning-compounder/bin/check_runtime_drift --include-user-runtimes
```

Drift means the runtime artifact no longer matches the source tree. Fix the
source, test it, and reinstall deliberately; do not patch the artifact directly.

## Auto-Distill In Dev

`auto_distill_session` can read global transcript folders as input, but dev
session hooks must write outputs inside this repo. `scripts/dev-session-setup.sh`
uses `runtime_topology.py` so command paths and state roots are resolved from the
repo root, not `~`-home defaults.

The command currently wires:

- `AGENT_LEARNING_USER=$REPO/.runtime/agent-learning-user`
- `AGENT_LEARNING_PERSONAL=$REPO/.runtime/agent-learning-user`
- `AGENT_LEARNING_STATE_DIR=$REPO/.runtime/agent-learning-state`
- `AGENT_LEARNING_SKILL_DIR=$REPO/agent-learning-compounder`

That keeps dogfood outputs contained until a release is intentionally installed.

## Event write sink contract

State Scope lives in `bin/state_handle.py`. It owns project/user/background
target selection for durable reads and writes; callers should ask it for
`StateHandle`, user report paths, read-scope validation, or write-target
classification instead of reconstructing those choices locally.

Writer-style callers (`alc_eval`, `alc_propose`, `alc_invoke`, etc.) should pass
explicit state intent into `event_writer` instead of mutating
`AGENT_LEARNING_STATE_DIR`. Use one of:

- `state=<StateHandle>` when the caller already has a repo handle
- `repo=<repo path>` when it can resolve from repo
- `state_root=<path>` only for legacy fallback
- State Scope background targets for explicit non-project event sinks

Every `events.jsonl` row now carries `_write_scope` in its payload so project
vs explicit background vs legacy writes remain distinguishable in audits.

## Refresh Run Boundary

`bin/refresh_run.py` owns repo refresh execution. Warm refresh is the Stop-hook
and bootstrap path: it appends only unreplayed `hook-events.jsonl` rows into
project `events.jsonl` and then indexes that file. Full refresh runs the same
ingestion path first, then baseline, skill-map, export, queue, gate, retirement,
and domain-rule stages under the repo `.refresh.lock`.

`bin/refresh_learning_state` stays as the operator-facing CLI adapter. Do not
route dashboard read-model construction or proposal lifecycle ranking through
Refresh Run; those completed boundaries live in `bin/dashboard_read_model.py`
and `bin/proposal_lifecycle.py`.
