# Changes

## 0.1.0

Clean public release line for the npm package.

- Resets package/plugin/manifest versioning to a conventional low semver
  series (`0.1.0`) instead of the internal review/build history labels.
- Ships the built React dashboard bundle in npm, tar, and zip artifacts.
- Keeps the dashboard bundle through install/release sanitization while still
  stripping caches, `node_modules`, generic `dist/`, and TypeScript build-info
  files.
- Makes `render_dashboard` work from a packaged install and adds an install
  regression that renders `latest-dashboard.html` from a fresh bootstrapped repo.
- Adds a stdlib static fallback for `serve_dashboard --repo ...` so a dashboard
  can be served even when optional FastAPI/uvicorn dependencies are absent.
- Adds `bin/alc_live_check`, an interactive one-command live-repo installer and
  verifier for hooks, warm-loop SQL, state JSON/HTML, static dashboard render,
  and direct MCP `tools/list`.

## 2026.05.27+review7-plus2.3

Close the warm-loop seam — `replay_hook_events` → `index_events` — into
the install bootstrap and the Stop hook. A fresh install lands with a
populated `events.sqlite` and stays populated without operator action.

Release-control follow-up in this source line:

- `scripts/build_release.sh` now sanitizes the whole staged release tree,
  not just the inner skill directory, and writes `SHA256SUMS` for the current
  release set only.
- Release readiness now has explicit helpers for extracted tar/zip checks,
  npm pack inspection, per-file release manifests, source-clean gating, and
  docs freshness.
- Install docs now distinguish zero-argument global install filesystem
  detection from `--bootstrap-repo --runtime auto` env/repo resolution, with
  hook writes kept behind `--apply-runtime-hooks`.

- New `bin/alc_bootstrap_pipeline` — single orchestrator for the chain.
  Called from `install.sh --bootstrap-repo` (after `alc_init`) and from
  the runtime Stop hook. Idempotent: replay is full each run, the
  indexer is cursor-driven and only inserts rows past the cursor.
- `install.sh` — runs the orchestrator at the end of `--bootstrap-repo`
  (best-effort). Opt out via `--no-first-run-index` or `ALC_FIRST_RUN_INDEX=0`.
- `hooks/hooks.json` — adds `hooks/warm_loop_index.py` to the Stop list
  before `refresh_dashboard.py` so the dashboard re-render reads a fresh
  sqlite.
- `bin/install_runtime_hooks` — appends the same warm-loop command to
  the Stop hook in `.codex/hooks.json` and `.claude/settings.local.json`,
  giving Codex parity with the Claude plugin path.
- `tests/test_pr5_install_warm_loop.py` — dual-path regression. Exercises
  both a legacy schema-3 flat row (carrying `repo` as an absolute path)
  and a fresh `collect_hook_event.normalize_event(...)` row through the
  bootstrap chain into `events.sqlite`. The same end-to-end gate
  PR 4's `feedback-schema-version-bumps.md` requires.

### Operator upgrade from pre-PR4

If you installed before PR 4 fixed the schema-stamp mismatch and your
`events.sqlite` cursor advanced past quarantined rows, drop the cursor
and re-run the orchestrator. PR 5's bootstrap path does this for fresh
installs; existing installs need one manual reset:

```sh
state=<repo>/.agent-learning/repos/<repo-id>
rm -f "$state/events.sqlite.cursor"
python3 <skill-root>/bin/alc_bootstrap_pipeline --repo <repo>
```

See `docs/dev/operator-upgrade-pr4.md` for the longer form.

## 2026.05.27+review7-plus2.2

Session-lifecycle synthesiser + self-dog-food doc contract.

### New MCP tool — `next_action` (M11)

Thin-skill + smart-MCP pattern. Consolidates "what's next", "session
start", "session end", "where did I leave off", "recap" into one
computed answer over the existing `alc_query` catalog (KTD-21).

- `bin/alc_next_action.py` (572 lines) — the synthesiser. Five-rung
  priority ladder: pending patches → recent rejected verdicts → stale
  recommendations → recent commits without follow-up plan → idle state.
- New skill `skills/alc-next/SKILL.md` triggers on English + Norwegian
  lifecycle phrases ("hva er neste", "hvor var jeg", …) and just calls
  the MCP tool + relays headline + rationale + suggested action.
- Auto-registered via the `#01` `MCP_TOOLS` catalog pattern — no
  `alc_mcp/server.py` edits required to ship a new tool now.
- Cache side-effect: each call writes
  `<state>/repos/<repo-id>/reports/latest-next-action.json` so future
  dashboard and hook consumers can read the most recent.
- 61 new unit tests covering each intent (`start`, `next`, `end`,
  `recap`, `leftoff`, `auto`) + every priority-ladder rung + schema
  validation + idempotency.

Total MCP surface: 11 → 12 tools.

### Self-dog-fooding the doc contract

`alc_init`'s doc-contract check had been flagging ALC's own repo for
6 missing canonical docs. Closed the architecture-tier gap:

- `STRATEGY.md` (213 lines) — target problem, approach, users, key
  metrics, tracks of work. Synthesised from project history in the
  operator's voice; downstream CE skills (`/ce-ideate`,
  `/ce-brainstorm`, `/ce-plan`) read it as grounding when present.
- `ARCHITECTURE.md` (264 lines) — five-minute mental model of the
  layered pipeline with a Mermaid diagram. Points at
  `reference-lib/` for deep dives.
- `CONTEXT.md` (258 lines) — LLM-agent-facing repo orientation.
  Dual-name layout warning, install path comparison, state topology,
  named-catalog vocabulary, read/propose seams (KTD-21), where to
  read first for any given task.

`alc_init` now reports doc_contract_missing 6/7 → 1/7 against this
repo (last remaining is `docs/brainstorms/`, which gets created lazily
when `/ce-brainstorm` first runs).

### Tests

363 `tests/` + 251 `fixtures/tests/` + 4 pressure tests all green.
+61 new tests for the synthesiser, +M11 catalog assertions in
`test_mcp_registry.py` and `test_capability_parity.py`.

## 2026.05.27+review7-plus2.1

Hotfix release — npm-distribution only. The 2.0 tarball published to npm
was missing the 94 `.py` module aliases (e.g. `bin/ce_playbook.py`) that
in the source tree are symlinks to the matching executables. npm dropped
the symlinks on pack without materializing them as file copies, so
`npx agent-learning-compounder --bootstrap-repo ...` blew up with
`ModuleNotFoundError: No module named 'ce_playbook'` at `alc_init` import
time.

The curl-one-liner and Claude Code marketplace paths were unaffected —
both consume the GitHub `archive/master.tar.gz` tarball, which preserves
symlinks.

Fix: `scripts/alc-install.mjs` (the npm `bin` entry) now materializes the
missing `.py` aliases as file copies at install time, scoped to shebanged
Python executables under `bin/`, `scripts/`, and `skills/alc-core/scripts/`.
Idempotent — skipped when the alias is already present (curl/GitHub path).

Anyone who installed `2026.5.27-review7.plus2.0` via `npx` should refresh
to `plus2.1`. Other install paths can stay on 2.0; the version bump on
MANIFEST.json / plugin.json / CLAUDE.md is for cross-channel sync only.

## 2026.05.27+review7-plus2.0

Install-surface release. Brings the package up to three first-class install
paths, makes the Claude Code plugin self-contained, and adds an `alc_init`
first-run flow that profiles the host repo, smokes the MCP server, and
writes a per-repo session context with compound-engineering playbook
hints tailored to the detected stack.

### New install paths

- **npm / npx.** `package.json` at repo root publishes the package as
  `agent-learning-compounder` with bin `alc-install` (`scripts/alc-install.mjs`,
  a thin Node wrapper around `install.sh`). Smoke-validated: `npm pack`
  → 414 KB tarball → `npm install` → `alc-install --plugin` lands a
  fully-wired plugin.
- **curl one-liner.** `bootstrap.sh` at repo root fetches the master
  tarball (overridable via `$ALC_REPO` / `$ALC_REF`) and exec's
  `install.sh` with forwarded args. Depends only on `curl` and `tar`.
- **Claude Code marketplace.** `.claude-plugin/marketplace.json` at repo
  root declares this repo as a single-plugin marketplace pointing at the
  inner `agent-learning-compounder/` directory. Enables
  `/plugin marketplace add beeard/agent-learning-compounder` →
  `/plugin install agent-learning-compounder@agent-learning-compounder`.

### Claude Code plugin made self-contained

- Adds `agent-learning-compounder/.mcp.json` declaring the `alc` stdio
  MCP server. Claude Code auto-starts the server on plugin load; smoke
  test (initialize + tools/list) returns 11 registered tools.
- `hooks/hooks.json` switches from `${ALC_PLUGIN_ROOT}` to
  `${CLAUDE_PLUGIN_ROOT}` (the variable Claude Code actually
  substitutes). Hook scripts (`session-start`, `refresh_dashboard.py`)
  and the `/alc-report` command resolve
  `${CLAUDE_PLUGIN_ROOT:-${ALC_PLUGIN_ROOT}}` so they remain safe in
  the Codex wrapper context.
- `plugin.json` gains author, repository, homepage, keywords for a
  professional marketplace presentation.

### First-run flow (`alc_init`)

- New `bin/alc_init` profiles the host repo (languages by extension,
  frameworks via file-presence signals, has-tests / has-frontend /
  monorepo / package-manager flags), checks for the `mcp` Python
  package (optional `pip install --user` via `--install-deps`), smokes
  `alc_mcp/server.py` over stdio, and writes a per-repo
  `latest-session-context.md` to the state directory.
- `install.sh --bootstrap-repo` auto-runs `alc_init` at the tail.
- `hooks/session-start` now cats `latest-session-context.md`
  alongside the gates and skill-context files at session start.
- Idempotent: re-running with the same args produces a byte-identical
  context file.

### Compound-engineering as soft dependency

- New `bin/ce_playbook` renders tailored hints for
  `/ce-brainstorm`, `/ce-plan`, `/ce-work`, `/ce-simplify-code`,
  `/improve-codebase-architecture`. Pairs detected frameworks with the
  right reviewer persona (Rails → `ce-dhh-rails-reviewer`; React/Next/
  Vue/Svelte/CF-Workers → `ce-kieran-typescript-reviewer`;
  Django/FastAPI/Flask → `ce-kieran-python-reviewer`).
- Detects whether the compound-engineering plugin is installed; if not,
  the playbook prepends a short install banner but the hints render
  unchanged so they remain useful as a workflow checklist.
- Conditional hints: monorepo, has_tests=false, and framework family
  each add or shape specific lines.

### Repo hygiene

- `FOLLOWUP.md` archived to `docs/history/FOLLOWUP-2026-05.md`
  (T1–T6 all addressed in the plus1.3 series).
- `GATE_SYSTEM_REVIEW.md` moved to
  `docs/dev/gate-system-review-2026-05.md` with an internal-backlog
  header. Open code-level review findings; not user-facing.
- Version drift fixed: `MANIFEST.json`, inner
  `agent-learning-compounder/.claude-plugin/plugin.json`, outer
  `CLAUDE.md`, README, marketplace.json all carry the same string.
- `README.md` rewritten — 342 → 106 lines. Pitch + three install paths
  in a table + "what it does" + safety model + docs index. Internals
  moved to `reference-lib/` and `docs/dev/`.
- New `LICENSE` (MIT) at repo root — required for npm publish and
  general open-source hygiene. Easy to swap.
- Fixed `agent-learning-compunder` typo (missing 'o') in README +
  QUICKSTART git-clone URLs.

### Tests

- 251 fixtures/tests/ (unit + integration) — all green.
- 219 tests/ (smoke) — adds `test_alc_init.py` (4 tests),
  `test_ce_playbook.py` (14 tests), updates `test_hooks.py`,
  `test_commands.py`, `test_cross_runtime.py` to match new
  env-var + plugin-shape conventions.
- 4 pressure checks.
- End-to-end validation suite (9 checks) covers every install path.

### Migration

`plus1.3` consumers should upgrade for the plugin shape fix (hooks
were silently no-op'ing in Claude Code plugin install). Run
`./install.sh --plugin` again or `npx agent-learning-compounder
--plugin` to refresh. Repo-bootstrapped installs gain `alc_init` +
session-context on next `--bootstrap-repo` run.

## 2026.05.26+review7-plus1.3

Installer feature release. Adds a `--plugin` mode to `install.sh` so the
skill package can be installed as a first-class Claude Code plugin
instead of (or in addition to) a skills-root install.

- `install.sh --plugin` installs the package under
  `${CLAUDE_HOME:-$HOME/.claude}/plugins/agent-learning-compounder`.
  Claude Code auto-discovers the plugin's agents, commands, hooks, and
  skills via the existing
  `agent-learning-compounder/.claude-plugin/plugin.json` manifest, so the
  flag is the only entry-point change required for plugin install.
  Implies `--runtime claude`; refuses to combine with `--bootstrap-repo`
  (which is a per-repo init flow, not a user-global plugin install).
- `.gitignore` gains `/.claude/scheduled_tasks.lock`, the Claude Code
  per-session PID lock. Mirrors the existing pattern for
  `/.claude/settings.local.json` — runtime state that should never enter
  the source tree.
- `scripts/sanitize_skill_tree.sh` now strips `node_modules/` and `dist/`
  directories during release staging in addition to the Python artifacts.
  The new `dashboard/web/` Vite app pulls in ~24 MB of pnpm deps and a
  Vite build output; without this, the release tarball ballooned from
  ~225 KB to ~24 MB. `.gitignore` gains a matching `node_modules/`
  pattern so the working tree stays clean too.

No behavior change inside `agent-learning-compounder/` (the inner skill
dir). `plus1.2` consumers do not need to upgrade unless they want the
new `--plugin` install entry.

## 2026.05.25+review7-plus1.2

Hygiene release. Ships the source-tree git history that backs `plus1.1` and
adds gitignore patterns useful for downstream installers; no functional
behavior change vs `plus1.1`.

- `.gitignore` gains patterns for the auto-generated hook config files
  `install_runtime_hooks.py` writes alongside the skill — `/.codex/hooks.json`,
  `/.claude/settings.local.json`, and their `.agent-learning-bak-*` siblings.
  These files carry absolute `$HOME` paths and should not be committed by
  downstream consumers; the upstream ignore patterns prevent that accidentally.
- Git history now includes `fix/mcp-stdio-1.0` merged to `master` so the MCP
  stdio fix shipped in `plus1.1` is also visible in the source tree
  (`master @ 42188b8`). The `plus1.1` tarball already contained the fixed
  code — `plus1.2` rebuilds with the committed-to-master state plus the
  `.gitignore` changes so the SHA-256 reflects the canonical source state.
- Adds `CLAUDE.md` at the repo root (contributor guide for the skill
  package's source tree). Outer-repo file; does not ship in the tarball
  staging dir.

No code or behavior changes in `agent-learning-compounder/` (the inner skill
dir). Consumers on `plus1.1` do not need to upgrade for functional reasons;
upgrade only if you want the improved `.gitignore`.

## 2026.05.25+review7-plus1.1

Patch release. Fixes a real bug in the MCP stdio entry point discovered
when registering `alc_mcp/server.py` against `mcp>=1.0`.

- `alc_mcp/server.py:main()` now wires `stdio_server()` as an async
  context manager and runs the server inside it. The prior form
  `asyncio.run(stdio_server(server))` assumed `stdio_server` was a
  coroutine; in `mcp>=1.0` it is a context manager that yields
  `(read_stream, write_stream)`, so the entry point raised
  `TypeError: An asyncio.Future, a coroutine or an awaitable is required`
  immediately on launch. Tool handlers were unaffected — only the stdio
  loop was broken.
- `alc_mcp/tests/test_server.py` gains `MCPStdioEntryPoint`, a
  subprocess-based regression that spawns the server, completes the MCP
  initialize handshake, calls `tools/list`, and asserts all four tool
  names (`get_gates`, `report_outcome`, `propose_gate`,
  `get_skill_context`) are exposed. Prior coverage exercised handlers
  in-process but never drove the stdio loop, which is how the bug
  reached a tagged release.

## 2026.05.24+review7-plus1

Eight-upgrade extension on top of `2026.05.24+review7-production`. All
upstream hardening properties preserved; additions are additive. See
`docs/history/PLAN-eight-upgrade.md` for the (now-frozen) implementation
work order.

Post-review fixes:
- `bin/gates_promote` and `bin/gates_inherit` now require 12 lowercase hex
  `gate_id` values before building shared-registry paths.
- `bin/gates_inherit` validates shared JSON records before appending markdown,
  including matching `gate_id` and rejecting newline-bearing fields.
- `install.sh` sanitizes copied installs after copy, compile checks, and
  optional verification so ignored cache artifacts are not shipped into target
  skill roots.
- Optional dependency docs now distinguish archive-root and installed-root
  `requirements-optional.txt` paths.
- Release packaging is now reproducible. The exclusion set previously inlined
  in `install.sh` lives in `scripts/sanitize_skill_tree.sh` and is sourced by
  both the installer and the new `scripts/build_release.sh`. Archives are
  rebuilt with sorted filenames, a fixed mtime, numeric ownership, and a
  gzip header with no embedded timestamp, so two runs produce byte-identical
  output. `dist/SHA256SUMS` now covers every archive in `dist/`.

New capabilities:
- **Phase 1 (schema versioning + replay):** `bin/collect_hook_event` now
  stamps `schema_version: 2` on every persisted row and allows
  `correlation_id` (bounded + scrubbed) and `gate_loaded_ids` (per-member
  capped) fields. `bin/replay_hook_events` migrates older logs to the
  latest schema, preserving original `ts` values.
- **Phase 2A (queue dedup):** `bin/queue_dedup` collapses semantically
  near-duplicate improvement-queue rows using character-trigram
  Sørensen-Dice (stdlib) or optional sentence-transformers backend.
  Wired into `refresh_learning_state` post-append.
- **Phase 2B (gate effectiveness):** `bin/export_gates` stamps a stable
  12-char `gate_id` (sha256 of domain|category|gate). `bin/evaluate_gate_effectiveness`
  computes correlation-only signals per gate (`correlated_with_success`,
  `correlated_with_failure`, `no_signal`, `needs_review`). Refresh queues
  low-impact gates as `gate_retirement_candidate` rows for operator review.
- **Phase 3A (domain rules learner):** `bin/propose_domain_rules` mines
  the session corpus for correction-correlated n-grams and queues them
  as `domain_rule_candidate` rows. Refresh-integrated.
- **Phase 3B (causal probes):** `bin/causal_probe` registers/decides
  deterministic A/B skip cohorts per gate. `probe_decisions` field added
  to v2 schema. `evaluate_gate_effectiveness` emits a `causal_signal`
  per gate when probe cohorts exceed N=5.
- **Phase 4 (cross-repo federation):** `bin/gates_promote` writes shared
  registry records; `bin/gates_inherit` appends shared gates to target
  repos with `derived_from:` provenance lines. Refresh auto-queues
  `inherited_gate_demote_candidate` for underperforming inherited gates.
- **Phase 5A (MCP server):** `alc_mcp/server.py` exposes `get_gates`,
  `report_outcome`, `propose_gate`, `get_skill_context` over stdio MCP.
  Optional `mcp` SDK dependency.
- **Phase 5B (operator dashboard):** `dashboard/` (FastAPI + Jinja2 +
  HTMX) + `bin/serve_dashboard` launcher serve a localhost-only view of
  gates, queue, and active probes. Optional fastapi/jinja2/uvicorn/httpx.

Test deltas: 105 → 166 fixture tests (+61 new). 4 SKIPs are gated on
optional deps. 1 smoke + 4 pressure scenarios still pass.

New references: `event-schema-evolution.md`, `queue-dedup.md`,
`gate-effectiveness.md`, `domain-rules-learning.md`, `cross-repo-gates.md`.

## 2026.05.24+review7-production

Post-review polish on top of `2026.05.24+review6-production`. One behavioral
change in the validator, plus the test that pins it.

Correctness:
- `bin/validate_outputs`: `_build_psych_re` now splits the verb list into
  state verbs (`is|er|are|was|were|has|have|had`) and judgment verbs
  (`lacks|shows|demonstrates|exhibits|displays|appears|seems|tends|mangler|
  evner ikke`). State verbs only fire when followed by an `adjective_tail`
  term, so neutral claims like "user is great" no longer trip the
  psychological-claim check. Judgment verbs still fire alone, preserving the
  existing `Foo.Bar shows weakness` metachars test. Existing positive cases
  ("user is weak at architecture", "brukeren er svak", "user lacks
  experience") continue to fail validation as before.

Tests:
- `fixtures/tests/test_validate_outputs_psych_tightening.py`: six cases
  pinning both directions of the tighten — `dårlig` (diacritical) matches,
  `darlig` (stripped) still matches, `user is great` does not fire,
  `user has skills` does not fire, `user is weak at architecture` still
  fires, `user lacks experience` still fires.

Documentation:
- `production-signoff` adds a basis line for the tightened validator.
- `README.md` and `production-signoff` versions bumped.

The full 105 fixture tests (was 99; +6 new), 1 smoke test, and 4
pressure-test scenarios pass.

## 2026.05.24+review6-production

Post-review polish on top of `2026.05.24+review5-production`. Behavior contract
unchanged; ten low-severity findings plus one follow-up permission finding
addressed.

Correctness and safety:
- `bin/distill_learning`: `quote()` now runs `scrub_secrets.scrub` before
  truncating, so a caller that bypasses `extract_sessions` (and its upstream
  scrub) cannot land secret-shaped text in the report; `quote_is_useful` then
  filters anything that picked up a `[REDACTED:*]` marker.
- `bin/refresh_learning_state`: `queue_candidate_adjustments` now counts rows
  dropped for containing secret-like content as `suppressed_redacted`; surfaced
  on stderr and in the result dict alongside `suppressed_needs_review`.
- `bin/collect_hook_event`: hook event log files are now created via
  `os.open(..., 0o600)`, eliminating the brief window between creation and the
  follow-up `chmod` during which a new file could be group/world-readable.
- `bin/init_learning_system`: bootstrap-created `hook-events.jsonl` now uses the
  same private `0o600` creation path, so the first real hook event cannot be
  written to a group/world-readable file created earlier by `touch`.

Code quality and consistency:
- `bin/build_repo_baseline`: `stack_evidence` now emits evidence for
  `package-lock.json`; previously it was listed in `STACK_FILES` but silently
  dropped by the inner condition.
- `bin/distill_learning`: `archive_report` collision suffix now uses UTC,
  matching every other timestamp in the package.
- `bin/install_runtime_hooks`: `command_exists` now compares shlex-tokenized
  commands so a rerun with equivalent-but-differently-quoted commands does not
  produce duplicate hook entries.
- `bin/validate_outputs`: added `dårlig` (diacritical Norwegian) to
  `adjective_tail`, so the psychological-claim regex matches the native
  spelling, not just the diacritic-stripped `darlig` form.
- `bin/evaluate_classifier`: replaced module-level `FIXTURE_DOMAIN_RULES` load
  with a lazy `fixture_domain_rules()` cache; importing the module no longer
  crashes if the packaged tm-norge preset is malformed or missing.
- `bin/collect_hook_event`: removed unused `DROP_KEYS` set; replaced with a
  comment explaining that `normalize_event`'s allowlist supersedes any
  blocklist at the entry point.
- `bin/map_active_skills`: documented the deliberate single-level
  `glob("*/SKILL.md")` versus `build_repo_baseline.skill_files`'s recursive
  `rglob("SKILL.md")`; the two are intentionally divergent (active skills vs.
  broader audit).

The full 99 fixture tests, 1 smoke test, and 4 pressure-test scenarios pass
unchanged.

## 2026.05.24+review5-production

Production hardening from independent multi-persona review of `2026.05.22+review5`.

Correctness and state model:
- `bin/state_paths`: docstring locks the documented 6-tier precedence
  (`--state-dir` → `AGENT_LEARNING_STATE_DIR` → `--personal` →
  `<repo>/.agent-learning` → `$XDG_STATE_HOME` → `~/.local/state`).
- `bin/init_learning_system`: `install_repo_integration` now warns on stderr
  when called without `--install-hooks` (prevents silently producing an
  `.agent-learning.json` missing the hook keys promised by README); `run_self_test`
  now parses `.agent-learning.json` and asserts the keys it claims, including
  hook keys when `--install-hooks` was used.
- `bin/refresh_learning_state`: reads `runtime` from `config.json` and threads
  it through `build_baseline`/`build_map`; `fcntl.LOCK_EX` on
  `improvement-queue.jsonl` around the read+append; `needs_review` rows still
  suppressed but counted and exposed via `suppressed_needs_review`; empty hook
  log surfaces `event_log_present: false` plus stderr notice.
- `bin/install_runtime_hooks`: `_manifest_expected_root` raises explicitly
  when config lacks `repo_state_dir` instead of silently falling back.

Safety hardening:
- `bin/scrub_secrets`: added patterns for GitLab PAT (`glpat-…`), HuggingFace
  (`hf_…`), AWS access key (`AKIA…`), Twilio SK/AC, Telegram bot token,
  basic-auth URLs, DB connection-string credentials, multi-line JSON value
  form; closed the short-token gap on `SENSITIVE_LINE_RE` matches.
- `bin/collect_hook_event`: `chmod 0o600` on first write; size-based rotation
  honoring `retention.max_hook_event_bytes`; capped backup count.
- `bin/validate_outputs`: widened verb list
  (`shows|demonstrates|exhibits|displays|appears|seems|tends|...`) and added
  adjective tail (`weak|poor|incompetent|...`); `re.escape` on subject names
  preserved.

Installer and dry-run gating:
- `install.sh`: renamed `runtime_root` loop-local to `dest_root` (was
  shadowing the same-named function — fragile in mksh); refuse symlink
  `$dest`/`$target_root`; backup collision suffix (`-2`, `-3`, …) on
  sub-second reruns.
- `install.sh`: runtime hint parsing no longer relies on non-portable awk
  `IGNORECASE`; `Runtime: Claude` and other case variants now resolve correctly
  under mawk and POSIX awk implementations.
- `bin/distill_learning`: dry-run refuses `--approved-gates-output` and
  `--skill-context-output` with exit 1; preserves the prior
  "inside-`--personal`" message wording.
- `bin/collect_hook_event`: retention now follows the generated state config
  referenced by `.agent-learning.json` before falling back to defaults, so
  bootstrapped `max_hook_event_bytes` settings control rotation.

Documentation:
- `README.md`: state-precedence rewritten as numbered list with repo-local
  marked as production default; one-command bootstrap now passes
  `--runtime "${AGENT_LEARNING_RUNTIME:-codex}"` to match what
  `install.sh --bootstrap-repo` does internally; Health Contract calls out
  hook keys.
- `SKILL.md`: same precedence + `--runtime` updates to First Use and
  One-Command Bootstrap.
- `README.md` and production signoff now describe the shipped tarball artifact
  and current `2026.05.24+review5-production` version.

Tests added: `test_state_paths_precedence.py`,
`test_init_self_test_failure_modes.py`, `test_scrub_secrets_extended_patterns.py`,
`test_collect_hook_event_rotation.py`, `test_validate_outputs_regex_metachars.py`.

## 2026.05.22+review5

Fixes from agent-help review of `2026.05.22+review4`.

- Added `references/agent-quickstart.md`, a compact deferred operating guide
  for LLM agents using the skill.
- Linked the guide from `SKILL.md` without expanding the main invocation
  instructions materially.
- README now points humans and agents to the dedicated agent-help surface.

## 2026.05.22+review4

Fixes from review of `2026.05.22+review3`.

- Domain distillation rules moved from `distill_learning.py` code into JSON
  data under `domain-rules/`.
- `generic` is now the portable default domain preset; the historical
  tm-norge/Quick3/Cloudflare/Teams rules are preserved as the packaged
  `tm-norge` preset.
- `init_learning_system.py` now writes `domain-rules.active.json` into the
  repo's agent-learning state and records it in `.agent-learning.json`.
- `distill_learning.py` now accepts `--domain-rules` and `--domain-preset`,
  auto-reading `.agent-learning.json` when a repo integration is present.
- Test coverage adds custom-domain-rule install, repo-config auto-discovery,
  invalid-rule refusal, and preset-specific distillation behavior.

## 2026.05.22+review3

Fixes from review of `2026.05.22+review2`.

- `init_learning_system.py --install-repo-integration` now treats
  `.agent-learning.json` as local integration config: in git repos it refuses
  to overwrite a tracked copy and auto-adds an untracked copy to `.gitignore`.
  This matches the existing runtime-hook protection for files containing
  absolute local paths.
- Refresh manifests are now scheduler-neutral in both key and install note
  (`scheduler_pattern`, external scheduler wording), removing the remaining
  Hermes cron coupling.
- The self-healing roadmap acceptance wording now says representative repo
  smoke instead of tm-norge-specific smoke.
- Test coverage adds ignored-config and tracked-config refusal cases for
  `.agent-learning.json`.

## 2026.05.22+review2

Fixes from review of `2026.05.22+review1`.

- `install_runtime_hooks.py --apply` now refuses to write repo-local hook
  config if the target config file is tracked by git. `.gitignore` cannot
  protect tracked files, so this fails before writing absolute-path adapter
  commands. Operators must untrack the config, keep it local/ignored, or use
  `--scope user`.
- Repo-local hook config backup files are now ignored with
  `.agent-learning-bak-*` globs alongside the config files.
- README install commands now use the actual `+review2` archive and extracted
  directory names, and document zip installation.
- The tarball and zip now use the same versioned top-level directory layout.
- Scratch-output examples now use a caller-created `RUN_DIR` instead of
  literal temp-file paths.
- Test coverage adds the tracked-config refusal case.

## 2026.05.22+review1

Review-round patches applied on top of the 2026.05.22 cut. No behavioral
breaking changes for existing installs; all 51 tests pass (was 48, plus 3
new tests for the changes below).

### Portability

- `validate_outputs.py` no longer hard-codes a single operator name in its
  psychological-claim regex. Default subjects are `user` and `brukeren`.
  Operators with personal deployments can extend the list via the
  `AGENT_LEARNING_SUBJECT_NAMES` env var (comma- or whitespace-separated;
  entries are `re.escape`'d). Documented in `README.md`.
- "Hermes cron" references in `SKILL.md` and the self-healing roadmap were
  generalized to "external scheduler (cron, systemd timer, launchd, or any
  equivalent)". The "Hermes Patterns Applied" header in the roadmap was
  renamed to "Design Patterns Applied"; the patterns themselves are not
  Hermes-specific. Hermes remains documented in `source-adapters` and
  `distill-sessions` as a *supported* runtime to extract sessions from —
  that is correct and was not changed.

### Safety

- `install_runtime_hooks.py --apply` with repo scope now auto-appends the
  hook config paths to the repo's `.gitignore` when a `.git/` directory is
  present. Prevents accidentally committing absolute `$HOME` paths from
  the adapter command. No-op when not a git repo. Idempotent. Two new
  tests cover both paths.
- `references/threat-model.md` now documents the aggressive UUID
  redaction policy and the runtime-hook `$HOME`-leak mitigation so
  operators aren't surprised.

### Documentation

- New `## Layout And Conventions` section in `README.md` explaining the
  `bin/<name>` + `bin/<name>.py` + `scripts/<name>.py` triple-name
  convention (which is required by Python's import system, not redundant
  as one might initially think), the parallel `reference-lib/` and
  `references/` split, and the difference between `tests/` (smoke) and
  `fixtures/tests/` (unit + eval).
- New `## Configurable Subject Names` section documenting the env var.
- New `## Safety Notes On Runtime Hooks` section documenting the
  `.gitignore` auto-write.

### Runtime symmetry

- New `agents/claude.yaml` mirroring `agents/openai.yaml`. Claude Code
  does not yet consume a manifest of this shape (discovery is via
  `SKILL.md`), but the parallel file is in place for when it does, and
  removes the cognitive asymmetry of "OpenAI gets a manifest, Claude
  does not".

### Test count

- 48 → 51 tests (kept three new ones across the changes above).
- The "Tom is weak at architecture" fixture in
  `test_validate_outputs_blocks_secrets_and_unsupported_claims` was
  updated to use the generic "user" subject, since the validator's job
  is to catch the category of claim, not specifically Tom.

### Not changed (deliberately)

- `bin/<name>.py` symlinks were initially proposed for removal in the
  review. They are required: cross-script imports like
  `from scrub_secrets import scrub` look for `.py` files on `sys.path`,
  so removing the symlinks breaks every script that imports a sibling.
  Documented in the new README section instead.
- `tests/` vs `fixtures/tests/` were not consolidated. Both directories
  have distinct purposes (smoke vs unit+eval) and existing tests use
  `__file__.parents[N]` path math that would silently shift on a move.
  Documented in the new README section instead.
- `map_active_skills.py` already scans `~/.claude/skills/`. The review
  noted this as missing; that observation was incorrect on closer
  reading. No change.
