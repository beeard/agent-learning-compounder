---
title: "review: Agent-native architecture audit summary"
type: "review"
status: "proposed"
date: "2026-05-28"
source: "compound-engineering:ce-agent-native-audit"
parser_contract: "PLAN_ITEMS"
---

# review: Agent-native architecture audit summary

## Summary

This file captures the 2026-05-28 agent-native architecture audit in a plan-parser-friendly format.

The audit covered all eight agent-native principles. Six explorer sub-agents completed independent slices. Two slices were audited locally because the sub-agent limit was reached.

Overall maturity score: **55%** using strict principle scoring.

Interpretation: the system has a real agent-facing architecture, but it still depends too much on shell fallback, code-owned orchestration, stale documentation, and incomplete lifecycle verbs.

## Audit Method

- Action Parity: audited by explorer agent.
- Tools as Primitives: audited by explorer agent.
- Context Injection: audited by explorer agent.
- Shared Workspace: audited by explorer agent.
- CRUD Completeness: audited by explorer agent.
- UI Integration: audited by explorer agent.
- Capability Discovery: audited locally.
- Prompt-Native Features: audited locally.

## Scorecard

| Principle | Score | Percent | Status |
|---|---:|---:|---|
| Action parity | 7/23 direct, 20/23 with `exec_sandbox` | 30% direct | needs_work |
| Tools as primitives | 39/46 | 85% | strong |
| Context injection | 8/12 | 67% | partial |
| Shared workspace | 10/13 store families | 77% | partial |
| CRUD completeness | 1/14 full entities, 34/56 operation slots | 7% strict, 61% operations | needs_work |
| UI integration | 6/10 | 60% | partial |
| Capability discovery | 5/7 | 71% | partial |
| Prompt-native features | 4/9 | 44% | needs_work |

## Key Findings

### F1 - Action parity relies too heavily on `exec_sandbox`

Direct semantic MCP parity covers only 7 of 23 user-facing actions. With `exec_sandbox`, 20 of 23 actions become agent-reachable, but that forces the agent to know and assemble shell commands.

Covered direct actions include dashboard reads, dashboard URL lookup, `next_action`, durable state queries, patch proposal/status, gate proposal, outcome reporting, agent telemetry, and bounded command execution.

Missing or shell-only actions include distill jobs, dashboard promote/unpromote, mute/unmute, latest report content, bootstrap/init/hooks, refresh/render/index, apply/revert patch bundle, gate federation, eval/validation, live checks, and agent invocation.

### F2 - MCP tools are mostly primitive, but `next_action` is an orchestrator

The MCP/catalog surface is strong: 20 catalog tools plus `list_capabilities`, 12 analyst query specs, 5 generators, 4 DSL targets, and 3 sandbox scopes.

The main non-primitive MCP tool is `next_action`. It synthesizes intent, ranks priorities, chooses skills/prompts, returns alternatives, and writes a cache. That behavior belongs in a prompt-native skill over primitive state signals.

Generator recipes such as recommender generators and workflow chain emitters are also workflow-shaped rather than primitive tool calls.

### F3 - Context injection is useful but stale-prone

Session context generation includes repo profile, MCP status/tools, runtime summary, doc contract, CE usage, and playbook content.

Gaps:

- `latest-session-context.md` appears owned by `alc_init`, not clearly refreshed every hook cycle.
- `latest-session-report.md` and `latest-next-action.json` are not injected by default.
- Current branch, dirty status, active plan, running services, latest validation result, and current task are not first-class context.
- User/operator preferences are not represented as a structured repo-local context section.

### F4 - Shared workspace is mostly coherent but has path and sink splits

The canonical topology is repo-local through `.agent-learning.json` and `StateHandle`, with shared reports, dashboard artifacts, `events.jsonl`, `events.sqlite`, hook events, improvement queue, and patch/outcome state.

Gaps:

- `.runtime/agent-learning-state/events.jsonl` is a separate dev sink not indexed into the project dashboard/MCP state.
- The outer repo and inner `agent-learning-compounder/` directory can produce separate `.agent-learning` sandboxes.
- Dashboard action state such as promoted gates and muted domains is UI-writeable but not agent-complete through MCP.
- Root `.agent-learning/events.sqlite` looks like legacy or diagnostic state and can confuse the canonical project index story.

### F5 - CRUD lifecycle coverage is incomplete

Only dashboard action records have full CRUD-like coverage. Most entities are create/read or append-only without explicit update/archive/delete semantics.

Entity gaps include events, gates, recommendations, proposals, outcomes, capabilities, reports, suggestions, agent definitions/invocations, and skill usage.

The system should either expose explicit lifecycle verbs or document an append-only rationale per entity.

### F6 - UI integration is polling and snapshot-first

The FastAPI/React dashboard uses a shared read model and polls `/api/data`, which is a good foundation. It is not a live evented UI.

Risks:

- No SSE, WebSocket, or event bus.
- Generic MCP writes can remain invisible until indexing runs.
- MCP proposal queue writes are not included in the React read surface.
- Static and stdlib dashboards are snapshot-first.
- Dashboard live URL markers can become stale after crashes because there is no TTL or process probe.

### F7 - Capability discovery exists but is fragmented

Discovery mechanisms exist across README, context docs, MCP catalog, capability map, skills, dashboard empty states, and `list_capabilities`.

Gaps:

- No single `/alc-help` or `/tools` style command.
- No dashboard capabilities panel.
- First-run output does not clearly enumerate installed hooks, SQL/index state, dashboard status, MCP tool availability, and command surfaces.
- Some documentation has stale MCP count/list drift.

### F8 - Too much behavior is code-defined instead of prompt-native

Prompt-native surfaces exist in `alc-reviewer`, `alc-next`, `alc-dashboard`, and agent prompt definitions.

Code-owned workflow behavior remains high in:

- `alc_next_action.py` ranking and skill selection.
- `recommender_generators.py` recipes.
- `distill_learning` gate/rule/scoring logic.
- `dashboard/actions.py` mutation behavior.
- `alc_live_check` workflow checks.
- release/readiness validation scripts.

The preferred direction is primitive tools plus prompt-owned policy where possible.

## Strengths

- MCP read/propose/observe catalog is substantial and useful.
- `StateHandle` gives a coherent repo-local shared-state model.
- Dashboard read model centralization is a good UI integration foundation.
- `exec_sandbox` provides a powerful escape hatch for missing semantic tools.
- Session context generation already captures important repo and capability data.
- `list_capabilities` is a strong meta-discovery primitive.
- Hook, refresh, report, dashboard, and MCP surfaces are converging on shared repo state.

## Risks

- Relying on `exec_sandbox` as the parity story makes the system hard for agents to use safely and consistently.
- Stale documentation can make release/install claims untrustworthy.
- Incomplete lifecycle verbs make proposals, patches, gates, and recommendations hard to manage cleanly.
- Path-sensitive repo identity can cause agents and UI to read/write different state.
- Polling/snapshot dashboard behavior can hide agent actions until a refresh/index event happens.
- Code-owned decision logic makes the system less adaptable to agent reasoning.

## PLAN_ITEMS

### P1 - Add semantic MCP parity for dashboard actions

- id: `P1`
- priority: `P0`
- status: `todo`
- type: `feature`
- owner_surface: `alc_mcp`, `dashboard`
- goal: Add agent-callable tools for dashboard action workflows.
- scope:
  - Add `run_distill(repo, mode?)`.
  - Add `list_action_jobs(repo)`.
  - Add `get_action_job(repo, job_id)`.
  - Add `get_action_state(repo)`.
  - Add `promote_gate_action(repo, gate_id)`.
  - Add `unpromote_gate_action(repo, gate_id)`.
  - Add `mute_domain(repo, domain)`.
  - Add `unmute_domain(repo, domain)`.
  - Add `get_latest_report(repo, format)`.
- acceptance:
  - Agent can perform every dashboard mutation without `exec_sandbox`.
  - Dashboard action state is readable through MCP.
  - Tool responses are structured and include status, paths, and user-visible next steps.

### P2 - Split `next_action` into primitive signals plus prompt-native decision

- id: `P2`
- priority: `P0`
- status: `todo`
- type: `refactor`
- owner_surface: `alc_next_action`, `skills/alc-next`, `alc_mcp`
- goal: Move ranking and decision prose out of the MCP primitive.
- scope:
  - Add `get_session_signals(repo)` or equivalent read-only primitive.
  - Keep optional cache writing as explicit `write_next_action_cache`.
  - Update `/alc-next` skill to reason over returned signals.
  - Keep compatibility for current `next_action` callers during migration.
- acceptance:
  - MCP can return raw facts without choosing the work item.
  - `/alc-next` owns suggestion ranking in prompt space.
  - Existing `next_action` behavior remains available or has a documented migration.

### P3 - Define entity lifecycle contracts

- id: `P3`
- priority: `P0`
- status: `todo`
- type: `architecture`
- owner_surface: `StateHandle`, `alc_query`, `alc_propose`, `alc_mcp`
- goal: Make each core entity explicitly CRUD-capable or explicitly append-only.
- entities:
  - events
  - gates
  - recommendations
  - patch bundles
  - proposals
  - outcomes
  - dashboard artifacts
  - dashboard action records
  - skill context and usage
  - capabilities
  - agent definitions and invocations
  - reports and metrics
  - suggestions
- acceptance:
  - Each entity has documented create/read/update/archive/delete semantics.
  - MCP/CLI surfaces expose lifecycle verbs for mutable entities.
  - Append-only entities explain why update/delete is intentionally unsupported.

### P4 - Make writes refresh or index visible state

- id: `P4`
- priority: `P0`
- status: `todo`
- type: `fix`
- owner_surface: `event_writer`, `alc_propose`, `dashboard_read_model`, `index_events`
- goal: Prevent agent writes from silently staying invisible to the dashboard.
- scope:
  - Trigger indexing after generic MCP writes where needed.
  - Add a bounded refresh/index hook for `report_outcome`, `report_agent_event`, `propose_apply`, and `propose_gate`.
  - Include proposal queue state in the dashboard read model.
- acceptance:
  - A write through MCP is visible in `/api/data` without waiting for an unrelated stop hook.
  - Proposal queue entries appear in React dashboard data.
  - Tests cover write-to-read propagation.

### P5 - Add capability discovery command and dashboard panel

- id: `P5`
- priority: `P1`
- status: `todo`
- type: `feature`
- owner_surface: `commands`, `dashboard`, `reference-lib`
- goal: Give users and agents one place to inspect installed capabilities.
- scope:
  - Add `/alc-help` or equivalent command.
  - Add dashboard capabilities/status panel.
  - Include hooks status, SQL/index status, dashboard status, MCP tools, commands, and install/runtime status.
  - Keep MCP count/list generated from the live catalog.
- acceptance:
  - User can answer "is this installed and working?" from one command.
  - Dashboard shows whether hooks, SQL/index, MCP, and reports are active.
  - Docs no longer hand-maintain MCP tool counts.

### P6 - Add repo identity and state-sink diagnostics

- id: `P6`
- priority: `P1`
- status: `todo`
- type: `fix`
- owner_surface: `StateHandle`, `alc_init`, `runtime_topology`
- goal: Prevent outer/inner repo state confusion and invisible dev event sinks.
- scope:
  - Warn when repo resolution points at inner `agent-learning-compounder/` while outer repo has `.agent-learning.json`.
  - Add diagnostic for `.runtime/agent-learning-state/events.jsonl`.
  - Mark root `.agent-learning/events.sqlite` as legacy/diagnostic unless actively owned.
- acceptance:
  - Live check reports canonical repo state root.
  - Live check warns on inner-package state split.
  - Dashboard or report surfaces mention unindexed dev events when present.

### P7 - Make context freshness explicit

- id: `P7`
- priority: `P1`
- status: `todo`
- type: `fix`
- owner_surface: `alc_init`, `session_context_render`, `render_state_surface`, `hooks`
- goal: Ensure session-start context is current or clearly marked bootstrap-only.
- scope:
  - Stamp `latest-session-context.md` with freshness/source.
  - Refresh it during the regular refresh loop or document bootstrap-only semantics.
  - Inject compact `latest-next-action.json`, latest session report summary, branch, dirty status, active plan, and latest validation result.
- acceptance:
  - Session-start context clearly states freshness.
  - Agents see current workspace state without shelling out first.
  - Tests cover stale-context marker or refresh behavior.

### P8 - Move workflow recipes toward prompt-owned policy

- id: `P8`
- priority: `P2`
- status: `todo`
- type: `refactor`
- owner_surface: `recommender_generators`, `skills`, `agents`
- goal: Reduce code-owned policy and expose primitives for prompt-native assembly.
- scope:
  - Convert generator recipes into prompt templates plus primitive artifact tools where practical.
  - Keep `alc-reviewer` as a prompt-native agent/persona.
  - Avoid exposing full review workflows as single opaque tools.
- acceptance:
  - Generator code owns artifact creation/validation, not recommendation policy prose.
  - Prompt files own review and recommendation process language.
  - Tests cover primitive artifact behavior.

### P9 - Add live UI eventing or bounded fast refresh

- id: `P9`
- priority: `P2`
- status: `todo`
- type: `enhancement`
- owner_surface: `dashboard`
- goal: Reduce silent dashboard staleness.
- scope:
  - Add SSE/WebSocket/event bus, or lower-risk explicit refresh after write actions.
  - Add TTL/process probe for live dashboard URL markers.
  - Make static dashboard staleness explicit.
- acceptance:
  - Dashboard indicates last refresh and data age.
  - Live URL lookup does not return dead loopback markers as healthy.
  - Agent writes have an observable UI update path.

### P10 - Correct stale MCP and capability docs

- id: `P10`
- priority: `P1`
- status: `todo`
- type: `docs`
- owner_surface: `README`, `alc_mcp/README.md`, `reference-lib`
- goal: Keep public docs aligned with live tool catalogs and command surfaces.
- scope:
  - Update stale MCP tool counts and lists.
  - Fix capability-map rows that describe library modules as runnable CLI entrypoints.
  - Add docs freshness checks for MCP tool count/list.
- acceptance:
  - README, MCP README, and reference catalog agree with live `catalog.py`.
  - Docs freshness test fails on stale MCP counts.
  - Capability map distinguishes semantic MCP, real CLI, and `exec_sandbox` fallback.

## Suggested Implementation Sequence

1. P10 - Correct stale docs and capability map so future work starts from truthful surfaces.
2. P1 - Add MCP parity for dashboard actions because it gives immediate user-visible agent control.
3. P4 - Make writes visible in dashboard/read model so new tools prove themselves.
4. P2 - Split `next_action` into primitive signals and prompt decision.
5. P3 - Define lifecycle contracts and close high-value CRUD gaps.
6. P5 - Add capability discovery command and dashboard panel.
7. P6 - Add repo identity and state-sink diagnostics.
8. P7 - Make context freshness explicit.
9. P8 - Move workflow recipes toward prompt-owned policy.
10. P9 - Add live UI eventing or bounded fast refresh.

## Evidence Pointers

- `agent-learning-compounder/reference-lib/capability-map`
- `agent-learning-compounder/reference-lib/mcp-catalog`
- `agent-learning-compounder/alc_mcp/catalog.py`
- `agent-learning-compounder/alc_mcp/server.py`
- `agent-learning-compounder/bin/alc_next_action.py`
- `agent-learning-compounder/bin/session_context_render.py`
- `agent-learning-compounder/bin/state_handle.py`
- `agent-learning-compounder/bin/alc_query.py`
- `agent-learning-compounder/bin/alc_propose.py`
- `agent-learning-compounder/bin/dashboard_read_model.py`
- `agent-learning-compounder/dashboard/__init__.py`
- `agent-learning-compounder/dashboard/actions.py`
- `agent-learning-compounder/dashboard/web/src/App.tsx`
- `agent-learning-compounder/skills/alc-dashboard/SKILL.md`
- `agent-learning-compounder/skills/alc-next/SKILL.md`
- `agent-learning-compounder/agents/alc-reviewer.md`

