# mini-repo: integration fixture

Used by integration tests that need a small but valid repo with a working
agent-learning state. Tests stage this directory into a TemporaryDirectory,
then build the `.agent-learning/repos/<rid>/` subtree by computing `rid` at
runtime via `state_handle.repo_id()` and copying the `seed/` files into place.

`seed/improvement-queue-near-dupes.jsonl` — two rows whose text is similar
enough to trip the trigram+Dice dedup at threshold 0.80.

### Retirement cohort fixture

`seed/hook-events-failure-cohort.jsonl` — 50 rows (25 sessions for `g_failgate12c` loaded with ~88% correction; 25 sessions with no gates loaded with ~40% correction). Drives P2B-C's "queue a retirement candidate" integration test.

### Inherited demote cohort fixture

`seed/hook-events-inherited-failure-cohort.jsonl` — 50 rows (25 sessions for `bbbbbbbbbbbb` loaded with 22/25 correction; 25 sessions with no gates loaded and 10/25 correction). Paired with `seed/inherited-gates-md-fragment.md`, which provides a gates.md block that carries a `derived_from:` line marking `bbbbbbbbbbbb` as inherited. Drives P4-C's "queue an inherited_gate_demote_candidate instead of gate_retirement_candidate" integration test.
