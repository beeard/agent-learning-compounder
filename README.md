# agent-learning-compounder

Portable skill package for mining repo baselines, session evidence, hook telemetry,
and skill-health signals into durable future-agent context.

This version (`2026.05.24+review7-plus1`) layers eight upgrades on top of
upstream `review7-production`: schema-versioned hook events with replay, semantic
queue dedup, stable per-gate IDs with effectiveness scoring, domain-rule mining,
deterministic A/B causal probes, cross-repo gate federation, an optional MCP
server, and an optional operator dashboard. See `CHANGES.md` for the shipped
feature list (historical implementation work order at
`docs/history/PLAN-eight-upgrade.md`).

## Quickstart

Two commands from inside the project you want to set up. Installs the skill,
wires the repo, and self-tests:

```bash
git clone https://github.com/beeard/agent-learning-compunder.git /tmp/alc
/tmp/alc/install.sh --bootstrap-repo "$PWD" --verify
```

Defaults to Codex. Claude users prepend `AGENT_LEARNING_RUNTIME=claude` to
the second command. See [docs/QUICKSTART.md](docs/QUICKSTART.md) for the
beginner-friendly walk-through (verification, opt-in hooks, uninstall).

## Requirements

- Python 3.10+
- POSIX shell for hook wrappers and `install.sh`
- Codex-compatible skills root, Claude skills root, or an explicit skills directory

Windows users should install through WSL or another POSIX shell environment.

### Optional extras

Some features depend on packages NOT installed by default. The package degrades
gracefully when they are absent (tests skip, code paths fall back or
raise on first use).

```bash
pip install -r agent-learning-compounder/requirements-optional.txt
```

- `mcp` — required for `alc_mcp/server.py` (the MCP stdio server).
- `fastapi`, `jinja2`, `uvicorn`, `httpx` — required for `bin/serve_dashboard`
  (the operator dashboard).
- `sentence-transformers` — optional embedding backend for `bin/queue_dedup`
  (default backend is stdlib trigram-Dice).

## Install

```bash
tar -xzf agent-learning-compounder-2026.05.24+review7-plus1.tar.gz
cd agent-learning-compounder-2026.05.24+review7-plus1
./install.sh
```

With no arguments, the installer detects whether to use Codex (`~/.agents/`) or
Claude (`~/.claude/`), runs the test suite (`--verify` is on by default),
backs up any existing install, and prints the exact next command to initialize
a repo. Prompts once if both runtime roots are present; defaults to Codex if
neither is.

After install, run the printed `init_learning_system.py` command from your
project root to wire the skill into that repo.

### Custom install

To bypass auto-detection — for an explicit runtime, a non-standard target, or
to script a repeatable install — pass any of the flags below. Any one of them
disables auto-detection (and `--verify` reverts to opt-in).

```bash
./install.sh --claude                         # explicit Claude
./install.sh --codex-home                     # ${CODEX_HOME:-~/.codex}/skills
./install.sh --target "$HOME/.agents/skills"  # explicit target
./install.sh --runtime claude --verify        # explicit runtime, verify
```

`AGENT_LEARNING_RUNTIME=claude ./install.sh` also bypasses auto-detection.

## One-Command Bootstrap (from a checked-out repo)

To extract, install, and initialize a repo in one shell pipeline (set
`AGENT_LEARNING_RUNTIME` if you want to override auto-detection):

```bash
REPO_ROOT="$PWD" && \
ARCHIVE="agent-learning-compounder-2026.05.24+review7-plus1.tar.gz" && \
WORKDIR="$(mktemp -d)" && \
tar -xzf "$ARCHIVE" -C "$WORKDIR" && \
( cd "$WORKDIR"/agent-learning-compounder-* && \
  ./install.sh --bootstrap-repo "$REPO_ROOT" --verify ) && \
rm -rf "$WORKDIR"
```

`--bootstrap-repo` installs the skill into the repo's runtime root (`.codex/`
or `.claude/`) and runs `init_learning_system.py` against the repo in one step.
Pass `--apply-runtime-hooks` if you also want runtime hooks wired immediately
instead of left as a dry-run manifest.

## Runtime-Specific Behavior

| Runtime target | Install root flag | Hook config target (repo scope) |
| --- | --- | --- |
| Codex | `--codex` (default) | `.codex/hooks.json` |
| Codex home | `--codex-home` | `$HOME/.codex/hooks.json` |
| Claude | `--claude` | `.claude/settings.local.json` |

Use `--scope user` for global hook wiring only when explicitly requested by
the operator.

## State Layout and Defaults

State root precedence (first match wins):

1. `--state-dir <path>` (explicit flag)
2. `AGENT_LEARNING_STATE_DIR` (environment override)
3. `--personal <path>` (resolves to `<personal>/reports/agent-learning`)
4. `<repo>/.agent-learning` — **production default** when invoked with a repo (the
   recommended default for all new setups)
5. `$XDG_STATE_HOME/agent-learning` (when set)
6. `~/.local/state/agent-learning`

## Installed Artifacts

After bootstrap (with `--install-repo-integration --install-hooks --self-test`):

**Repo local**

- `.agent-learning.json`
- `.agent-learning.json` state pointers:
  - `latest_approved_gates`
  - `latest_skill_context`
  - `hook_command` (when hooks enabled)
  - `hook_manifest` + `hook_event_log` (when hooks enabled)

**State root (`.agent-learning/repos/<repo-id>/`)**

- `config.json`
- `baseline.json`
- `domain-rules.active.json`
- `skill-map.json`
- `reports/latest-approved-gates.md`
- `reports/latest-skill-context.md`
- `improvement-queue.jsonl`
- `automation/agent-learning-refresh.manifest.json`
- `hooks/collect-agent-learning-event.sh`
- `hooks/agent-learning-hooks.manifest.json`
- `hook-events.jsonl`

The state root is also where read-only validation reads use generated
intermediate files.

## Health Contract

A repo is considered operationally healthy only when all of these pass:

- `init_learning_system.py --self-test` (or equivalent manifest checks) reports no
  missing required file.
- `.agent-learning.json` is present and untracked in git repos. When
  `--install-hooks` was used, it also declares `hook_command`, `hook_manifest`,
  and `hook_event_log` pointers.
- `reports/latest-approved-gates.md` and `reports/latest-skill-context.md` both
  exist and load.
- Hook runtime contract files agree on command and manifest path when hooks are
  installed.
- `automation/agent-learning-refresh.manifest.json` is present when
  `--install-repo-integration` is used.

## Domain Rules

Distillation domains are data, not script code. First use writes
`domain-rules.active.json` into the repo's agent-learning state and records its
path in `.agent-learning.json`. The default preset is generic; pass
`--domain-rules <json>` for a local operator profile or `--domain-preset
tm-norge` to preserve the packaged tm-norge/Quick3/Cloudflare/Teams gates.

## Runtime Hooks

The skill creates runtime-neutral hook wiring during init. Runtime hook application
is **manifest-only by default**:

- `--install-hooks` writes the wrapper and manifest.
- Runtime-specific hook integration requires explicit `install_runtime_hooks.py`
  `--apply`.

Review before writing:

```bash
python3 "$HOME/.agents/skills/agent-learning-compounder/scripts/install_runtime_hooks.py" \
  --repo "$PWD" \
  --runtime codex \
  --runtime claude \
  --dry-run
```

Apply only after review:

```bash
python3 "$HOME/.agents/skills/agent-learning-compounder/scripts/install_runtime_hooks.py" \
  --repo "$PWD" \
  --runtime codex \
  --runtime claude \
  --apply
```

## Uninstall, Upgrade, Rollback

### Uninstall

1. Remove installed runtime skill path:
   `rm -rf "$HOME/.agents/skills/agent-learning-compounder"` (or your target root).
2. Remove repo integration files:
   `.agent-learning.json`, `.agent-learning` (if no longer needed), and runtime
   hook config targets if you installed runtime hooks there.
3. Clean `.gitignore` entries added during install if desired.

### Upgrade

1. Install the new archive to the same target with `install.sh`.
2. Confirm backup path created by the installer (previous version is preserved and
   not overwritten).
3. Re-run the one-command bootstrap from step 1 against the target repo.

### Rollback

1. Restore the desired backup created by `install.sh` into your target skills
   root.
2. Re-run repo bootstrap with the same repo and desired state root.
3. Re-apply runtime hooks only after a fresh dry-run/review cycle.

## New Tooling (review7-plus1)

Eight new binaries land in `bin/` alongside the upstream set:

- `replay_hook_events` — migrate older hook event logs to the latest schema version.
- `queue_dedup` — collapse semantically near-duplicate improvement-queue rows.
- `evaluate_gate_effectiveness` — correlation-only effectiveness signals per `gate_id`.
- `propose_domain_rules` — mine corpus n-grams that correlate with corrections.
- `causal_probe` — register and decide deterministic A/B skip cohorts per gate.
- `gates_promote` — promote a gate from a repo into the shared registry.
- `gates_inherit` — append a shared gate into a target repo with provenance.
- `serve_dashboard` — launch the localhost operator dashboard.

Two new top-level dirs:

- `alc_mcp/` — stdio MCP server (`python3 -m alc_mcp.server`).
- `dashboard/` — FastAPI + Jinja2 + HTMX dashboard templates and static files.

Per-feature reference docs under `references/`: `event-schema-evolution.md`,
`queue-dedup.md`, `gate-effectiveness.md`, `domain-rules-learning.md`,
`cross-repo-gates.md`.

## Safety Model

- No raw prompts, raw tool output, transcript chunks, or secret markers are persisted.
- Future agents load compact exports only: `latest-approved-gates.md` and
  `latest-skill-context.md`.
- Improvement candidates are queued for human review, not silently applied.
- Runtime hook installation is dry-run by default.

## Agent Help

LLM agents should start with `agent-learning-compounder/SKILL.md`. For a
single deferred operating guide, read
`agent-learning-compounder/references/agent-quickstart.md`.

To delegate the install itself to an LLM (paste-ready prompts for both the
from-tarball and from-source paths), see `docs/llm-install-prompt.md`.

## Verify After Install

```bash
cd "$HOME/.agents/skills/agent-learning-compounder"
python3 -m unittest discover -s fixtures/tests
python3 -m unittest discover -s tests
python3 scripts/run_pressure_tests.py
```

## Layout And Conventions

A few directories use a dual-name convention that is intentional, not an
accidental duplicate:

- `bin/<name>` — canonical executable for each script. Shebanged, chmod +x.
- `bin/<name>.py` — symlink to `bin/<name>`. Required so Python's import
  machinery can resolve cross-script imports like `from scrub_secrets import
  scrub`, which look for a `.py` file on `sys.path`.
- `scripts/<name>.py` — symlink to `../bin/<name>`. Stable compatibility path
  documented in `SKILL.md` and external docs; lets the canonical bin/ layout
  evolve without breaking external invocations.
- `reference-lib/<name>` — canonical markdown reference, no extension.
- `references/<name>.md` — symlink to `../reference-lib/<name>`. Same
  separation as bin/scripts: identity-by-bare-name in `reference-lib/`,
  `.md`-suffixed presentation surface in `references/`.

There are two test directories with different purposes:

- `tests/` holds runtime smoke tests verifying the installed layout is intact.
  Small and meant to run after install.
- `fixtures/tests/` holds the full unit and integration suite plus eval fixtures.
  The directory name reflects that the tests live next to the eval fixtures they
  consume, not that the tests themselves are fixtures.

## Configurable Subject Names

`scripts/validate_outputs.py` rejects psychological or ability claims about
the operator. The default subjects are generic (`user`, `brukeren`). To
extend with personal names so reports mentioning, say, "Lisa is weak at
architecture" are caught, set `AGENT_LEARNING_SUBJECT_NAMES`:

```bash
export AGENT_LEARNING_SUBJECT_NAMES="Lisa,Per"
```

Comma- or whitespace-separated. Entries are regex-escaped automatically.

## Safety Notes On Runtime Hooks

Repo-scope init writes `.agent-learning.json` containing absolute local state
paths. In git repos, init refuses to overwrite a tracked copy and auto-adds the
untracked file to `.gitignore`.

Repo-scope `install_runtime_hooks.py --apply` writes `.codex/hooks.json` and
`.claude/settings.local.json` containing absolute `$HOME` paths to the adapter
script. If either config file is already tracked by git, the installer refuses to
modify it. For untracked repo-local configs, the installer auto-appends config
paths and backup globs to `.gitignore` when a `.git/` directory exists.
