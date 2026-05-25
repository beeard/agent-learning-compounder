# Output Schema

Use one report per run. Archive written reports under:

```text
<personal-repo>/reports/agent-learning/YYYY-MM-DD.md
```

If a same-day report already exists, suffix with `-2`, `-3`, and so on. Never overwrite an old report. The skeleton lives in `assets/report-template.md`; use it instead of inventing a new structure.

## Required Buckets

Every claim belongs to exactly one bucket and carries its literal marker.

### `confirmed_current`

Verified in the current run from repo files, read-only commands, generated baselines, or current transcript extraction.

Each line includes a concrete source path, command, or extraction metadata source. Vague sources such as `source: baseline` are rejected because they make current repo truth unauditable.

```text
- [confirmed_current] The repo loads local skills before substantial work. source: AGENTS.md:12
- [confirmed_current] Session extraction metadata: sampled_sessions selected=50 total=120 strategy=oldest10_middle15_newest25. source: corpus metadata
```

### `memory_derived`

Derived from prior reports, memories, or session evidence. Useful, but not current repo truth.

Each line includes an origin, quote, or named evidence count:

```text
- [memory_derived] Recent sessions show repeated requests for live deploy verification. source: distill-sessions, evidence: 4 matching user lines
```

### `needs_verification`

Plausible but not confirmed. Include the exact check that would confirm or refute it.

```text
- [needs_verification] The deploy gate may have changed. verify: read AGENTS.md and package scripts in the current checkout.
```

### `agent_compensation`

Actionable gates future agents must run before acting in a domain.

```yaml
- domain: cloudflare
  marker: agent_compensation
  category: live-check
  gate: "Before claiming a deploy is healthy, run the repo-approved verification command and quote one non-secret line."
```

### `self_healing_loop`

Shows how a repeated failure signal becomes an agent gate that is loaded into future work.

```text
- failure_signal -> candidate_gate -> validation_status -> next_session_load. source: corpus
- strongest_current_gate: validation requires `validation-check` before action. source: baseline and corpus
```

## Skill-System Buckets

Roadmap-enabled reports may include these additional compact sections:

- `skill_inventory`: available, invalid, duplicate, or missing-resource skill counts from `map_active_skills.py`.
- `skill_usage`: expected, loaded, applied, missed, and failed skill sets from `extract_skill_usage.py`.
- `skill_health`: invalid, missed, or loaded-but-not-applied alerts. Every bullet needs `source:`, `count:`, or `verify:`.
- `skill_compensation`: candidate skill-routing or skill-instruction adjustments from `evaluate_skill_impact.py`.

These sections are evidence summaries. They must not include raw hook payloads, raw prompts, raw tool outputs, or transcript text.

## Rejection Rules

Reject reports containing:

- `## Unsupported Claims`
- raw secret-shaped content
- `[REDACTED` markers, because the report should paraphrase or count instead
- personality, psychological, or generic ability labels
- entries without `source:`, `quote:`, `origin:`, `count:`, or `verify:`
- global user levels instead of per-domain levels
- reports without `self_healing_loop`
- bare `repeat_count` values, because the current classifier measures matching lines unless a session-level denominator is available
- `confirmed_current` entries that cite only `source: baseline`, `source: corpus`, or `source: baseline and corpus`
- raw hook payloads, raw prompts, raw tool outputs, or tool-output dumps
- causal skill overclaims such as "skill caused failure"
- `skill_health` bullets without source/count/verify evidence

## Append Behavior

`--write` must:

- validate the generated report first,
- archive it under `reports/agent-learning/`,
- export a compact approved-gates registry, defaulting to `reports/agent-learning/latest-approved-gates.md`,
- export compact active skill context, defaulting to `reports/agent-learning/latest-skill-context.md`,
- append deduped dated entries to `insights.md` and `learning.md`,
- preserve evergreen personal files such as `soul.md`, `system.md`, and `preferences.md`,
- never overwrite prior reports.

Durable entries are one line, dated, and evidence-backed:

```text
[YYYY-MM-DD] Observation with operational consequence. (source: "short quote")
```

## Cross-Report Continuity

Future runs should read the latest report before starting if one exists. Prefer sessions newer than the last report date and flag domains where the level shifted, for example `level_change: 2 -> 3`.

Future agents should read `latest-approved-gates.md` when it exists before acting on the same repo/domain. That registry is the loadable self-healing surface; full reports remain archives.

Reports may include `## proposed_evergreen_diffs` when current evidence
conflicts with evergreen personal files. This section is proposal-only: never
edit `soul.md`, `system.md`, or `preferences.md` automatically.

## Length Budget

Aim for under 400 lines. If the report exceeds 600 lines, compress prose into terse bullets with source paths.

## What Reports Are Not

- Not a journal entry.
- Not coaching for the user.
- Not Claude-specific or Codex-specific.
- Not a session transcript dump.
