# agent-learning-compounder (Claude entrypoint)

This is the Claude Code plugin entry for `agent-learning-compounder`.

## Core commands

- `/alc-report` — run the full learning report pipeline via `scripts/render_unified_report.py`.
- `init_learning_system` — bootstrap repository state and hooks in one command.
- `render_unified_report` — run the full report chain with optional automation flags.

## MCP tools

- `get_gates`
- `get_skill_context`
- `propose_gate`
- `report_outcome`

## Operating rules

### State and scope

- Use command entrypoints in the `scripts/` directory, not direct internal modules.
- Keep repo mutation paths inside `agents/`, `skills/`, `commands/`, and configured state roots.

### Output policy

- Prefer durable report outputs (`latest-approved-gates.md`, `latest-skill-context.md`) over raw transcripts.
- Never include secrets, absolute paths, or unbounded transcript chunks in command outputs.
