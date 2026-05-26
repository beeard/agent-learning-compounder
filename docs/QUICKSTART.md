# Quickstart

Get `agent-learning-compounder` installed and wired into a project in
**one command**. The installer auto-detects your runtime (Codex / Claude
Code) and runs `alc init` to profile your repo, smoke-test MCP, and write
the first session-context.

## What you need (one-time check)

- A POSIX shell. macOS Terminal, Linux, or WSL on Windows all work.
- Python 3.10 or newer. Check with `python3 --version`.
- A project directory you want to wire up (a `.git` folder helps but isn't required).

## Install — pick the path that fits

Run from inside the project you want to wire up.

### npm / npx (recommended)

```bash
npx agent-learning-compounder --bootstrap-repo "$PWD" --verify
```

### curl one-liner (no Node required)

```bash
curl -fsSL https://raw.githubusercontent.com/beeard/agent-learning-compounder/master/bootstrap.sh \
  | sh -s -- --bootstrap-repo "$PWD" --verify
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
/tmp/alc/install.sh --bootstrap-repo "$PWD" --verify
```

Any of the four paths above will:

- Install the skill into the right runtime root (auto-detects `~/.agents/` vs
  `~/.claude/`; pick explicitly with `--runtime codex|claude`).
- Run the packaged test suite (`--verify`) — about a minute.
- Create `.agent-learning.json` at your project root and `.agent-learning/`
  for local state.
- Run `alc_init` to profile the host repo (frameworks, languages, tests),
  smoke the MCP server, check the doc contract, and write
  `latest-session-context.md`.

## Did it work?

If both files exist in your project, you're done:

```bash
ls -la .agent-learning.json .agent-learning/
```

You should also see a final line in the installer output that says
`self-test passed` (or similar).

## What now?

Nothing. Use your AI coding agent (Claude Code, Codex, etc.) as you normally
would. The skill builds up learning context in the background and surfaces
it to future sessions automatically. The longer it runs, the smarter it gets
about your specific repo.

## Optional: wire runtime hooks

By default the installer prepares hook configs but does **not** apply them —
it leaves a dry-run manifest you can review. To actually wire the hooks (so
the skill captures session telemetry automatically), pass
`--apply-runtime-hooks` to the install command:

```bash
/tmp/alc/install.sh --bootstrap-repo "$PWD" --verify --apply-runtime-hooks
```

Or apply them later by running `install_runtime_hooks.py --apply` against
the installed location (the installer prints the exact command).

## Uninstall

If you change your mind:

```bash
# 1. Remove the installed skill (path depends on your runtime).
rm -rf "$HOME/.agents/skills/agent-learning-compounder"   # Codex
# or:  rm -rf "$HOME/.claude/skills/agent-learning-compounder"  # Claude

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
