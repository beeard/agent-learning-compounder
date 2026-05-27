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
| 4 | Analyst Query Catalog Module | Queued | Next plan/build slice. Make query id, shape, callable, consumer, and generated reference output one catalog contract. |
| 5 | Runtime Install Target Module | Queued | Move release install target selection behind runtime topology depth while keeping `install.sh` as execution adapter. |
| 6 | Recommender Generator Registry Seam | Queued | Make the generator registry the execution seam for identity, validation, reference output, and rendering. |

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
- Public command names and runtime install semantics were not changed.

## Next Planning Rule

The next plan should start at order 4 unless a later architecture review
explicitly supersedes this campaign. Re-read the source review and current code
before planning; do not assume this file captures implementation details for
the queued items.
