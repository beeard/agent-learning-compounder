# Mode 3: map-capability

Turn evidence from `distill-sessions` into a domain x rubric matrix, then derive concrete `agent_compensation` gates per domain. The output is instructions for future agents, not coaching or criticism of the human.

## Rubric

Apply levels per domain, never globally. Capability is contextual.

| Level | Meaning |
| --- | --- |
| 0 | AI used as lookup only. User generates the work; AI answers point questions. |
| 1 | AI drafts; user steers and verifies every step. Friction is high if AI deviates. |
| 2 | AI implements; user reviews outcomes against a known-good standard. |
| 3 | AI owns plan and validation; user approves direction. User cannot fully audit; trust rests on AI verification gates. |
| 4 | Continuity depends on AI memory or gates because manual verification is structurally weak: too much state, too fast, no time, or no tooling. |

Level 3 and 4 are not failures. The useful output from level 3 or 4 is never "the user should improve"; it is "future agents must run gate Y because independent human audit is not enough in this domain."

## Default Domains

Start with these. Add domains only when evidence requires it.

| Domain | Scope |
| --- | --- |
| `git-release` | Branching, merging, tagging, deploy cuts, rollback, version pinning |
| `repo-architecture` | Knowing where things live in a specific repo; navigating unfamiliar codebases |
| `external-docs` | Reading current docs for libraries, SaaS, or cloud providers vs. relying on memory |
| `tests` | Writing tests, reading test output, choosing what to test, asserting invariants |
| `ui` | Component patterns, accessibility, design tokens, frontend state |
| `quick3` | User-specific Quick3 workflow and integration context |
| `cloudflare` | Workers, KV, D1, R2, Hyperdrive, Wrangler config, deploy verification |
| `teams-m365` | Microsoft Teams, M365 tenant state, Planner, SharePoint, mailbox or connector checks |
| `external-runtime-truth` | Live services, tenants, deploy state, dashboards, logs, or runtime state outside the repo |
| `scope-drift` | Packet boundaries, do-not-build zones, over-scope implementation risk |
| `validation` | Test/typecheck/lint/build proof, completion claims, verification discipline |
| `agent-workflows` | Skills, AGENTS.md and CLAUDE.md discoverability, handoffs between agents, memory hygiene |

Domains without evidence are noise. If evidence is thin, use a range such as `2-3` and mark the domain `needs_verification`.

## Level Assignment

| Evidence pattern | Suggested level |
| --- | --- |
| User asks point questions; does the work themselves | 0 |
| User accepts drafts but rewrites substantial portions; corrects approach often | 1 |
| User accepts implementations, runs them, and corrects post-hoc | 2 |
| User accepts agent plan and validation gates; does not independently audit | 3 |
| Multiple sessions require the agent to remember state across sessions, or the user cannot reproduce what the agent set up | 4 |

The level is descriptive, derived from evidence, and never a scorecard. Do not label the user as capable or incapable.

## Compensation Gates

For each domain at level >=2, write what future agents must do before recommending action. Gates must be:

- Specific to the domain.
- Verifiable by a future agent.
- Cheap enough to actually run.

| Category | Example |
| --- | --- |
| `docs-check` | Re-read the current upstream doc page before recommending API usage. Include access date. |
| `repo-gate` | Re-read AGENTS.md, local skill guidance, and validation commands before changing the repo. |
| `live-check` | Run a non-destructive command and quote one line of output as confirmation. |
| `evidence-quote` | Quote the specific line of code, config, or transcript the recommendation depends on. |
| `handoff-check` | Re-read the latest agent-learning report before continuing prior work. |
| `scope-gate` | Restate active scope and do-not-build boundary before editing. |
| `readback-check` | After a write or append, smoke and read back the changed state in the same run. |
| `validation-check` | Run the discovered validation commands or document exact skipped commands as `needs_verification`. |
| `release-gate` | Inspect git status, validation state, and file scope before commit/push/merge/ship. |

## Output Format

```yaml
domain: cloudflare
level: 3
evidence_summary: "Two current-session examples show deploy confidence depends on agent-run validation."
agent_compensation:
  - category: live-check
    gate: "Before claiming a Workers deploy is healthy, run the repo's deploy verification command and quote one non-secret output line."
  - category: docs-check
    gate: "Before changing wrangler config, re-read current Cloudflare docs and record the access date in the report."
```

## Common Mistakes

| Mistake | Fix |
| --- | --- |
| One global level for the user | Use per-domain levels only |
| Matrix reads as criticism | Rephrase as compensation gates for future agents |
| Domain has no evidence | Drop it |
| Vague gates | Replace with specific, verifiable, cheap actions |
| Level 4 framed as a problem | Keep the level descriptive; the gate is the useful output |
| Level from one session | Use a range and mark `needs_verification` |
