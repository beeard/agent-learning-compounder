# Follow-Up: Packaging, Docs, and Installer UX

> **Frozen historical work order — May 2026.** T1–T6 below were addressed in
> the `2026.05.26+review7-plus1.3` series. For active status see
> [`CHANGES.md`](../../CHANGES.md). Gate-system findings live at
> [`docs/dev/gate-system-review-2026-05.md`](../dev/gate-system-review-2026-05.md).

Work order for the next agent. Addresses gaps surfaced in the 2026-05-24 packaging audit (see prior conversation transcript). **Out of scope:** the gate-system code-level findings in `GATE_SYSTEM_REVIEW.md` — those are tracked separately.

## Context

The eight-upgrade plan (PLAN.md) shipped. All Phase 1–5 features are merged. But the project still carries the development scaffolding that got us here:

- `PLAN.md` (3075 lines) lives on `main` as if it were a live spec — it isn't; the work is done.
- The release tarballs in `dist/` contain `.pytest_cache/` and other dev artifacts that only get sanitized at install time, not at package time. Manual `tar -xzf` (which the README instructs) ships dev junk.
- `references/` mixes user-facing operational docs with internal release-process documents (`production-signoff`, `production-hardening-plan`, `self-healing-roadmap`).
- The `README.md` install path assumes an experienced Codex/Claude operator — no zero-config "paste this and you're done" path exists.

These are independent problems with mechanical fixes. Take them in the order below.

## Tasks

### T1. Archive `PLAN.md`

**Why:** It's a finished work order. Leaving it on `main` confuses new readers into thinking it's a live spec. `CHANGES.md` already records what shipped.

**Do:**
- Verify every Phase 1–5 task in `PLAN.md` corresponds to a merged commit. Spot-check by grepping for the binaries/refs the plan creates: `bin/replay_hook_events`, `bin/queue_dedup`, `bin/evaluate_gate_effectiveness`, `bin/propose_domain_rules`, `bin/causal_probe`, `bin/gates_promote`, `bin/gates_inherit`, `alc_mcp/server.py`, `bin/serve_dashboard`. All exist.
- Move `PLAN.md` to `docs/history/PLAN-eight-upgrade.md` (create the directory). Add a one-line header at the top noting "Frozen historical work order; for active status see CHANGES.md."
- Update any references to `PLAN.md` in `README.md` (currently lines 10-11 mention it) to point to `CHANGES.md` only.

**Acceptance:** `git ls-files PLAN.md` returns nothing at the repo root. The history doc is grep-able under `docs/history/`. README no longer points readers at a work order as if it were a spec.

### T2. Sanitize what goes into the tarball at build time

**Why:** `install.sh:150-154` defines `sanitize_skill_tree` but only runs it *after* extraction. The published tarball in `dist/agent-learning-compounder-2026.05.24+review7-plus1.tar.gz` contains `.pytest_cache/` because the build step skipped sanitization. Anyone who runs `tar -xzf` manually (a documented install path in the README) gets dev artifacts.

**Find or create the build script.** It's likely a `scripts/build_release.sh`, `Makefile` target, or ad-hoc commands. If you can't find one, check git history for the commit that produced files in `dist/` — the commit message or co-located script should reveal the packaging command.

**Do:**
- Either (a) factor `sanitize_skill_tree` out of `install.sh` into a shared `scripts/sanitize_skill_tree.sh` that both `install.sh` and the build script source, or (b) use `tar --exclude` flags during packaging.
- The exclusion set should match `install.sh:152-153`: `__pycache__`, `.pytest_cache`, `.agent-learning`, `*.pyc`, `*.pyo`, `.agent-learning.json`. Plus anything new that's appeared since.
- Rebuild and verify: `tar -tzf dist/<archive>.tar.gz | grep -E 'pytest_cache|__pycache__|\.pyc$'` should return nothing.

**Acceptance:** Fresh tarball has zero dev artifacts. Existing tarballs in `dist/` should either be rebuilt or deleted — do not leave broken artifacts published. If you cannot rebuild (build script lost), file a separate issue rather than guessing.

### T3. Triage the `references/` directory

**Why:** Three docs are internal release-process artifacts that shouldn't ship to end users. Two more are borderline.

**Internal — move out of `references/`:**
- `reference-lib/production-signoff` (+ symlink `references/production-signoff.md`)
- `reference-lib/production-hardening-plan` (+ symlink)
- `reference-lib/self-healing-roadmap` (+ symlink)

**Borderline — review and decide:**
- `reference-lib/pressure-tests` — describes the dev test harness. Probably belongs in `docs/dev/` not `references/`.
- `reference-lib/threat-model` — useful for security-conscious operators. Keep in `references/`.

**Do:**
- Create `docs/dev/` if it doesn't exist.
- Move the three internal docs (canonical files in `reference-lib/`, not their symlinks). Update the symlinks: either delete them or point to `docs/dev/<name>.md`.
- For the canonical move pattern, mirror what the rest of the project does: bare-name file in `docs/dev/`, optional `.md`-suffixed symlink if there's a presentation surface.
- Update any cross-references. Grep the entire repo for `production-signoff`, `production-hardening-plan`, `self-healing-roadmap` before deleting symlinks. `README.md`, `SKILL.md`, and the moved docs themselves are likely callers.

**Acceptance:** `references/` contains only user-facing operational and feature-reference docs. A new operator reading the directory listing sees nothing they would mistake for an internal release artifact.

### T4. Add a zero-config install path

**Why:** Today's install requires choosing between `--codex`, `--codex-home`, `--claude`, `--target`, plus knowing about `--runtime`, `--verify`, `--bootstrap-repo`, `--apply-runtime-hooks`. Six install flags before doing anything. The README acknowledges this with a 15-line bash one-liner under "One-Command Bootstrap" — which still requires picking a runtime via env var.

**Goal:** `./install.sh` with **no arguments** should do the right thing on a healthy system. Define "right" as:

1. Detect runtime: if `~/.claude/` exists and `~/.agents/` does not → Claude. If `~/.agents/` exists and `~/.claude/` does not → Codex. If both → ask the user once. If neither → default to `~/.agents/skills` (current Codex default).
2. Install to the detected runtime's skill root.
3. Run `--verify` automatically — the test suite is small (<1 minute) and the cost of skipping it is a silent broken install.
4. Print one final line telling the user what to do next, with the exact command pre-filled for their repo (`python3 <path>/scripts/init_learning_system.py --repo "$PWD" ...`).

**Do:**
- Add a `detect_runtime()` shell function near `resolve_runtime()` in `install.sh`.
- When no flags are passed, call `detect_runtime`, set `verify=1` by default, and proceed.
- Keep existing explicit flags working — they should override detection.
- Update README's `## Install` section to lead with the zero-arg command. Move the multi-flag forms to a "Custom install" subsection.

**Acceptance:** A new user can run `./install.sh` and have the skill installed plus verified, with a clear next-step command printed. Existing flag-based invocations continue to work unchanged. The README quickstart is one command, not fifteen lines.

**Caveat:** Don't auto-bootstrap into a repo — that's a separate decision the user should make consciously. The default zero-arg install just lands the skill on disk.

### T5. Ship a "first run" prompt for LLM agents

**Why:** The README's `## Agent Help` section points agents at `SKILL.md` and `references/agent-quickstart.md`. There's no canned prompt for "I have a tarball, install everything for me" — even though that's the most common LLM-assisted install scenario.

**Do:**
- Add a `docs/llm-install-prompt.md` containing two ready-to-paste prompts:
  1. **From-tarball:** agent has the `.tar.gz` and wants it installed + repo bootstrapped + extras pip-installed + hooks dry-run.
  2. **From-source:** agent has the git repo and wants the same.
- Both prompts should be explicit about: target runtime, hooks dry-run vs apply, optional extras y/n, what counts as success, what to do on failure (stop, don't retry destructively).
- Reference this file from `README.md`'s `## Agent Help` section.

Drafts of these prompts exist in the 2026-05-24 audit transcript — adapt them, don't rewrite from scratch.

**Acceptance:** A user can copy a single prompt into Claude Code / Codex / etc. with one path substitution and have the install run end-to-end without further interaction.

### T6. Make `dist/` reproducible and pruned

**Why:** Three archives sit in `dist/` (two `.tar.gz`, one `.zip`). No `Makefile` target or build script is obvious. Whatever produced them needs to be findable and re-runnable.

**Do:**
- Locate or create the build script. If it doesn't exist, write `scripts/build_release.sh` that:
  - Reads version from a single source (likely `MANIFEST.json`).
  - Runs `sanitize_skill_tree` (per T2) on a clean copy.
  - Produces both `.tar.gz` and `.zip` deterministically (sort filenames, fix mtimes if you want byte-reproducible builds — at minimum, content-reproducible).
  - Regenerates `SHA256SUMS`.
- Add a `make release` or `scripts/build_release.sh --version <v>` entry point.
- Decide retention policy for `dist/`: probably keep only the latest 2 versions on `main`; older archives live in GitHub Releases or equivalent. Don't bloat the repo.

**Acceptance:** Anyone can rebuild a byte-identical (or at least content-identical) tarball from a tagged commit. `dist/` doesn't grow unbounded.

## Out of scope

- **Gate-system code-level fixes** (the 7 critical + 6 high findings in `GATE_SYSTEM_REVIEW.md`). Track those separately; they're code changes, not packaging.
- **MCP server hardening beyond what's already shipped.** Commit `73e8bdf` covered it.
- **Renaming `fixtures/tests/`** to `tests/integration/` or similar. The README already explains the dual `tests/` + `fixtures/tests/` naming; leave it.
- **Switching the project to Poetry / setuptools / a real Python package layout.** That's a larger architectural call. The current "scripts that exec each other via symlinks" pattern is intentional (zero-deps, vendorable).

## How to verify the whole follow-up

After T1–T6 land:

1. **Fresh-eyes install test.** On a clean VM or container without `~/.claude` or `~/.agents`: untar the new release, run `./install.sh`, follow the printed next-step command. Verify a self-test passes end-to-end without reading the README beyond the quickstart.
2. **Tarball sanity check.** `tar -tzf dist/<archive>.tar.gz | grep -cE 'pytest_cache|__pycache__|production-signoff|self-healing|hardening-plan'` returns 0.
3. **Repo cleanliness.** `git ls-files | grep -E '^(PLAN|production-signoff|production-hardening-plan|self-healing-roadmap)' ` returns nothing in the top-level or in `references/`.
4. **LLM prompt test.** Hand the from-tarball prompt to a fresh agent session with the published tarball; it should complete the install end-to-end with one path substitution.
5. **Existing-user regression.** A user with an installed copy of `review7-plus1` should be able to `./install.sh` over their existing install and have it succeed (backup created, install verified, no surprises).

## Notes for the executing agent

- **No PLAN.md-style verbose checkbox tasks.** This file is the work order; don't expand it into another 3000-line plan. Implement and commit.
- **Commits per task.** Each T# above should be one or two commits. Don't bundle T1 and T6 into one mega-PR.
- **Test before publishing.** If you're going to delete or rebuild `dist/` archives, make sure you can rebuild the current published versions byte-for-byte first (T6), or you'll break anyone who has the SHA256SUMS pinned.
- **Don't touch the gate-system code** while doing this work. The audit findings in `GATE_SYSTEM_REVIEW.md` need their own focused PRs with test coverage — they will conflict with packaging changes if attempted together.
- **Conservative on destructive moves.** When moving `PLAN.md` and the internal refs, use `git mv` and keep history. Don't delete + add.
