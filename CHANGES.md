# Changes

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
