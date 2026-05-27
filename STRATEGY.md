# STRATEGY

> What ALC is, who it's for, how we know it's working, what we're investing in.
> Short and durable — peer of README.md. Downstream CE skills read this as
> grounding (`/ce-ideate`, `/ce-brainstorm`, `/ce-plan`).

Version: `2026.05.27+review7-plus2.3`
Last reviewed: 2026-05-28

---

## Target problem

Agents forget. Every new session reloads generic skill files and re-discovers
the same project-specific lessons from scratch — that a gate was tried last
week and failed, that a particular skill never gets used in this repo, that
a specific tool is the bottleneck. The operator pays in two ways:

1. **Tokens and time.** Re-deriving repo-specific routing and do/don't rules
   on every session.
2. **Lost learnings.** A correction the operator gave last week doesn't reach
   the agent on the next session, so the same mistake recurs.

The friction is sharpest on multi-week projects where the operator runs many
sessions across different agents (Codex, Claude Code, Gemini, others) and
expects the project itself — not the human — to carry the institutional
memory between sessions.

ALC solves this by turning the ambient signals already produced by those
sessions (git baseline, transcripts, hook events, recommendation outcomes)
into two small, compact, evidence-backed surfaces that future agents load
on every session start:

- `latest-approved-gates.md` — do/don't rules, scored by effectiveness
- `latest-skill-context.md` — repo-specific skill routing hints

Plus a third, written by `alc_init`:

- `latest-session-context.md` — per-repo runtime summary + doc-contract
  status + CE playbook tailored to the detected stack

Everything else is plumbing in service of keeping those three files honest.

## Approach

The mechanism is a layered pipeline (see ARCHITECTURE.md for the seams):

1. **Install once** — three first-class paths (npm/npx, curl one-liner,
   Claude Code marketplace). All land the same artifacts.
2. **Bootstrap a repo** — `alc_init` profiles the host, smokes the MCP
   server, writes the per-repo session-context file. Idempotent.
3. **Ingest ambient signals** — repo baseline, session transcripts (via
   runtime adapters), hook events (bounded allowlist, never raw output).
4. **Distill into evidence-backed proposals** — `distill_learning` turns
   the corpus into proposed gates and skill-routing facts. Read-only by
   default; durable writes require explicit `--write --personal`.
5. **Score and federate** — `evaluate_gate_effectiveness` gives each gate
   a stable 12-char `gate_id` and a correlation-only effectiveness signal.
   `gates_promote` / `gates_inherit` carry gates across repos with
   `derived_from:` provenance.
6. **Export the durable surfaces** — `export_gates` + `export_skill_context`
   produce the two compact markdown files. Never raw logs.
7. **Loop closed via hook telemetry** — `collect_hook_event` writes
   bounded events; `refresh_learning_state` re-derives the exports on the
   next refresh.

Trust model is the load-bearing design choice (see ARCHITECTURE.md §
"Trust boundaries"). Two principles:

- **Never persist raw prompts, raw tool output, transcript chunks, or
  secret markers.** Telemetry rows are an allowlisted field set; the
  validator rejects psychological/ability claims about the operator.
- **Default to read-only.** Anything that mutates durable memory requires
  explicit operator opt-in. Hook install is manifest-only until
  `install_runtime_hooks --apply`.

Reversibility matters more than slickness. Every install layer can be
re-run; the installer refuses to write tracked files; runtime hook configs
auto-`.gitignore` themselves; backups are timestamped.

## Users

Three concentric profiles, in priority order:

1. **The primary operator** — a single developer running many sessions per
   day across multiple agents (Codex CLI, Claude Code) on a handful of
   long-running projects. Wants the project itself to carry institutional
   memory between sessions, without leaking secrets to a remote service
   or trusting a black-box "agent memory" SaaS.

2. **Other coding agents installing into a fresh repo** — Codex / Claude
   Code being told "install agent-learning-compounder and bootstrap this
   repo." The install must be five-year-old simple: one command, idempotent,
   no follow-up Q&A required. Three install paths exist to absorb the
   "I don't have Node" / "I don't have Claude Code" / "I just have curl"
   variance.

3. **The compound-engineering pipeline itself** — `/ce-ideate`,
   `/ce-brainstorm`, `/ce-plan`, `/ce-work`, `/ce-simplify-code`,
   `/improve-codebase-architecture` all benefit from grounding in this
   repo's specific gates and skill-routing facts. `bin/ce_playbook`
   renders tailored hints into the session-context file so the CE
   workflow has something concrete to anchor against.

**Inferred but unverified:** team adoption beyond the primary operator
is a non-goal for now. Federation (`gates_promote` / `gates_inherit`)
is built so a single operator can carry hard-won gates across their own
repos, not for cross-org sharing. If team adoption becomes a goal, the
trust model around `--personal` writes and the per-repo state topology
will need to be revisited.

## Key metrics

How we'd know it's working — observable signals, not vibes:

- **Doc-contract green across the anchor + architecture tiers.**
  `alc_init` runs a doc-contract check and reports missing canonical
  files. Self-dog-fooding: this very commit closes the
  STRATEGY/ARCHITECTURE/CONTEXT gap that the check flagged.
- **Gate effectiveness ratio.** `evaluate_gate_effectiveness` segments
  every gate into `correlated_with_success` / `correlated_with_failure`
  / `no_signal` / `needs_review`. We want the success-correlated fraction
  trending up and the no-signal fraction trending down over time.
- **Queue retire rate.** Low-impact gates get queued as
  `gate_retirement_candidate` for operator review. A healthy loop
  retires faster than it proposes.
- **Causal probes deciding cleanly.** `causal_probe` runs deterministic
  A/B skip cohorts per gate. Once a probe accumulates N ≥ 5 trials per
  arm, it should emit a `causal_signal` — not stay in
  collecting-evidence mode forever.
- **Refresh latency.** `refresh_learning_state` from corpus to exported
  surfaces should stay under operator patience (current target: well
  under a minute on a baseline-ALC corpus). Inferred threshold; no
  hard SLA yet.
- **Install path parity.** All three paths (npm, curl, Claude plugin)
  pass the same nine-check end-to-end validation suite. Regression
  here breaks the "five-year-old simple" claim.
- **No secret leakage.** The pressure-test suite + scrubber regression
  tests must stay at 100%. This one is binary, not a trend.

What we explicitly do **not** track:

- Number of sessions, prompts, or tool calls. Those are means, not ends.
- "Time saved" — not measurable without a counterfactual.

## Tracks of work

What we're actively investing in vs. parked.

### Active

- **Self-dog-fooding the doc contract.** ALC's own `alc_init` flagged
  STRATEGY / ARCHITECTURE / CONTEXT as missing on the ALC repo itself.
  Closing that now (this commit). Going forward: the doc-contract output
  is a first-class signal in the per-repo session context, not just an
  informational line.
- **Read/propose seam discipline (KTD-21).** `alc_query` is the only
  read API; `alc_propose` is the only propose/write API. Hooks,
  dashboards, MCP tools, slash commands, and `alc_init` all consume
  them. New work that touches reads/writes lands here, not inline.
- **MCP catalog stability (M1–M10).** Eleven stdio tools, auto-registered
  from `alc_mcp.catalog.MCP_TOOLS`. Catalog-driven so consumers can
  call `list_capabilities` and compare versions instead of guessing.
- **CE playbook integration.** `bin/ce_playbook` renders detected-stack
  hints for the compound-engineering pipeline. CE is a soft dependency
  — playbook still renders useful checklists when CE isn't installed.
- **Install-path parity.** Three first-class install paths kept in
  sync via the same end-to-end validation suite. Symlink-vs-copy
  pitfalls (npm strips symlinks on pack — see `plus2.1` hotfix) are
  the failure mode to keep guarded.
- **Release contract ownership.** Package-visible identity is owned by
  `bin/release_metadata.py`; archive/package inclusion policy is owned by
  `bin/release_layout.py`. Manifest, npm, plugin, marketplace, README, shell,
  and fixture-test surfaces stay shallow adapters with parity tests.
- **Dashboard URL ownership.** `bin/dashboard_url_publisher.py` owns live
  dashboard marker schema, loopback validation, token-safe cleanup, and static
  fallback order. FastAPI, stdlib serving, static rendering, and MCP exposure
  remain adapters around that URL policy.

### Deferred (not "ideated and rejected" — just not now)

- **Cross-repo federation beyond a single operator.** `gates_promote` /
  `gates_inherit` work today across one operator's own repos. Multi-
  operator / multi-org federation needs the trust model revisited
  first.
- **Cloud sync (`alc-cloudflare-sync` and similar).** Sketched in
  earlier sessions as a track but parked — the trust model around
  "ALC state should stay on the operator's machine" is currently
  load-bearing and we don't want to weaken it without a concrete
  user need.
- **Team-grade dashboard.** The localhost FastAPI/HTMX dashboard
  (`bin/serve_dashboard`) and the newer stdlib `http.server` surface
  (`skills/alc-dashboard/`) coexist for MVP per
  `docs/decisions/dashboard-migration.md`. Consolidation deferred
  until the stdlib surface stabilizes and the muted-domains workflow
  is ported.
- **Embedding-backed dedup as default.** `bin/queue_dedup` ships with a
  stdlib character-trigram backend by default. The optional
  `sentence-transformers` backend exists but stays optional — pulling a
  multi-hundred-MB dep into a base install would break the "skill
  package, not an app" framing.

### Constantly evaluated, never finished

- **No raw-data leakage.** Threat-model review every release. New
  signals get vetted against the allowlist, not added to it.
- **Naming consistency.** Q1–Q10 analyst queries, G1–G5 generators,
  M1–M10 MCP catalog, `DSL_TARGETS` for Hermes-DSL. Cute names get
  pushed back on; named-catalog over ad-hoc terms (see
  `reference-lib/analyst-queries-catalog`, `generator-catalog`,
  `mcp-catalog`).

---

## Footnotes

- "Inferred:" markers above flag claims I (the agent) extrapolated from
  the codebase + recent commits rather than stating from an explicit
  source document. They're conservative; remove or rewrite if wrong.
- This file is durable. Update it when direction shifts, not when
  individual features land — those belong in CHANGES.md.
