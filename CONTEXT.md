# CONTEXT

> For an LLM agent landing in this repo. Read this before grep. README.md is
> the human pitch; CLAUDE.md (inner) is the Claude plugin entry; this file
> is what makes you effective fast.

## 1. What this repo is

A **portable skill package**, not an app. The source tree builds and ships
`agent-learning-compounder/` (the inner skill dir) as a self-contained
Codex / Claude Code skill that other repos install via three first-class
paths. The outer repo is the build / distribution surface; the inner dir
is the artifact.

When you change behavior, the consumer is a fresh repo that just installed
the package. Paths, imports, and entrypoints must work from the **installed
location**, not just from this working tree.

Production version string: `2026.05.27+review7-plus2.1` (single source of
truth in `MANIFEST.json`, mirrored to README, plugin.json, marketplace.json).

## 2. Three install paths (when each is preferred)

| Path | Command | When |
|---|---|---|
| **npm / npx** | `npx agent-learning-compounder` | Anyone with Node 18+. Zero-config. **Symlink caveat:** npm strips symlinks on pack, so `scripts/alc-install.mjs` materializes the `.py` aliases as file copies at install. Other paths preserve symlinks. |
| **curl one-liner** | `curl -fsSL https://raw.githubusercontent.com/beeard/agent-learning-compounder/master/bootstrap.sh \| sh` | No Node. Just `curl` + `tar`. Fetches master tarball, exec's `install.sh`. |
| **Claude Code marketplace** | `/plugin marketplace add beeard/agent-learning-compounder` then `/plugin install agent-learning-compounder@agent-learning-compounder` | Claude Code users who want hooks + MCP + slash commands wired automatically. |
| Git clone (legacy) | `git clone … && ./agent-learning-compounder/install.sh` | Full source for inspection / contribution. |

All three production paths pass the same nine-check end-to-end validation
suite. Forward any `install.sh` flag through `npx` / curl pipe:

```bash
npx agent-learning-compounder --bootstrap-repo "$PWD" --verify
```

Runtime target selection for these paths is owned by
`agent-learning-compounder/bin/runtime_topology.py`: user-global Codex/Claude
skills roots, Codex-home roots, Claude plugin roots, explicit targets, runtime
resolution, and repo bootstrap expansion all route through that policy.
`install.sh` stays the execution adapter for copy, backup, verification,
dashboard build, bootstrap hooks, and first-run indexing.

## 3. Dual-name layout (without this, grep goes wrong)

```
bin/<name>                    ← canonical shebanged executable (no extension)
bin/<name>.py                 ← symlink → bin/<name>   (required by Python import)
scripts/<name>.py             ← symlink → ../bin/<name>  (stable external path)
reference-lib/<name>          ← canonical markdown reference (no extension)
references/<name>.md          ← symlink → ../reference-lib/<name>
```

Why the symlinks exist:

- `bin/<name>.py` — cross-script imports like `from scrub_secrets import scrub`
  need the `.py` suffix on `sys.path`. Removing these symlinks breaks every
  script that imports a sibling.
- `scripts/<name>.py` — the stable compatibility path documented in `SKILL.md`
  and used by external invocations.

**When editing: edit the canonical file in `bin/` or `reference-lib/`.** Do
not edit the symlink. There are 112 entries in `bin/`; roughly half are
symlinks.

## 4. Two test directories (different purposes)

```
agent-learning-compounder/tests/              ← post-install smoke (small, ~219 tests)
agent-learning-compounder/fixtures/tests/     ← unit + integration (29 files, ~251 tests)
```

The `fixtures/` prefix on the second one reflects co-location with
`fixtures/eval-fixtures/` data, not that the tests themselves are fixtures.

Plus pressure tests for durable-write readiness:

```
agent-learning-compounder/scripts/run_pressure_tests.py
```

Run all three after any code change. Pressure tests are the durable-write
gate — never skip.

```bash
cd agent-learning-compounder
python3 -m unittest discover -s fixtures/tests   # unit + integration
python3 -m unittest discover -s tests            # smoke
python3 scripts/run_pressure_tests.py            # durable-write gate
```

## 5. State topology (where things live)

```
<repo>/.agent-learning.json                       # integration manifest
<repo>/.agent-learning/repos/<repo-id>/
    config.json                                    # state_version, retention
    baseline.json
    domain-rules.active.json
    skill-map.json
    hook-events.jsonl                              # JSONL primary (append-only)
    events.jsonl                                   # writer + replay JSONL primary
    improvement-queue.jsonl
    events.sqlite                                  # SQLite indexed cache over JSONL
    reports/latest-approved-gates.md               # ← durable surface 1
    reports/latest-skill-context.md                # ← durable surface 2
    reports/latest-session-context.md              # ← durable surface 3 (alc_init)
    hooks/                                         # manifest + wrapper script
    automation/                                    # refresh manifest (declarative)
    sandbox-worktrees/<exec-id>/                   # exec_sandbox tier worktrees
```

**State root precedence** (first match wins):

1. `--state-dir` flag
2. `AGENT_LEARNING_STATE_DIR`
3. `--personal` flag
4. `<repo>/.agent-learning` ← **production default**
5. `$XDG_STATE_HOME/agent-learning`
6. `~/.local/state/agent-learning`

For project event writes, pass `state=<StateHandle>` or `repo=<path>` to the
event writer. Avoid mutating `AGENT_LEARNING_STATE_DIR` inside project writers.
`bin/state_handle.py` is the State Scope module: it owns project handles,
user report paths, background write targets, read-scope validation, and
`_write_scope` classification. Keep query parsing in `alc_query.py` and
serialization/locking/boundary checks in `event_writer.py`.

`bin/refresh_run.py` is the Refresh Run module: it owns warm/full refresh
profiles, incremental hook replay into project `events.jsonl`, indexing, the
repo refresh lock, stage ordering, and structured result payloads. The public
`refresh_learning_state` command is a CLI adapter around this module.

`bin/causal_evidence.py` is the Causal Evidence module: it owns probe assignment
semantics, accepted probe decisions, alias-aware evidence rows, causal signal
thresholds, and retirement/demotion eligibility. The probe CLI, hook collector,
effectiveness scorer, and refresh queue writer are adapters around that policy.

`bin/dashboard_read_model.py` is the Dashboard Read Model module: it owns
read-only payload assembly for FastAPI/React, static dashboard rendering, and
the stdlib fallback. Keep project reads behind `alc_query`/`StateHandle`, and
keep promote/mute/distill/proposal writes in the FastAPI action or propose
layers.

`bin/dashboard_url_publisher.py` is the Dashboard URL Publisher module: it owns
live `dashboard/server.json` marker schema, loopback validation, marker cleanup,
and static fallback ordering. FastAPI/stdlib servers publish through it;
`state_handle.dashboard_url` and MCP `get_dashboard_url` read through it.

`bin/proposal_lifecycle.py` is the Proposal Lifecycle module. It owns proposal
identity, lifecycle records, proposal event payloads, and normalized read
mirrors over improvement queue, patch, and suggestion artifacts. Keep CLI/MCP
write entrypoints in `alc_propose.py`; expose read mirrors through
`alc_query.py`.

`RuntimeTopology` (`bin/runtime_topology.py`) centralizes runtime mode selection
for hook command rendering, config targets, and drift checks:

- dev mode: repo-local dogfood paths and commands
- release mode: explicit install into repo/user runtime config targets
- drift mode: repo-only by default, with explicit `--include-user-runtimes` for
  read-only user-runtime audit

**Storage model: JSONL primary, SQLite indexed cache.** Reads go through
`bin/alc_query.py`. Don't reach into SQLite or the JSONL files from a new
consumer — `alc_query` controls schema evolution. (See § 6.)

## 6. The named catalogs (KTD-15 family)

ALC uses **stable IDs over cute names.** When adding analyst queries,
generators, MCP tools, or propose ops, add the registry entry first; then
implement against the ID.

| Catalog | IDs | Source of truth |
|---|---|---|
| Analyst queries | Q1–Qn | `bin/analyst_queries.py::QUERY_SPECS`; mirror: `reference-lib/analyst-queries-catalog` |
| Generators (patch and suggestion emitters) | G1–Gn | `bin/recommender_generators.py::GENERATORS`; mirrors: `reference-lib/generator-catalog`, `skills/alc-core/references/generator-catalog.md` |
| MCP tools | M1–M20 | `reference-lib/mcp-catalog` (`alc_mcp.catalog.MCP_TOOLS`) |
| Propose ops | UP1–UP5 | `reference-lib/propose-catalog` |
| Hermes-DSL targets | `skill` / `agent` / `command` / `hook` | `reference-lib/hermes-dsl-spec` |

## 7. The read/propose seams (KTD-21)

Two canonical APIs. If you're tempted to read/write ALC state without going
through these, stop.

| Seam | API | Consumers |
|---|---|---|
| **Read** | `bin/alc_query.py` | Hooks, dashboards, MCP read tools, slash commands, `alc_init`, `ce_playbook` |
| **Propose / write** | `bin/alc_propose.py` | MCP propose/observe tools, event writer |

Writes that mutate target files go through **Hermes-DSL → `bin/alc_apply`.**
Every op has a `revert_op` (exact inverse) and a `preflight` block
(`allowed_roots`, `expected_target_sha256`, `max_target_size`). Refuses if
the target changed under us.

Bounded execution goes through **`bin/exec_sandbox`** in one of three
tiers: `read` (allowed prefixes only, 30s default), `worktree` (mutation in
isolation, 60s default), `eval` (300s default, powers `alc_invoke`-style
dispatch). All tiers: network blocked. Recursion capped at `--depth >= 2`.

## 8. Unified hook entry

`bin/render_state_surface` is the single entry point for hooks that surface
ALC state. Session-start, stop-hook, and `/alc-report` all route through it
so the synthesis discipline (allowlist in, markdown out) is enforced in one
place.

**If you add a hook that surfaces state, route it through
`render_state_surface`. Don't write your own renderer.**

## 9. Trust model (non-negotiable)

ALC's safety posture is load-bearing. Preserve these:

- **Never persist raw prompts, raw tool output, transcript chunks, or
  secret markers.** Hook events have a bounded allowlisted field set
  (`ts`, `event`, `runtime`, `repo`, `skill`, `tool`, `outcome`, `path`,
  `command_class`, plus short tags). `bin/scrub_secrets` runs before
  anything reaches durable storage.
- **Installer refuses to write tracked files.** `.agent-learning.json` and
  runtime hook configs (`.codex/hooks.json`, `.claude/settings.local.json`)
  must be untracked. Installer auto-adds them to `.gitignore` when `.git/`
  exists and refuses to overwrite tracked copies.
- **Runtime hook install is manifest-only by default.**
  `install_runtime_hooks.py` requires explicit `--apply` after `--dry-run`
  review. Refresh manifests are **declarations** — they do NOT register
  schedulers.
- **`bin/validate_outputs`** rejects psychological/ability claims about
  the operator. Personal-name variants via `AGENT_LEARNING_SUBJECT_NAMES`
  (comma-separated; regex-escaped).
- **Default to read-only.** `distill_learning.py` mutates durable memory
  only with `--write` plus an explicit user-scope root: `--user <path>`
  (alias: `--personal`, deprecated) or `AGENT_LEARNING_USER` (compat:
  `AGENT_LEARNING_PERSONAL`).
- **Hook event log files** created with `os.open(..., 0o600)` — no
  group/world-readable window between create and chmod.

## 10. Where to read first (task → reference)

Gate identity migrations are explicit: keep `_gate_id` stable, use
`export_gates --rename OLD:NEW`, preserve `previous_gate_ids`, and normalize
old ids at read/scoring boundaries instead of rewriting historical telemetry.

| If you're touching | Read first |
|---|---|
| Hooks (any kind) | `agent-learning-compounder/reference-lib/hook-telemetry` |
| Hook schema migration | `…/reference-lib/event-schema-evolution` |
| Source adapters (Codex / Claude transcript ingestion) | `…/reference-lib/source-adapters`, `…/distill-sessions` |
| Gate scoring or causal probes | `…/reference-lib/gate-effectiveness`, `…/gate-registry` |
| Cross-repo federation | `…/reference-lib/cross-repo-gates` |
| MCP tools | `…/reference-lib/mcp-catalog`, `agent-learning-compounder/.mcp.json` |
| Sandbox tiers | `…/reference-lib/sandbox-tiers` |
| Output schema / scrubbing | `…/reference-lib/output-schema`, `…/threat-model` |
| Apply path (Hermes-DSL) | `…/reference-lib/hermes-dsl-spec` |
| Anything performance-affecting | `…/reference-lib/pressure-tests` (the durable-write gate) |
| Install paths, target roots, or symlink layout | `agent-learning-compounder/bin/runtime_topology.py`, `agent-learning-compounder/tests/test_install_targets.py`, `CHANGES.md` (entries for `plus1.3`, `plus2.0`, `plus2.1`) |

## 11. Editing conventions

- Edit the canonical file in `bin/` or `reference-lib/`, not the symlink.
- After any code change, run all three test suites. The pressure-test
  suite is the durable-write gate — never skip.
- Don't edit evergreen personal memory files (`soul.md`, `system.md`,
  `preferences.md`) — propose changes in the report instead. Enforced
  operationally, not by permissions.
- Don't add a new top-level state file without updating the health
  contract in `init_learning_system.run_self_test` and the architecture
  reference.
- Don't add a new MCP tool, analyst query, or generator without adding
  the catalog entry first (§ 6).
- Synthesize `alc_query` results into prose before putting them in agent
  context. Never dump raw event rows or JSON payloads. See
  `bin/alc_init` (`render_runtime_summary_md`, `render_doc_contract_md`)
  for the synthesis discipline.

## 12. Quick orientation cheatsheet

```
Outer repo (build / distribution surface)
├── README.md                          # human pitch
├── STRATEGY.md                        # product anchor
├── ARCHITECTURE.md                    # 5-min mental model
├── CONTEXT.md                         # this file (for agents)
├── CLAUDE.md                          # outer contributor guide
├── CHANGES.md                         # release notes
├── MANIFEST.json                      # version source of truth
├── install.sh                         # the actual installer
├── bootstrap.sh                       # curl-one-liner entry
├── scripts/alc-install.mjs            # npm/npx entry
├── .claude-plugin/marketplace.json    # Claude Code plugin marketplace
├── package.json                       # npm
└── agent-learning-compounder/         # ← the artifact (inner skill dir)
    ├── CLAUDE.md                      # Claude plugin entry
    ├── AGENTS.md                      # Codex plugin entry
    ├── SKILL.md                       # generic skill manifest
    ├── .mcp.json                      # MCP stdio server registration
    ├── .claude-plugin/plugin.json     # plugin manifest
    ├── bin/                           # 112 entries (canonical + symlinks)
    ├── scripts/                       # external-facing path (symlinks)
    ├── reference-lib/                 # canonical markdown references
    ├── references/                    # symlinks → reference-lib/
    ├── alc_mcp/                       # MCP server (Python)
    ├── dashboard/                     # FastAPI + HTMX dashboard
    ├── skills/                        # alc-core, alc-dashboard
    ├── agents/                        # claude.yaml, openai.yaml
    ├── commands/                      # /alc-report, /alc-reviewer
    ├── hooks/                         # hooks.json, session-start
    ├── domain-rules/                  # generic + tm-norge presets
    ├── data-contracts/                # JSON schemas
    ├── fixtures/                      # eval-fixtures + tests
    └── tests/                         # post-install smoke
```
