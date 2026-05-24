# Domain Rules Learning

`bin/propose_domain_rules` mines the session corpus for n-grams that
correlate with session corrections. The proposer never modifies
`domain-rules.active.json` directly. It writes JSON proposals that
`refresh_learning_state.py` appends to `improvement-queue.jsonl` as
`kind: domain_rule_candidate`.

## Scoring

```
score(term) = correction_count(term) / (clean_count(term) + 1)
```

Higher score means the term appears disproportionately in
correction-tagged session chunks. The +1 in the denominator keeps the
score finite when a term never appears in clean chunks (which is the
strongest possible correlation signal but would otherwise divide by
zero).

## Approval workflow

Operators inspect queue entries and explicitly edit
`domain-rules.active.json` to incorporate the term. The proposer is
deliberately advisory — adding noisy seeds would hurt the
distillation classifier in `bin/distill_learning`.

When a domain seed is accepted, mark the queue row as resolved
(`status: resolved` is the suggested convention; the operator's queue
review tooling handles this).

## Tunables

- `--top-k 10` — proposals per refresh.
- `--min-score 2.0` — minimum score to surface.
- `STOP_WORDS` — a deliberately small list. Expand only on demand;
  large stop-word lists hide signal.
- `n_min, n_max` — default 1..2 (unigrams and bigrams). Trigrams are
  available via code edit but rarely score above the threshold without
  a much larger corpus.

## Corpus format

```
[session=<id> outcome=<state>] <chunk text>
```

`<state>` is `correction` or `clean`. Other states are dropped. Lines
without a matching header are skipped.
