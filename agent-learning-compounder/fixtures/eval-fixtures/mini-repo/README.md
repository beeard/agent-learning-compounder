# mini-repo: integration fixture

Used by integration tests that need a small but valid repo with a working
agent-learning state. Tests stage this directory into a TemporaryDirectory,
then build the `.agent-learning/repos/<rid>/` subtree by computing `rid` at
runtime via `state_paths.repo_id()` and copying the `seed/` files into place.

`seed/improvement-queue-near-dupes.jsonl` — two rows whose text is similar
enough to trip the trigram+Dice dedup at threshold 0.80.
