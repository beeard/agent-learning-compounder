# LLM-Targeted Install Prompts

Paste-ready prompts for delegating an install to an LLM agent (Claude Code,
Codex, or any other tool-using coding assistant). Each prompt is self-contained:
the agent does not need to read the rest of this repo to follow it.

Each prompt has one path to substitute (the tarball or source location). The
agent is meant to be operating inside the repo you want to install into — i.e.
the current working directory of the agent's shell is your target project.

---

## Prompt 1 — install from a tarball

Use when you have an `agent-learning-compounder-*.tar.gz` on disk and want it
installed plus this repo initialized.

```
You are installing the agent-learning-compounder skill into THIS repo
(your current working directory). The tarball is at PATH/TO/TARBALL.tar.gz.

Steps:
1. Pick a clean work dir: WORK=$(mktemp -d)
2. Extract: tar -xzf PATH/TO/TARBALL.tar.gz -C "$WORK"
3. Find the extracted dir (it is named agent-learning-compounder-<version>):
   EXTRACTED=$(find "$WORK" -maxdepth 1 -type d -name 'agent-learning-compounder-*' | head -n 1)
4. From THIS repo's root, run the extracted zero-argument installer:
   "$EXTRACTED/install.sh"
   - It installs project-locally into THIS repo.
   - It resolves runtime from env/repo hints, local Codex/Claude runtime
     evidence, then Codex by default.
   - It runs the packaged test suite (~1 minute) automatically.
   - It initializes .agent-learning and applies repo-local runtime hooks.
5. Print the final state: ls -la .agent-learning.json .agent-learning/ in
   this repo.

Do NOT:
- Pass user/global flags such as --codex, --claude, --codex-home, or --plugin
  unless the user explicitly asks for a user-scope install.
- Install optional extras (mcp, fastapi, sentence-transformers) unless the
  user explicitly asks. If asked during install, pass `--install-deps` to the
  installer; it installs into this repo's `.agent-learning/venv` by default. Do not use
  `--deps-scope user` or `--user-deps` unless explicitly requested.
- Retry destructively on failure. Stop and surface the stderr.
- Touch any files outside $WORK and this repo.

Success criteria (all must hold):
- install.sh exits 0 (test suite passed).
- .agent-learning.json exists at this repo's root and is in .gitignore.
- .agent-learning/repos/<repo-id>/baseline.json exists.

On failure: stop, print the failing command's stderr verbatim, and ask the
user before trying anything else. Do not delete partial state.
```

---

## Prompt 2 — install from a source checkout

Use when the agent-learning-compounder repo is already checked out on disk and
you want both the install and the repo bootstrap in one shell pipeline.

```
You are installing the agent-learning-compounder skill into THIS repo
(your current working directory) from a source checkout at PATH/TO/SOURCE.

Steps:
1. Resolve the absolute path of this repo first: TARGET="$PWD"
2. Resolve the source checkout path: SOURCE="PATH/TO/SOURCE"
3. From THIS repo's root, run the one-step installer:
     "$SOURCE/install.sh"
   - Use --runtime claude for Claude repo-local install or --runtime all for
     both runtimes.
   - Default auto mode uses env/repo hints, local runtime evidence, then Codex.
   - This installs into the repo's runtime root (.agents/skills or
     .claude/skills under $TARGET), runs init_learning_system.py, executes
     the self-test, and applies repo-local hooks.
   - Bootstrap does not register Codex MCP. Register that host-side MCP server
     separately if the user asks.
   - alc_init can smoke alc_mcp, but optional MCP dependencies require
     --install-deps or a separate dependency install. `--install-deps` writes
     to this repo's `.agent-learning/venv` by default, not user site.
4. Print: ls -la .agent-learning.json .agent-learning/

Do NOT:
- Pass user/global flags such as --codex, --claude, --codex-home, or --plugin
  unless the user explicitly asks for a user-scope install.
- Install optional extras unless asked. If asked, keep them project-local; do
  this by passing installer `--install-deps`. Do not use `--deps-scope user`
  or `--user-deps` unless explicitly requested.
- Retry destructively on failure.

Success criteria:
- install.sh exits 0.
- install.sh reports successful bootstrap and creates the expected state files.
- .agent-learning.json exists in this repo's root.
- .agent-learning/repos/<repo-id>/baseline.json exists.

On failure: stop, print the stderr verbatim, ask the user before continuing.
```

---

## Notes for the human dispatching one of these prompts

- The agent does not need to know the runtime ahead of time. The zero-arg
  installer resolves it from env/repo hints, local runtime evidence, then Codex.
  If you want to override, set `AGENT_LEARNING_RUNTIME=claude` (or `codex`) or
  pass `--runtime claude|codex|all`.
- The zero-arg path applies repo-local hooks. Use `--no-apply-runtime-hooks`
  when you want a dry-run first.
- If your repo already has an installed copy of `agent-learning-compounder`,
  the installer will move it to a timestamped `.bak-<ts>` directory before
  copying the new one.
