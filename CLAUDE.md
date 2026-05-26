# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

This is the **source tree of a portable skill package**, not an app. It builds and ships
`agent-learning-compounder/` as a self-contained Codex/Claude skill that other repos install
via `install.sh` (or, increasingly, `npx alc-install` / `curl … | sh` / `/plugin install`).
Production version string is `2026.05.27+review7-plus2.1`. When changing behavior, assume the
consumer is a fresh repo that just installed the package — paths, imports, and entrypoints
must work from the installed location, not just from this working tree.

## Common commands

All test/dev commands run from inside `agent-learning-compounder/` (the inner skill dir),
not the repo root:

```bash
cd agent-learning-compounder

# Full unit + integration suite (29 files, ~166 tests; 4 SKIPs depend on optional extras)
python3 -m unittest discover -s fixtures/tests

# Post-install smoke test — verifies the installed layout is intact
python3 -m unittest discover -s tests

# Durable-write readiness pressure tests (validator, scrubber, output schema)
python3 scripts/run_pressure_tests.py

# Single test file
python3 -m unittest fixtures.tests.test_queue_dedup

# Single test method
python3 -m unittest fixtures.tests.test_queue_dedup.QueueDedupTests.test_collapses_near_duplicates
```

Optional extras (only needed for MCP server, dashboard, or embedding-backed dedup):

```bash
pip install -r agent-learning-compounder/requirements-optional.txt
```

End-to-end install verification from the source root:

```bash
./install.sh --codex --verify   # also: --claude, --codex-home, --target DIR
./install.sh --bootstrap-repo /path/to/repo --runtime auto --verify
```

## Architecture

### Layered pipeline

1. **Install layer** (`install.sh`): copies the inner `agent-learning-compounder/` tree
   into a runtime skills root (`~/.agents/skills`, `~/.claude/skills`, `~/.codex/skills`,
   or `--target`). Refuses to write through symlinks and backs up any existing install to
   a timestamped `.bak-<ts>` directory.
2. **Repo bootstrap** (`bin/init_learning_system`): per-target-repo init. Writes
   `<repo>/.agent-learning.json` (the integration manifest) and state under
   `<repo>/.agent-learning/repos/<repo-id>/` (baseline, domain-rules, skill-map,
   reports, hook event log, improvement queue).
3. **Ingestion** (`bin/build_repo_baseline`, `bin/extract_sessions`,
   `bin/distill_learning`): turn repo facts and session transcripts into a report.
4. **Export** (`bin/export_gates`, `bin/export_skill_context`): produce the two durable
   compact surfaces future agents load — `latest-approved-gates.md` and
   `latest-skill-context.md`. Never raw logs.
5. **Hook telemetry** (`bin/collect_hook_event`, `bin/install_runtime_hooks`):
   runtime-agnostic event collector + a two-phase runtime wiring step.
6. **Refresh** (`bin/refresh_learning_state`): re-derives exports from the current
   corpus; declarative-only — never registers itself with cron/systemd.

### Eight review7-plus1 add-ons

These are additive on top of the upstream `review7-production` core and each have a
reference doc:

- `replay_hook_events` — migrate older hook logs to schema v2 (`references/event-schema-evolution.md`)
- `queue_dedup` — collapse near-duplicate improvement-queue rows; stdlib trigram or
  optional `sentence-transformers` (`references/queue-dedup.md`)
- `evaluate_gate_effectiveness` — correlation-only signals per stable 12-char `gate_id`
  (`references/gate-effectiveness.md`)
- `propose_domain_rules` — n-gram mining for correction-correlated rules
  (`references/domain-rules-learning.md`)
- `causal_probe` — deterministic A/B skip cohorts per gate
- `gates_promote` / `gates_inherit` — cross-repo federation via a shared registry, with
  `derived_from:` provenance (`references/cross-repo-gates.md`)
- `serve_dashboard` — localhost FastAPI/Jinja2/HTMX operator view
- `alc_mcp/server.py` — stdio MCP server exposing `get_gates`, `report_outcome`,
  `propose_gate`, `get_skill_context`

### Dual-name layout (intentional, not duplication)

This trips up grep-based exploration if you don't know it:

- `bin/<name>` — canonical shebanged executable (no extension)
- `bin/<name>.py` — **symlink to `bin/<name>`**, required so Python's import machinery
  resolves cross-script imports like `from scrub_secrets import scrub`
- `scripts/<name>.py` — **symlink to `../bin/<name>`**, the stable compatibility path
  documented in `SKILL.md` and used by external invocations
- `reference-lib/<name>` — canonical markdown reference (no extension)
- `references/<name>.md` — **symlink to `../reference-lib/<name>`**, the presentation
  surface

When editing a script or reference, **edit the canonical file** in `bin/` or
`reference-lib/`, not the symlink.

### Two test directories with different purposes

- `tests/` — runtime smoke tests; verifies the *installed* layout is intact. Small.
- `fixtures/tests/` — the real unit + integration suite, colocated with the
  `fixtures/eval-fixtures/` data they consume. The name reflects co-location, not that
  the tests themselves are fixtures.

### State and trust boundaries

State root precedence (first match wins): `--state-dir` → `AGENT_LEARNING_STATE_DIR` →
`--personal` → `<repo>/.agent-learning` (production default) → `$XDG_STATE_HOME/...` →
`~/.local/state/...`. Repo-local is the recommended default.

Trust model the code enforces — preserve these when changing things:

- **Never persist raw prompts, raw tool output, transcript chunks, or secret markers.**
  Hook events have a bounded allowlisted field set; telemetry writes reject symlinks and
  non-regular files.
- **Installer refuses to write tracked files.** `.agent-learning.json` and runtime hook
  configs (`.codex/hooks.json`, `.claude/settings.local.json`) must be untracked; the
  installer auto-adds them to `.gitignore` when a `.git/` exists and refuses to overwrite
  if they are already tracked.
- **Runtime hook install is manifest-only by default.** `install_runtime_hooks.py`
  requires explicit `--apply` after a `--dry-run` review. Refresh manifests are
  declarations — they do **not** register schedulers.
- **`validate_outputs.py`** rejects psychological/ability claims about the operator. To
  catch personal-name variants, set `AGENT_LEARNING_SUBJECT_NAMES="Lisa,Per"` (comma- or
  whitespace-separated; entries are regex-escaped).
- **Default to read-only**; `distill_learning.py` only mutates durable memory with
  `--write` plus an explicit `--personal` root or `AGENT_LEARNING_PERSONAL`.

### Runtime adapter matrix

| Runtime | Hook config target            | Installer flag      |
|---------|-------------------------------|---------------------|
| Codex   | `.codex/hooks.json`           | `--runtime codex`   |
| Claude  | `.claude/settings.local.json` | `--runtime claude`  |

Both runtimes share the same wrapper command and manifest. Adding a new runtime means
updating `install_runtime_hooks.py` path handling, event mapping, command-integrity
validation, and regression coverage for both dry-run and apply flows.

## Editing conventions

- Read the relevant `reference-lib/` doc before changing a subsystem (architecture,
  threat-model, output-schema, gate-registry, hook-telemetry, source-adapters,
  pressure-tests).
- After any code change, run the three suites above; the pressure tests are the
  durable-write gate.
- Don't edit evergreen personal memory files (`soul.md`, `system.md`, `preferences.md`)
  — propose changes in the report instead. This is enforced operationally, not by
  permissions.
- Don't add a new top-level state file without updating the health contract in
  `init_learning_system.run_self_test` and the architecture reference.
