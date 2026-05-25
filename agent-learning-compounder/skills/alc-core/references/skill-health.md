# Skill Health

Skill health is expected-vs-observed workflow evidence.

## Pipeline

```text
map_active_skills.py
-> evaluate_skill_routing.py
-> extract_skill_usage.py
-> evaluate_skill_impact.py
-> export_skill_context.py
```

## Signals

- `available`: skill exists in the active inventory.
- `expected`: scope, gates, or repo rules indicate the skill should apply.
- `loaded`: hook evidence or file-read evidence shows the skill instructions were loaded.
- `applied`: event evidence shows the required gate or workflow happened.
- `missed`: expected but not loaded.
- `failed`: loaded/applied/missed and followed by correction, validation failure, or scope failure.

## Reporting Language

Allowed:

- `correlated_with_success`
- `correlated_with_failure`
- `missed_expected_skill`
- `loaded_but_not_applied`
- `needs_review`
- `candidate_skill_adjustment`

Avoid causal overclaims such as "skill caused failure", model psychology, global capability labels, and claims without source, count, or verify evidence.

## Loadable Export

Only this compact export should be read by future session-start:

```text
reports/agent-learning/latest-skill-context.md
```

It may contain required skills, health alerts, and candidate adjustments. It must not contain raw prompts, raw tool outputs, transcript text, or secret markers.
