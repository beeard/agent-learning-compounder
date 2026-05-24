# Self-Healing Roadmap

Target: turn `agent-learning-compounder` from session report generation into a self-healing skill system that can evaluate active skills, their use, and their observed session impact.

Status: implemented as a portable state subsystem. Use `scripts/init_learning_system.py` for first use, then load only compact `latest-approved-gates.md` and `latest-skill-context.md` in future sessions.

## System Model

```text
active repo
-> programmatic skill map
-> hook/session skill usage extraction
-> skill impact evaluation
-> approved gates + skill context exports
-> session-start/session-end loading
```

The goal is not more memory. The goal is fewer repeated agent failures.

## Design Patterns Applied

- Profile-scoped state: every repo gets a deterministic state directory under the selected state root.
- Hooks as event bus: hook wrappers append bounded JSONL only.
- Runtime hook installer: missing Codex/Claude hooks are added only through an explicit dry-run/apply command that preserves existing config.
- Script-only cron readiness: init writes an automation manifest for a no-agent refresh routine, but does not mutate any live scheduler (cron, systemd timer, launchd, Hermes, etc.).
- Kanban-style queue: refresh appends deduplicated candidate skill adjustments to `improvement-queue.jsonl`.
- Compact future context: session-start loads latest gates/context, not the raw queue or hook log.

## Phase 1: Hook Telemetry

Add:

```text
scripts/collect_hook_event.py
references/hook-telemetry.md
fixtures/tests/test_hook_telemetry.py
```

Collector requirements:

- Append-only JSONL.
- Scrub secrets before persistence.
- Tolerate unknown hook events.
- Never persist raw full prompts, raw tool outputs, or unbounded payloads.
- Normalize paths and runtime names.

Useful Claude Code events:

- `InstructionsLoaded`
- `UserPromptExpansion`
- `PreToolUse`
- `PostToolUse`
- `PostToolUseFailure`
- `SubagentStart`
- `SubagentStop`
- `Stop`
- `SessionEnd`
- `ConfigChange`
- `FileChanged`

## Phase 2: Active Skill Map

Add:

```text
scripts/map_active_skills.py
references/skill-health.md
fixtures/tests/test_skill_mapping.py
```

Scan:

```text
.agents/skills/*/SKILL.md
.claude/skills/*/SKILL.md
~/.agents/skills/*/SKILL.md
AGENTS.md skill-loading rules
```

Output:

```json
{
  "repo": "/path/to/repo",
  "skills": [],
  "duplicates": [],
  "invalid": [],
  "missing_dependencies": []
}
```

Track per skill:

- `name`
- `path`
- `scope`
- `valid`
- `description`
- `hash`
- `mtime`
- `references_ok`
- `scripts_ok`
- `priority`

## Phase 3: Expected Skill Routing

Add:

```text
scripts/evaluate_skill_routing.py
fixtures/eval-fixtures/skill_routing.json
fixtures/tests/test_skill_routing.py
```

Inputs:

- user scope or prompt
- active skill map
- approved gates
- AGENTS.md rules

Output:

```json
{
  "expected": ["session-start", "port-vocab-gate"],
  "reason": "scope touches packages/ports/**",
  "missing": [],
  "confidence": "high"
}
```

## Phase 4: Skill Usage Extraction

Add:

```text
scripts/extract_skill_usage.py
fixtures/tests/test_skill_usage.py
```

Detect:

- `available`: skill exists in the mapped skill inventory.
- `expected`: scope/gates/rules indicate the skill should apply.
- `loaded`: evidence shows instructions or `SKILL.md` were loaded.
- `applied`: evidence shows the required skill steps/gates were followed.
- `missed`: expected but not loaded or applied.
- `failed`: loaded/applied but followed by correction, validation failure, or scope failure.

Potential evidence:

- `InstructionsLoaded` hook events.
- reads of `*/skills/*/SKILL.md`
- slash command expansion events
- subagent start/stop events
- validation commands
- user corrections
- session-end reason/outcome

## Phase 5: Skill Impact Evaluation

Add:

```text
scripts/evaluate_skill_impact.py
fixtures/tests/test_skill_impact.py
```

Report correlation, not hard causality:

```json
{
  "skill": "session-start",
  "expected_sessions": 12,
  "loaded_sessions": 9,
  "missed_sessions": 3,
  "corrections_after_loaded": 1,
  "corrections_after_missed": 3,
  "impact_signal": "missed_expected_skill_correlates_with_scope_correction",
  "confidence": "medium",
  "candidate_adjustment": "session-start must read latest-approved-gates.md"
}
```

Allowed language:

- `correlated_with_success`
- `correlated_with_failure`
- `missed_expected_skill`
- `loaded_but_not_applied`
- `needs_review`
- `candidate_skill_adjustment`

Avoid:

- `skill caused failure`
- psychological claims
- unsupported global capability claims

## Phase 6: Export Skill Context

Add:

```text
scripts/export_skill_context.py
fixtures/tests/test_skill_context_export.py
```

Output:

```text
reports/agent-learning/latest-skill-context.md
```

Shape:

```md
# Active Skill Context

## required_at_session_start
- latest-approved-gates.md
- session-start
- next-session when scope is empty

## skill_health_alerts
- invalid: <skill path>
- missed_expected_skill: <skill name>
- loaded_but_not_applied: <skill name>

## candidate_adjustments
- Add gate: <specific future-agent action>
```

The export must exclude raw hook payloads, raw tool outputs, long prompts, and raw transcript content.

## Phase 7: Distill Integration

Extend `distill_learning.py` and validation schema with:

```md
## skill_inventory
## skill_usage
## skill_health
## skill_compensation
```

New gate categories:

- `skill-routing`
- `skill-health-check`
- `loaded-but-not-applied`
- `missing-required-skill`

Validator requirements:

- no raw hook payloads
- no raw tool output
- source/count/verify evidence for skill-health claims
- no causal overclaiming

## Phase 8: Session-Start Integration

Update repo-local `session-start` rules:

```text
Read latest-approved-gates.md and latest-skill-context.md when present.
If required skill is missing, invalid, or stale, mark needs_verification before planning.
If scope matches a required skill gate, load that skill before plan.
```

This is where self-healing becomes active in the next session.

## Phase 9: Session-End Integration

Update repo-local `session-end` rules:

```text
At closeout, record expected/loaded/applied skill signals if hook telemetry exists.
If validation failure or user correction happened, leave a skill-health signal for agent-learning.
```

Only counters and structured signals should be persisted. Do not persist raw transcript text.

## Phase 10: Evals And Pressure Tests

Add:

```text
fixtures/eval-fixtures/skill_health.json
fixtures/eval-fixtures/hook_events.jsonl
fixtures/tests/test_skill_health_pipeline.py
```

Targets:

- skill-routing precision/recall >= 0.90
- classifier precision/recall >= 0.95 remains green
- hook extraction safe under secret-shaped payloads
- exports contain no raw prompts, raw tool outputs, quotes, or secret markers
- dry-run never writes into personal
- `--write` exports both:
  - `latest-approved-gates.md`
  - `latest-skill-context.md`

## 9.5 Acceptance Criteria

The skill can be called 9.5/10 when:

- Programmatic active skill map exists.
- Hook telemetry can be imported safely.
- Expected vs loaded vs applied skill state is computed.
- Skill impact is reported as correlation, not causality.
- `latest-skill-context.md` is exported.
- `session-start` reads `latest-approved-gates.md` and `latest-skill-context.md`.
- `session-end` can feed skill-health signals back.
- At least 40 total eval cases exist across classifier, routing, hook extraction, and skill-health.
- Full test suite passes.
- Real smoke in a representative repo produces report, approved gates, and skill context with no secrets or raw hook payloads.
