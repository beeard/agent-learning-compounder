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
| 3 | Dashboard URL Publisher Module | Queued | Next plan/build slice. Own live server marker state and static fallback policy across FastAPI, stdlib serving, static rendering, and MCP exposure. |
| 4 | Analyst Query Catalog Module | Queued | Make query id, shape, callable, consumer, and generated reference output one catalog contract. |
| 5 | Runtime Install Target Module | Queued | Move release install target selection behind runtime topology depth while keeping `install.sh` as execution adapter. |
| 6 | Recommender Generator Registry Seam | Queued | Make the generator registry the execution seam for identity, validation, reference output, and rendering. |

## Current Slice Evidence

- Release identity now has one canonical mapping for manifest, npm, Claude
  plugin, marketplace, and README-visible release strings.
- Release layout now has one canonical policy for shipped top-level archive
  contents, build-pruned paths, sanitizer exclusions, npm files, manifest docs,
  and manifest package exclusions.
- Public command names and runtime install semantics were not changed.

## Next Planning Rule

The next plan should start at order 3 unless a later architecture review
explicitly supersedes this campaign. Re-read the source review and current code
before planning; do not assume this file captures implementation details for
the queued items.
