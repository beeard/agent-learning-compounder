---
title: "audit: Agent-native architecture review after hardening"
type: "audit"
status: "completed"
date: "2026-05-28"
origin: "docs/plans/2026-05-28-013-refactor-agent-native-hardening-plan.md"
---

# audit: Agent-native architecture review after hardening

## Summary

This audit reviews the current `agent-learning-compounder` working tree against
agent-native architecture principles after the hardening work from
`2026-05-28-013-refactor-agent-native-hardening-plan.md`.

Overall maturity is **67%**. The system is now credible as an agent-facing
architecture, especially around cataloged MCP capabilities, generated discovery
docs, shared project-state reads, and write-to-read propagation. The next
planning slice should focus on places where UI and agent surfaces appear
equivalent but still do not share the same implementation.

## Overall Score Summary

| Core Principle | Score | Percentage | Status |
| --- | ---: | ---: | --- |
| Action Parity | 10/21 | 48% | Needs work |
| Tools as Primitives | 30/32 | 94% | Excellent |
| Context Injection | 10/17 | 59% | Partial |
| Shared Workspace | 11/15 | 73% | Partial |
| CRUD Completeness | 10/15 | 67% | Partial |
| UI Integration | 7/10 | 70% | Partial |
| Capability Discovery | 5/7 | 71% | Partial |
| Prompt-Native Features | 5/9 | 56% | Partial |

**Overall Agent-Native Score:** 67%

## Top Recommendations By Impact

| ID | Priority | Action | Principle | Effort |
| --- | ---: | --- | --- | --- |
| ANR-001 | 1 | Unify FastAPI dashboard jobs and MCP dashboard jobs through `dashboard.actions`; currently job registries are split. | Action Parity, UI Integration | Medium |
| ANR-002 | 2 | Fix `run_distill` MCP script path to match FastAPI's `bin/auto_distill_session`. | Action Parity | Small |
| ANR-003 | 3 | Add `get_dashboard_payload`, `get_dashboard_health`, and latest report content parity tools. | Action Parity | Medium |
| ANR-004 | 4 | Render `proposal_queue` and `proposal_lifecycle` in React; they are in payload but UI-silent. | UI Integration | Medium |
| ANR-005 | 5 | Wire `workspace_facts` into `alc_init` or session-start context: branch, dirty state, active plan, latest next action, latest validation. | Context Injection | Medium |
| ANR-006 | 6 | Add proposal status mutation: accept, reject, close, supersede queue rows. | CRUD Completeness | Medium |
| ANR-007 | 7 | Add a real gate retirement/archive API instead of only retirement candidates. | CRUD Completeness | Medium |
| ANR-008 | 8 | Make `personal_root` resolution shared and explicit across dashboard, MCP, and `.runtime` archives. | Shared Workspace | Medium |
| ANR-009 | 9 | Label `next_action` and `run_distill` as workflow tools, or keep them out of primitive-only scoring. | Tools as Primitives | Small |
| ANR-010 | 10 | Move more recommendation ranking and workflow policy out of `alc_next_action.py` and generator code into skills/agents. | Prompt-Native Features | Medium |

## Strengths

- MCP catalog discipline is strong: 31 catalog tools, generated mirrors, parity
  tests, and `list_capabilities`.
- Most tools are primitives: read, query, propose, observe, and status
  operations are narrow and composable.
- Project-scope workspace is mostly shared through `StateHandle`, repo state,
  events, reports, patches, proposals, suggestions, and dashboard artifacts.
- Write visibility improved: `alc_propose` indexes writes so query/dashboard
  surfaces can see them promptly.
- Capability documentation is much stronger: `README.md`, `AGENTS.md`,
  `CLAUDE.md`, MCP README, capability maps, `/alc-help`, and generated catalog
  docs expose the system surface.

## Critical Gaps

### Action Parity

- Dashboard UI can do several actions agents cannot do exactly:
  - read the exact `/api/data` dashboard payload;
  - read `/api/health`;
  - fetch latest report content, not just metadata;
  - retry connection state;
  - perform UI-local copy/theme actions.
- Some UI-only actions may be acceptable exclusions, but they need explicit
  classification in the capability map.
- FastAPI dashboard jobs and MCP dashboard jobs are split:
  - FastAPI uses `dashboard.__init__.py` local `JobRegistry`;
  - MCP uses `dashboard.actions._JOBS`.
- `run_distill` defaults to a different script path from FastAPI.

### UI Integration

- Agent writes are queryable after indexing, but React only sees them after
  polling or manual refresh.
- `proposal_queue` and `proposal_lifecycle` are present in backend payloads but
  are not rendered in the React dashboard.
- Patch status changes can make pending patches disappear without a visible
  deferred/rejected status explanation.
- Distill job state is not actively displayed or polled in the dashboard.

### Context Injection

- The renderer supports freshness and workspace facts, but current session-start
  generation does not provide live branch, dirty state, active plan, latest next
  action, latest report, or latest validation result.
- Generated session context can drift from live MCP tool counts and repo profile
  facts.

### CRUD Completeness

- Proposal queue rows lack public lifecycle mutation for accept/reject/close.
- Gates lack a concrete retire/archive operation.
- Suggestions lack status/archive mutation.
- Capabilities and agent definitions are readable but not clearly first-class
  mutable entities.

### Prompt-Native Features

- `get_session_signals` and `alc-next` move in the right direction, but
  `next_action` still contains code-owned ranking and prose.
- Recommender generators still encode workflow-shaped policy in Python, even
  though metadata now names prompt ownership.

## Planning Notes

Recommended next plan slice:

1. Fix dashboard action parity first:
   - unify job registry;
   - fix `run_distill` script path;
   - add exact dashboard health/payload/report-content MCP reads.
2. Then render proposal lifecycle rows in React and add visible freshness/job
   status.
3. Defer broader lifecycle CRUD and prompt-native recommender migration until
   dashboard parity is no longer lying by omission.

## Evidence Pointers

- `agent-learning-compounder/alc_mcp/catalog.py`
- `agent-learning-compounder/alc_mcp/server.py`
- `agent-learning-compounder/dashboard/__init__.py`
- `agent-learning-compounder/dashboard/actions.py`
- `agent-learning-compounder/bin/dashboard_read_model.py`
- `agent-learning-compounder/bin/alc_next_action.py`
- `agent-learning-compounder/bin/lifecycle_contracts.py`
- `agent-learning-compounder/reference-lib/capability-map`
- `agent-learning-compounder/dashboard/web/src/App.tsx`
- `agent-learning-compounder/dashboard/web/src/components/ActionBar.tsx`
- `agent-learning-compounder/dashboard/web/src/components/ReadSurfacePanel.tsx`
