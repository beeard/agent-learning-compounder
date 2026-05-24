# Production Hardening Plan

This is the execution plan for `agent-learning-compounder` production hardening.
Scope is documentation-first for this review slice, with clear evidence gates and
9/10 quality acceptance criteria.

## 9/10 Quality Gates (hard quality target)

Release is considered production-ready for this slice when all of the following are
true:

1. 0 unaddressed critical findings and no remaining high findings from the audit.
2. Health contract surfaces exist and are loadable at repo start.
3. Hardening controls are enforced through readback-validated commands, not by
   README text alone.
4. All new behavior is represented in references with testable evidence paths.
5. At least one explicit installer/operator dry-run and one explicit apply action are
   documented and reproducible.

## Phase 1: Audit and Evidence Consolidation (4 steps)

1. Catalog the current findings from the audit:
   runtime-root leakage, state-root default, hook manifest-only flow, uninstall/
   upgrade/rollback, health contract gaps, include/hook/symlink controls.
2. Map each finding to:
   - owning document (`README.md`, `SKILL.md`, `agent-quickstart`, `threat-model`,
     `hook-telemetry`, `architecture`, `production-hardening-plan`)
   - evidence path and owning command (for example `collect_hook_event`,
     `install_runtime_hooks`, `init_learning_system`).
3. Add a versioned hardening checklist to `production-hardening-plan` and include
   success evidence tags (`passed`, `blocked`, `not-started`).
4. Publish a health-coverage matrix that explicitly names which artifacts prove
   each phase can start.

Evidence gates:

- `agent-learning-compounder/reference-lib/architecture` exists.
- `docs/dev/production-hardening-plan.md` exists.
- Existing manifest and default command contracts are referenced from
  `references/*.md` pages and SKILL.

## Phase 2: Code-Path Hardening and Contract Clarification (5 steps)

1. Standardize runtime state-default language around repository-local default
   `.agent-learning` and remove ambiguity about absolute path leakage in docs.
2. Define manifest-only scheduler semantics as normative behavior:
   write manifest, no implicit scheduler registration.
3. Codify security guarantees in docs and threat references:
   - no absolute out-of-repo telemetry paths,
   - no arbitrary absolute `@include`,
   - hook command integrity checks,
   - symlink-safe append/write behavior,
   - explicit automation consent for transcript-derived work.
4. Document uninstall, upgrade, and rollback behaviors with exact directory and
   config cleanup sequence.
5. Add explicit lifecycle health-contract checks for each major surface
   (`.agent-learning.json`, latest exports, hook manifest, refresh manifest).

Evidence gates:

- `references/threat-model.md` contains the required security guarantees.
- `references/hook-telemetry.md` documents symlink-safe append rules and no leak
  path policy.
- `references/agent-quickstart.md` explains one-command bootstrap and explicit runtime
  hook apply.

## Phase 3: Validation and Readback Tests (4 steps)

1. Update the documented runbook so every durable write has a readback check.
2. Add explicit readback check commands for bootstrap, hook apply, and manifest
   registration.
3. Define failure handling for readback mismatch (re-run plan, abort automation).
4. Require self-test and pressure test checks before signoff.

Evidence gates:

- `init_learning_system.py --self-test` checks required state artifacts.
- `install_runtime_hooks.py --dry-run` output reviewed before `--apply`.
- `install_runtime_hooks.py --apply` output + repo config readback checked for expected
  absolute command + hook events wrapper.
- `collect_hook_event.py` append path check documented and verified as non-symlink.

## Phase 4: Packaging and Lifecycle Documentation (3 steps)

1. Add reference documents and symlink surfaces in `references/`.
2. Add release lifecycle docs:
   - install,
   - uninstall,
   - upgrade,
   - rollback,
   - hook/scheduler semantics.
3. Ensure architecture and plan docs are discoverable from `README.md` and
   `SKILL.md`.

Evidence gates:

- `references/architecture.md` exists as symlink to canonical source.
- `docs/dev/production-hardening-plan.md` lives outside the shipped skill.
- `README.md`, `SKILL.md`, and `references/agent-quickstart.md` link to both.

## Phase 5: Signoff (3 steps)

1. Run the documented hardening acceptance checks from this plan and capture
   output paths in session notes.
2. Reconcile remaining risk items; unresolved risks must have owner + mitigation
   + date.
3. Mark package health contract as `PASS` only when:
   - all required artifacts are present,
   - installer/hook/apply flow matches manifest contract,
   - and automation is only active through explicit scheduler action.

Evidence gates:

- One pass of documented checks without destructive edits.
- No docs-only claims without command or output evidence.
- Final signoff checklist signed by operator with a date.

## Hardening Outcomes by Bucket

- **Audit bucket**: every finding has a direct doc anchor and runbook step.
- **Security bucket**: no silent global hook writes, no absolute root leakage,
  symlink-safe writes, include-path control, consented automation.
- **Operational bucket**: one-command bootstrap, lifecycle cleanup, deterministic
  health verification.
- **Maintenance bucket**: one canonical architecture + one hardening plan + one
  threat/security reference.
