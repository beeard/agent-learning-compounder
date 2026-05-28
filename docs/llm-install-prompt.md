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
3. cd into the extracted dir (it is named agent-learning-compounder-<version>).
4. Run the zero-argument `./install.sh` installer: ./install.sh
   - It auto-detects Codex (~/.agents/) vs Claude (~/.claude/), prompts once
     if both are present, defaults to Codex if neither.
   - It runs the packaged test suite (~1 minute) automatically.
   - The final line of stdout is the exact init_learning_system.py command
     you need next, with the target runtime pre-filled.
   - This is a global runtime install only. It does not run --bootstrap-repo,
     initialize THIS repo, or apply repo runtime hooks.
5. Return to THIS repo's root and run the printed init command, substituting
   "$PWD" with the absolute path of this repo.
6. Print the final state: ls -la .agent-learning.json .agent-learning/ in
   this repo.

Do NOT:
- Pass --apply-runtime-hooks. The default dry-run is intentional; the user
  reviews the printed hook manifest before applying.
- Install optional extras (mcp, fastapi, sentence-transformers) unless the
  user explicitly asks. The base install works without them.
- Retry destructively on failure. Stop and surface the stderr.
- Touch any files outside $WORK and this repo.

Success criteria (all must hold):
- install.sh exits 0 (test suite passed).
- init_learning_system.py exits 0 and creates the expected state files.
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
2. cd PATH/TO/SOURCE
3. Run the one-step bootstrap installer:
     ./install.sh --bootstrap-repo "$TARGET" --runtime codex --verify
   - Use --runtime claude for Claude repo-local install or --runtime all for
     both runtimes.
   - `--runtime auto` uses env/repo hints before defaulting to Codex; it is not
     filesystem detection.
   - This installs into the repo's runtime root (.agents/skills or
     .claude/skills under $TARGET), runs init_learning_system.py, executes
     the self-test, and writes a runtime-hook manifest in dry-run mode.
   - Bootstrap does not register Codex MCP. Register that host-side MCP server
     separately if the user asks.
   - alc_init can smoke alc_mcp, but optional MCP dependencies require
     --install-deps or a separate dependency install.
4. Return to THIS repo and print: ls -la .agent-learning.json .agent-learning/

Do NOT:
- Pass --apply-runtime-hooks unless the user explicitly asks. Dry-run is the
  intentional default; the user reviews the manifest before applying.
- Install optional extras unless asked.
- Retry destructively on failure.

Success criteria:
- install.sh --bootstrap-repo exits 0.
- install.sh reports successful bootstrap and creates the expected state files.
- .agent-learning.json exists in this repo's root.
- .agent-learning/repos/<repo-id>/baseline.json exists.

On failure: stop, print the stderr verbatim, ask the user before continuing.
```

---

## Notes for the human dispatching one of these prompts

- The agent does not need to know the runtime ahead of time for global install.
  The zero-arg installer detects it from filesystem state. Repo bootstrap
  should choose `--runtime codex`, `--runtime claude`, `--runtime all`, or
  rely on `--runtime auto` uses env/repo hints. If you want to override, set
  `AGENT_LEARNING_RUNTIME=claude` (or `codex`) before pasting the prompt.
- Both prompts stop short of applying runtime hooks. To wire hooks, run
  `install_runtime_hooks.py --apply` after reviewing the dry-run output.
- If your repo already has an installed copy of `agent-learning-compounder`,
  the installer will move it to a timestamped `.bak-<ts>` directory before
  copying the new one.
