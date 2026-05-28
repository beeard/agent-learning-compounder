# Quickstart

Get `agent-learning-compounder` installed and wired into a project in
**one command**. The default install is project-local and uses runtime resolution:
`AGENT_LEARNING_RUNTIME`, repo hints in `AGENTS.md` / `CLAUDE.md` /
`GEMINI.md`, local Codex/Claude runtime evidence, then Codex by default. It
runs `alc_init` to profile your repo, smoke-test MCP when optional deps are
available, and write the first session-context.

## What you need (one-time check)

- A POSIX shell. macOS Terminal, Linux, or WSL on Windows all work.
- Python 3.10 or newer. Check with `python3 --version`.
- A project directory you want to wire up (a `.git` folder helps but isn't required).

## Install — pick the path that fits

Run from inside the project you want to wire up.

Command matrix:

```bash
./install.sh
# zero-argument `./install.sh`: project-local install in the current repo.
# It detects runtime, verifies, initializes .agent-learning, and applies
# repo-local hooks.

./install.sh --runtime codex
./install.sh --runtime claude
./install.sh --runtime all
# Runtime flags are overrides. They still install project-locally.
# Use --install-deps for optional Python extras in .agent-learning/venv.
# Use --no-verify or --no-apply-runtime-hooks for custom unattended setups.
```

### npm / npx (recommended)

```bash
npx agent-learning-compounder
```

### curl one-liner (no Node required)

```bash
curl -fsSL https://raw.githubusercontent.com/beeard/agent-learning-compounder/master/bootstrap.sh \
  | sh
```

### Claude Code marketplace (in-app)

Inside a Claude Code session:

```
/plugin marketplace add beeard/agent-learning-compounder
/plugin install agent-learning-compounder@agent-learning-compounder
```

This installs the plugin for Claude Code; agents, commands, hooks, and the MCP
server auto-discover. Per-repo init still needs the npm/curl path or
`alc_init --repo "$PWD"` from inside the installed location.

### From source (for inspection or contribution)

```bash
git clone https://github.com/beeard/agent-learning-compounder.git /tmp/alc
/tmp/alc/install.sh
```

Any of the four paths above will:

- Install the skill into the selected repo-local runtime root. Pick explicitly
  with `--runtime codex|claude|all`; the default auto mode uses env/repo hints,
  then local runtime evidence, then Codex.
- Run the packaged test suite (`--verify`) — about a minute.
- Create `.agent-learning.json` at your project root and `.agent-learning/`
  for local state.
- Run `alc_init` to profile the host repo (frameworks, languages, tests),
  smoke the MCP server when optional MCP dependencies are installed, check the
  doc contract, and write `latest-session-context.md`.
- Optional Python extras are not installed by default. Pass `--install-deps`
  to install `requirements-optional.txt` into `.agent-learning/venv`; user-site
  installs require explicit `alc_init --deps-scope user` or `--user-deps`.
- Build dashboard React assets best-effort when `pnpm` is available; fallback
  HTML remains usable when the build is skipped or fails.
- It does not register Codex MCP. Register the MCP server separately in Codex
  when you want that host to load it.

## Did it work?

If both files exist in your project, you're done:

```bash
ls -la .agent-learning.json .agent-learning/
```

You should also see successful bootstrap output from `init_learning_system.py`
and a final `bootstrapped agent-learning-compounder into: ...` line.

## What now?

Nothing. Use your AI coding agent (Claude Code, Codex, etc.) as you normally
would. The skill builds up learning context in the background and surfaces
it to future sessions automatically. The longer it runs, the smarter it gets
about your specific repo.

## Runtime hooks

The zero-argument installer applies repo-local hooks by default so the skill
captures session telemetry automatically. To review without writing hooks:

```bash
/tmp/alc/install.sh --no-apply-runtime-hooks
```

Explicit `--bootstrap-repo <dir>` remains dry-run by default for scripted
operators; pass `--apply-runtime-hooks` when you want that path to write hooks.

## Uninstall

If you change your mind:

```bash
# 1. Remove the repo-local installed skill (path depends on your runtime).
rm -rf .agents/skills/agent-learning-compounder   # Codex
rm -rf .claude/skills/agent-learning-compounder   # Claude
rm -f .codex/hooks.json .claude/settings.local.json

# 2. Remove the per-project state.
rm -rf .agent-learning .agent-learning.json
```

You can also remove the source clone (`rm -rf /tmp/alc`) once installed —
it's only needed during install.

## When things go wrong

- **`python3 is required`** — install Python 3.10+ and try again.
- **`refusing to install into symlinked target root`** — the installer
  guards against accidental symlink writes. Resolve the symlink at the
  target path, or pass `--target <real-path>` explicitly.
- **Tests fail during `--verify`** — stop and check the failure message
  before re-running. Don't retry destructively; the installer left a
  timestamped backup of any previous install at `.bak-<timestamp>`.

For everything else, see the full [README](../README.md) and the more
detailed [LLM-targeted install prompts](llm-install-prompt.md) if you'd
rather delegate the install to a coding agent.
