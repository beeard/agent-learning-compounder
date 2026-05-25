# Threat Model

Skill files, session transcripts, runtime hook payloads, and environment state are
all attack surface. The security posture is contract-first: every persistence or
execution edge must have a validation rule and an explicit operator control.

## Threats

- prompt injection in transcripts, docs, web pages, or imported skills,
- semantic skill-selection attacks through enticing descriptions,
- stale memory overriding current repo truth,
- secret persistence or identifier leakage,
- hook telemetry becoming raw transcript storage,
- durable context flooding from unbounded reports or logs,
- durable personalization polluted by unsupported claims.

## Core Security Guarantees

### 1) No absolute out-of-repo telemetry paths

Hook/event persistence should never embed absolute paths that leak host layout
outside the target repo. Telemetry `path` fields should be repo-relative or
explicitly dropped.

### 2) No arbitrary absolute `@include`

Instruction includes are only allowed when:

- include target is relative,
- target resolves inside the active repo,
- include depth stays within instruction limits.

Absolute include directives must be rejected.

### 3) Hook command integrity validation

Runtime hook execution must only use adapter commands that are:

- absolute paths,
- executable regular files,
- non-symlinks,
- and matching the repo-local hook manifest command contract.

Manifest/config divergence is treated as a hard error.

### 4) Symlink-safe append writes

All append targets for queue, hook-events, and manifest outputs must be regular
files, not symlinks, to avoid path pivoting.

### 5) Explicit transcript consent for automation

Hook telemetry and refresh manifests are inert until the operator registers them in
an external scheduler. No built-in cron/userland scheduler registration should occur
implicitly.

## Controls

- read-only default,
- no network access as part of the default flow,
- explicit `--write` for append behavior,
- `validate_outputs.py` before durable writes,
- bounded hook-event normalization before persistence,
- compact `latest-approved-gates.md` and `latest-skill-context.md` as the only
  session-start load surfaces,
- source labels for current, memory-derived, and unverified facts,
- short `SKILL.md`; heavy guidance in references; deterministic parsing in scripts.

## Defensive Defaults

- `scrub_secrets.py` redacts UUID-shaped values unconditionally because many
  session IDs, request IDs, and file GUIDs are identity-correlated.
- In git repos, `init_learning_system.py` refuses to overwrite tracked integration
  config and adds local pointers to `.gitignore` as a non-leaking default.
- In git repos, `install_runtime_hooks.py` refuses to overwrite tracked runtime
  config files and writes repo-local runtime-config paths (with backup globs) into
  `.gitignore`.
