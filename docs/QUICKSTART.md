# Quickstart

Get `agent-learning-compounder` installed and wired into a project in **two
commands**. No flags to think about. The installer figures out the rest.

## What you need (one-time check)

- A POSIX shell. macOS Terminal, Linux, or WSL on Windows all work.
- Python 3.10 or newer. Check with `python3 --version`.
- A project directory you want to wire up. Anywhere with a `.git` folder is
  fine.

## Install — two commands

Open a terminal **inside the project you want to set up**, then:

```bash
# 1. Get the source somewhere (this stays out of your project).
git clone https://github.com/beeard/agent-learning-compounder.git /tmp/alc

# 2. Install it AND wire this project, all in one go.
/tmp/alc/install.sh --bootstrap-repo "$PWD" --verify
```

That's it. The second command:

- Installs the skill into your project's runtime root. Defaults to **Codex**.
  If you use Claude, prepend `AGENT_LEARNING_RUNTIME=claude` to the command:

  ```bash
  AGENT_LEARNING_RUNTIME=claude /tmp/alc/install.sh --bootstrap-repo "$PWD" --verify
  ```

- Runs the packaged test suite — about a minute. The `--verify` flag
  guarantees you find out immediately if something is off.
- Creates `.agent-learning.json` at your project root and `.agent-learning/`
  for local state.
- Runs a self-test that confirms everything is wired correctly.

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
