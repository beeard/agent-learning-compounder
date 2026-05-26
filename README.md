# agent-learning-compounder

> Durable, evidence-backed agent memory. Distills repo facts, session telemetry,
> and skill-health signals into compact context future agents actually read.

[![Release](https://img.shields.io/badge/release-2026.05.27+review7--plus2.1-blue)](CHANGES.md)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-stdio-orange)](agent-learning-compounder/.mcp.json)

ALC turns the noisy ambient signals around your project — git baseline, session
transcripts, hook events, recommendation outcomes — into two compact surfaces
future agents read on every session:

- `latest-approved-gates.md` — durable do/don't rules, scored by effectiveness
- `latest-skill-context.md` — repo-specific skill routing hints

It ships as a self-contained package that installs three ways: **npm/npx**,
**curl one-liner**, or **Claude Code plugin** (marketplace or direct).
After install, `alc init` profiles the host repo, smokes the MCP server,
and writes a per-repo session context with compound-engineering playbook
hints tailored to the detected stack.

## Install

| Path | Command | Best for |
| --- | --- | --- |
| **npm / npx** | `npx agent-learning-compounder` | Anyone with Node 18+. Zero-config: detects Codex/Claude runtime, installs to the right root, runs the test suite. |
| **curl one-liner** | `curl -fsSL https://raw.githubusercontent.com/beeard/agent-learning-compounder/master/bootstrap.sh \| sh` | No Node. Fetches the master tarball, runs the same installer. |
| **Claude Code plugin** | `/plugin marketplace add beeard/agent-learning-compounder` then `/plugin install agent-learning-compounder@agent-learning-compounder` | Claude Code users who want hooks + MCP + slash commands wired automatically. |
| **Git clone** (legacy) | `git clone https://github.com/beeard/agent-learning-compounder.git && ./agent-learning-compounder/install.sh` | Full source for inspection or contribution. |

All paths land the same artifacts and pass the same self-tests. Forward any
`install.sh` flag through `npx` or the curl pipe — for example, to also
bootstrap your current repo in one step:

```bash
npx agent-learning-compounder --bootstrap-repo "$PWD" --verify
```

See [`docs/QUICKSTART.md`](docs/QUICKSTART.md) for the beginner walk-through.

## What it does

- **Repo baseline** — `bin/build_repo_baseline` snapshots structure, tests,
  hot files, ownership signals into one JSON.
- **Session distillation** — `bin/extract_sessions` + `bin/distill_learning`
  turn recent transcripts into proposed gates and skill-routing facts (raw
  transcripts are never persisted).
- **Hook telemetry** — `bin/collect_hook_event` writes bounded, allowlisted
  events to `hook-events.jsonl`. `bin/replay_hook_events` migrates old
  schemas; `bin/queue_dedup` collapses near-duplicate proposals.
- **Gate scoring & federation** — `bin/evaluate_gate_effectiveness`,
  `bin/causal_probe`, `bin/gates_promote`, `bin/gates_inherit` give each
  gate a stable 12-char id and a cross-repo lifecycle with provenance.
- **MCP surface** — `alc_mcp/server.py` exposes `get_gates`,
  `get_skill_context`, `get_recommendations`, `propose_gate`,
  `report_outcome`, and 6 more tools over stdio. Auto-starts in Claude Code
  via [`.mcp.json`](agent-learning-compounder/.mcp.json).
- **Dashboard** — `bin/serve_dashboard` (FastAPI + HTMX) for operator
  triage of pending recommendations.

## Requirements

- Python 3.10+
- POSIX shell (macOS / Linux / WSL)
- Optional: `mcp`, `fastapi`, `jinja2`, `uvicorn`, `httpx`,
  `sentence-transformers` — install via
  `pip install -r agent-learning-compounder/requirements-optional.txt` if you
  want the MCP server, dashboard, or embedding-backed queue dedup.

## Safety model

- **No raw prompts, tool output, transcript chunks, or secret markers are
  persisted.** Telemetry has a bounded allowlist; the validator rejects
  psychological/ability claims about the operator.
- **Default to read-only.** `distill_learning.py` mutates durable memory only
  with `--write` + `--personal` root.
- **Installer never touches tracked files.** `.agent-learning.json` and
  runtime hook configs (`.codex/hooks.json`,
  `.claude/settings.local.json`) auto-`.gitignore` themselves; install
  refuses to overwrite if already tracked.
- **Runtime hook install is manifest-only by default.** Apply requires an
  explicit `install_runtime_hooks.py --apply` after a dry-run.

## Documentation

- [`CHANGES.md`](CHANGES.md) — release notes
- [`docs/QUICKSTART.md`](docs/QUICKSTART.md) — first-time install walk-through
- [`docs/llm-install-prompt.md`](docs/llm-install-prompt.md) — paste-ready
  prompts to delegate install to a coding agent
- [`agent-learning-compounder/reference-lib/`](agent-learning-compounder/reference-lib/) —
  per-subsystem references (architecture, threat-model, output-schema,
  gate-registry, hook-telemetry, source-adapters, pressure-tests, …)
- [`docs/dev/`](docs/dev/) — internal release artifacts (signoff, hardening
  plans, gate-system backlog)
- [`docs/history/`](docs/history/) — frozen historical work orders

## Verify

```bash
cd agent-learning-compounder
python3 -m unittest discover -s fixtures/tests   # unit + integration
python3 -m unittest discover -s tests            # post-install smoke
python3 scripts/run_pressure_tests.py            # durable-write gate
```

## License

[MIT](LICENSE) — © 2026 Tom.
