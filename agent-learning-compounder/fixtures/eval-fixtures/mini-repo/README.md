# mini-repo: integration fixture

Used by integration tests that need a small but valid repo with a working
agent-learning state. Tests stage this directory into a TemporaryDirectory,
then build the `.agent-learning/repos/<rid>/` subtree by computing `rid` at
runtime via `state_paths.repo_id()` and copying the `seed/` files into place.

`seed/improvement-queue-near-dupes.jsonl` — two rows whose text is similar
enough to trip the trigram+Dice dedup at threshold 0.80.

### Retirement cohort fixture

`seed/hook-events-failure-cohort.jsonl` — 50 rows (25 sessions for `g_failgate12c` loaded with ~88% correction; 25 sessions with no gates loaded with ~40% correction). Drives P2B-C's "queue a retirement candidate" integration test.
