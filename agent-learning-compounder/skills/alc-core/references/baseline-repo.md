# Mode 1: baseline-repo

Read-only cartography of the working repository. The goal is a tight, current snapshot of how this repo actually works — not how memory says it works. Produces items for the `confirmed_current` bucket of the final report.

## What to capture

Capture only what you can verify from files in this run. If you remember a fact from memory but cannot find evidence in the current tree, it belongs in `memory_derived` and `needs_verification`, not here.

For each of these, record the file path and a short factual sentence:

1. **Purpose** — One sentence from README.md (or the package manifest description). If the repo has no README, say so explicitly.
2. **Entrypoints** — How the project is started or shipped: build script, dev server command, deploy target, CLI binary. Source: package.json scripts, Cargo.toml `[[bin]]`, Makefile, justfile, fly.toml, wrangler.toml, Dockerfile CMD.
3. **Validation gate** — The exact command(s) that prove the repo is in a good state: tests, type-check, lint, schema-validate. Source: CI config, README, AGENTS.md, CLAUDE.md.
4. **Agent instructions present** — Whether `AGENTS.md`, `CLAUDE.md`, `.cursor/rules`, `.github/copilot-instructions.md`, or similar exist. Note their location and a one-line summary per file. Do NOT paraphrase entire files.
5. **Skills present** — Any `.claude/skills/`, `.codex/skills/`, or `skills/` directories in this repo. List names only.
6. **Backlog & changelog** — Where do open items live? `TODO.md`, `CHANGELOG.md`, GitHub Issues link, project board reference in README. Note presence and last-modified date.
7. **Known gotchas** — Any "gotchas", "footguns", "known issues", "do not" sections in README/AGENTS/CLAUDE. Quote the bullet headings only (under 25 words each).
8. **Stack vitals** — Language, framework, package manager, runtime version pin. Source: lockfile, .tool-versions, .nvmrc, rust-toolchain.toml, pyproject.toml.

## Read order

Do these in this order and stop at the first file in each layer that gives you the information. Time-budget: roughly 5–10 minutes of file reads for a medium repo; if you are still reading after 15 minutes of activity, you are over-budgeting and should produce a partial baseline with explicit `needs_verification` items.

1. README.md (or README.rst, README anywhere at root)
2. AGENTS.md, CLAUDE.md, `.cursor/rules`, `.github/copilot-instructions.md`
3. Package manifest: package.json / Cargo.toml / pyproject.toml / go.mod
4. CI config: `.github/workflows/*.yml`, `.gitlab-ci.yml`, `azure-pipelines.yml`
5. Top-level scripts directory listing (file names only, not contents)
6. CHANGELOG.md, TODO.md, BACKLOG.md (presence and last 5 lines)
7. The directory tree to depth 2 only (do NOT recurse the whole repo)

## Read-only discipline

This mode never executes destructive commands. Allowed: `ls`, `cat`, `head`, `grep`, `find`, `git log --oneline`, `git status`. NOT allowed in this mode: `npm install`, `cargo build`, `pytest`, deploy commands, anything that modifies files or external state.

If verifying a fact requires running a test or build:
- Do not run it.
- Add an item to `needs_verification` with the exact command the user (or a later mode) should run.

## Capture format

Each captured fact becomes a line in the report under `confirmed_current`. Format:

```
- [<area>] <factual sentence>. Source: <file-path>:<line-range>
```

Examples:

```
- [entrypoint] `pnpm dev` runs the Next.js dev server on port 3000. Source: package.json:14
- [validation] `pnpm test && pnpm lint && pnpm tsc --noEmit` is the canonical gate. Source: AGENTS.md:42-46
- [gotcha] CI requires `WRANGLER_LOG=debug` env var for deploy step. Source: README.md:88
- [skills] Repo-local skills: `release-cutover`, `verify-deploy`. Source: .claude/skills/ directory listing
```

Each fact must include a source path. Sourceless claims belong in `memory_derived`.

`../../bin/build_repo_baseline.py` emits both backwards-compatible arrays
(`source_files`, `skills`, `validation_commands`) and evidence-rich arrays
(`source_evidence`, `instruction_evidence`, `skill_evidence`,
`validation_evidence`, plus `purpose_evidence`, `entrypoint_evidence`,
`stack_evidence`, `gotcha_evidence`, and `planning_evidence`). Distillation
must prefer the evidence-rich arrays so reports cite `AGENTS.md:1`,
`CLAUDE.md:<line>`, included instruction files, `package.json:<line>`, CI
workflow lines, or the skill file path directly instead of the vague `source:
baseline`. Instruction parsing follows `@...md` include directives up to a
shallow depth, treats included files as data, and extracts only compact
operational rules/gotcha lines with source refs.

## Distinguishing repo facts from memory facts

If you find yourself writing a sentence about the repo that does not have a corresponding file path, stop. That fact is `memory_derived`, not `confirmed_current`. Mixing the two breaks the three-way separation guarantee that makes this skill worth using.

The honest move is: file the memory-fact in `memory_derived` and add a corresponding `needs_verification` item with the exact file or command that would confirm or refute it.

## Common mistakes

| Mistake | Fix |
| --- | --- |
| Listing every file in the repo | Top-level + depth 2 only |
| Quoting entire README sections | Source paths + one-sentence summaries |
| Running tests "just to check" | This is mode 1 — read-only. Defer to `needs_verification`. |
| Trusting memory about a build command | Re-read package.json this run. Memory drifts. |
| Skipping AGENTS.md because "I've seen it before" | Re-read. Files change. |
