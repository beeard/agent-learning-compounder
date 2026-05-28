# Architecture Review Campaign - 2026-05-28

Source review: `.runtime/reports/architecture-review-20260527-215034.md`

Status: active campaign. The review identified six shallow seams where policy
was still repeated across adapters. Each plan/build cycle should complete one
coherent slice and leave this queue current.

## Campaign Queue

| Order | Recommendation | Status | Owner / next action |
|---|---|---|---|
| 1 | Release Metadata Module | Complete | `agent-learning-compounder/bin/release_metadata.py`; parity in `agent-learning-compounder/tests/test_release_metadata.py` |
| 2 | Release Layout Module | Complete | `agent-learning-compounder/bin/release_layout.py`; parity in `agent-learning-compounder/tests/test_release_layout.py` and archive fixture coverage in `agent-learning-compounder/fixtures/tests/test_contracts.py` |
| 3 | Dashboard URL Publisher Module | Complete | `agent-learning-compounder/bin/dashboard_url_publisher.py`; parity in `agent-learning-compounder/tests/test_dashboard_url_publisher.py`, launcher coverage in `agent-learning-compounder/tests/test_serve_dashboard.py`, and stdlib coverage in `agent-learning-compounder/tests/test_dashboard_readonly.py`. |
| 4 | Analyst Query Catalog Module | Complete | `agent-learning-compounder/bin/analyst_queries.py::QUERY_SPECS`; parity in `agent-learning-compounder/tests/test_analyst_queries.py`, `agent-learning-compounder/tests/test_capability_parity.py`, and `agent-learning-compounder/tests/test_render_catalogs.py`; mirror in `agent-learning-compounder/reference-lib/analyst-queries-catalog`. |
| 5 | Runtime Install Target Module | Complete | `agent-learning-compounder/bin/runtime_topology.py`; target-policy parity in `agent-learning-compounder/tests/test_runtime_topology.py` and shell behavior coverage in `agent-learning-compounder/tests/test_install_targets.py`. |
| 6 | Recommender Generator Registry Seam | Complete | `agent-learning-compounder/bin/recommender_generators.py::GENERATORS`; renderer routing in `agent-learning-compounder/bin/recommender_render`, target coverage in `agent-learning-compounder/bin/alc_apply_contracts.py`, catalog parity in `agent-learning-compounder/tests/test_render_catalogs.py`, and behavior coverage in `agent-learning-compounder/tests/test_recommender_generators.py` / `agent-learning-compounder/tests/test_recommender_render.py`. |

## Current Slice Evidence

- Release identity now has one canonical mapping for manifest, npm, Claude
  plugin, marketplace, and README-visible release strings.
- Release layout now has one canonical policy for shipped top-level archive
  contents, build-pruned paths, sanitizer exclusions, npm files, manifest docs,
  and manifest package exclusions.
- Dashboard URL publication now has one canonical policy for loopback live
  markers, token-safe cleanup, and static fallback ordering. FastAPI and stdlib
  launchers publish through the same module; `state_handle.dashboard_url` and
  MCP `get_dashboard_url` consume it.
- Analyst query identity, shape, callable backing, consumer metadata, dispatch,
  and human-readable reference output now route through
  `bin/analyst_queries.py::QUERY_SPECS`. Q11 and Q12 are public catalog entries,
  and drift guards compare public catalog entries, dispatch registration, M10
  capability parity, and checked-in reference output.
- Runtime install target policy now routes through `bin/runtime_topology.py`:
  runtime resolution, user-global roots, Codex-home roots, Claude plugin roots,
  explicit target roots, and repo bootstrap target expansion are covered by
  topology tests plus temp-home `install.sh` parity tests. `install.sh` remains
  the execution adapter for copying, backups, verification, dashboard builds,
  bootstrap hooks, and first-run indexing.
- Recommender generator identity, G-ID order, callable dispatch, output class,
  target-type metadata, and generator catalog mirrors now route through
  `bin/recommender_generators.py::GENERATORS`. `recommender_render` classifies
  patch bundles versus suggestions from registry metadata, `workflow_chain`
  remains suggestion-only, and `alc_apply_contracts` derives generator-emitted
  Hermes-DSL target types from the registry instead of a fallback map.
- Gate identity migration now routes through a shared gate registry parser and
  explicit alias chain. `bin/export_gates --rename OLD:NEW` is required before
  a same domain/category text edit changes `gate_id`; the canonical block owns
  `previous_gate_ids`, federation preserves it, `alc_query.get_gates` exposes
  it without duplicate rows, and effectiveness scoring normalizes historical
  event ids in memory.
- Public command names and intended runtime install semantics were not changed.

## Next Planning Rule

The six shallow-seam recommendations from the source review are complete, and
gate-system C3 is closed. Start the next plan from fresh review evidence; M6
hash-recipe migration and H3 causal-probe hardening remain separate candidates.
