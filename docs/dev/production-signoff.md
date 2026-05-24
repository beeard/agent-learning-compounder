# Production Signoff

Package: `agent-learning-compounder`
Version: `2026.05.24+review7-plus1`
Date: `2026-05-24`

## Decision

Status: `APPROVED_FOR_PRODUCTION_USE`

## Eight-Upgrade Extension (review7-plus1)

This version layers eight extensions on top of review7-production. All upstream
hardening properties are preserved; the upgrades are additive.

| Phase | Upgrade | Surface |
| --- | --- | --- |
| 1 | Hook event schema versioning + replay | `bin/collect_hook_event` v2, `bin/replay_hook_events` |
| 2A | Improvement-queue semantic dedup | `bin/queue_dedup`, post-append in `refresh_learning_state` |
| 2B | Per-gate effectiveness scoring + retirement candidates | `bin/evaluate_gate_effectiveness`, `gate_id` in `export_gates`, refresh wiring |
| 3A | Domain-rules mining | `bin/propose_domain_rules`, refresh wiring |
| 3B | Causal A/B probes | `bin/causal_probe`, `probe_decisions` field in v2 schema, causal_signal in effectiveness |
| 4 | Cross-repo gate federation | `bin/gates_promote`, `bin/gates_inherit`, auto-demote in refresh |
| 5A | MCP server | `alc_mcp/` (stdio; optional `mcp` SDK dependency) |
| 5B | Operator dashboard | `dashboard/` + `bin/serve_dashboard` (optional fastapi/jinja2/uvicorn) |

Tests: 160 fixture tests (was 105 in review7-production; +55) plus 1 smoke
and 4 pressure scenarios pass on the production-eligible branch. The 4 SKIPs
in the fixture suite are tests gated on optional deps (`mcp`, `fastapi`,
`jinja2`, `httpx`) that are not installed by default; they pass when the
extras are present.

The frozen implementation work order at `docs/history/PLAN-eight-upgrade.md`
captures all eight upgrades with implementation-ready depth, including TDD
steps, acceptance criteria, and dependency sequencing.

This signoff applies to the portable tarball package produced from this tree
after the production-hardening audit. The approved operating mode is project-local:
unpack the archive, run `install.sh --bootstrap-repo <repo>`, keep generated
state under `<repo>/.agent-learning`, and apply runtime hooks only through the
explicit `--apply-runtime-hooks` flag.

## Quality Score

Score: `9.1/10`

Basis:

- Runtime skill roots are isolated by runtime. Codex does not import
  `.claude/skills` as Codex skills, and Claude does not import `.agents/skills`
  as Claude skills unless runtime `all` is explicitly requested.
- Default state is project-local and contained under `.agent-learning`.
- One-command bootstrap installs, scaffolds integration state, writes hook
  manifests, and runs self-test.
- Runtime hook writes are dry-run by default and require explicit apply.
- Hook command execution is integrity-checked against the repo-local manifest.
- Telemetry rejects symlink append targets and redacts out-of-repo absolute paths.
- Absolute and out-of-repo `@include` directives are rejected.
- Architecture, onboarding, threat model, and hardening plan are packaged.
- Psychological-claim validator (review7) requires an adjective_tail term
  after state verbs, so neutral "user is X" claims no longer false-positive
  while explicit deficiency claims still fail validation.

## Verification Evidence

Required checks before final package publication:

- `python3 -m unittest discover -s fixtures/tests`
- `python3 -m unittest discover -s tests`
- `python3 scripts/run_pressure_tests.py`
- Clean extraction of the final tarball artifact.
- `./install.sh --bootstrap-repo <fresh-repo> --runtime codex --verify`
- `./install.sh --bootstrap-repo <fresh-repo> --runtime codex --verify --apply-runtime-hooks`
- Tarball inspection confirms a single top-level directory and no generated
  cache or runtime-state files.

## Residual Risks

- Scheduler installation remains manifest-only by design. Operators must
  explicitly register `agent-learning-refresh.manifest.json` with their scheduler.
- The package archive is built locally from this tree; future releases should keep a
  checked-in packaging command or release script to make the archive build fully
  reproducible.
- User-scope hook installation exists but should remain an explicit operator
  choice; repo-scope bootstrap is the production default.

## Approval

Approved by: `Codex multi-persona production audit`
Approval type: `evidence-gated local package signoff`
