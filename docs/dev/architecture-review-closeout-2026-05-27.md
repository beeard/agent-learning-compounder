# Architecture Review Closeout - 2026-05-27

Source review: `.runtime/reports/architecture-review-20260527-183248.html`

Status: closed after contract verification. The review produced five completed
module boundaries: Runtime Wiring, State Scope, Refresh Run, Dashboard Read
Model, and Proposal Lifecycle. This note is the durable closeout record; the
old report is no longer a live backlog.

## Verified Boundaries

| Boundary | Owner module | Adapter surfaces verified | Regression evidence |
|---|---|---|---|
| Runtime Wiring | `agent-learning-compounder/bin/runtime_topology.py` | `install_runtime_hooks`, `check_runtime_drift`, `scripts/merge_dev_hooks.py` | `tests/test_runtime_topology.py`, `tests/test_runtime_boundary.py`, `tests/test_install_runtime_hooks_taxonomy.py` |
| State Scope | `agent-learning-compounder/bin/state_handle.py` | `event_writer`, `alc_query`, MCP state handlers, render/query callers | `tests/test_state_handle.py`, `tests/test_event_writer.py`, `tests/test_alc_query.py`, `alc_mcp/tests/test_server.py` |
| Refresh Run | `agent-learning-compounder/bin/refresh_run.py` | `refresh_learning_state`, `alc_bootstrap_pipeline`, hook replay/index warm loop | `tests/test_refresh_run.py`, `tests/test_pr5_install_warm_loop.py`, `fixtures/tests/test_install_bootstrap.py`, `tests/test_index_events.py` |
| Dashboard Read Model | `agent-learning-compounder/bin/dashboard_read_model.py` | FastAPI `/api/data`, `bin/render_dashboard`, stdlib `/data.json` | `tests/test_dashboard_read_model.py`, `tests/test_dashboard_readonly.py`, `fixtures/tests/test_dashboard.py` |
| Proposal Lifecycle | `agent-learning-compounder/bin/proposal_lifecycle.py` | `alc_propose`, `alc_query`, recommender/eval metadata, MCP proposal tools | `tests/test_proposal_lifecycle.py`, `tests/test_alc_propose.py`, `tests/test_alc_query.py`, `tests/test_recommender_render.py`, `tests/test_alc_eval.py`, `alc_mcp/tests/test_server.py`, `alc_mcp/tests/test_mcp_catalog.py` |

## Contract Notes

- Runtime Wiring owns mode-specific command rendering, config targets, release
  install target selection, and drift-plan selection.
- State Scope owns project/user/background target selection, read-scope
  validation, user report paths, and event write-target classification.
- Refresh Run owns warm/full refresh orchestration, incremental hook replay,
  indexing, locking, stage ordering, and structured result payloads.
- Dashboard Read Model owns read-only dashboard payload assembly; mutable
  promote/mute/distill/action behavior remains outside it.
- Proposal Lifecycle owns proposal identity, lifecycle records, event payloads,
  and normalized read mirrors; `alc_propose.py` remains the CLI/MCP adapter.

## Future Review Candidates

These are candidates for a future architecture review. They are not unfinished
work from `architecture-review-20260527-183248`.

- Analyst pipeline protocol for the analyst quartet when a fifth analyst,
  conditional execution, shared progress reporting, or measurable subprocess
  overhead appears.
- Dashboard URL and server-marker hardening if localhost/static fallback
  behavior becomes operator-visible drift.
- Package/distribution bundle review if release artifacts or dashboard bundles
  start diverging across install paths.

Follow-up review `.runtime/reports/architecture-review-20260527-215034.md`
turned the package/distribution concern into a six-item architecture campaign.
Track that campaign in `docs/dev/architecture-review-campaign-2026-05-28.md`;
this closeout remains closed for the earlier five boundaries.
