# Analyst methods (U8)

This unit evaluates four classes of signals from `events.sqlite`:

- Frequency patterns: grouped counts over actor + skill and co-occurrence by DAG edges
- Anomalies: z-score and IQR outlier detection
- Correlations: joined relationships across the event graph (gate effectiveness, parent→child cost)
- Ranking: evidence-weighted scoring with outcome feedback

## Statistical conventions

- `z-score` on duration is computed on `telemetry_duration_ms` within each bucket.
- `IQR` bounds are derived from Tukey quartiles and used for token/cost tails.
- Only buckets with `n >= min_n` are considered. Default `min_n=4`.
- Evidence strength for scoring is `log(N)` where `N` is supporting event count.

## Evidence requirements

All script outputs attach an `evidence` object with
`event_ids: list[str]` where ids are rows from `events.sqlite`.
Fallback mode uses `samples.json` when `events.sqlite` is unavailable.

## Outcome weighting (score)

Weights are derived from `eval_verdict` events emitted by `bin/alc_eval` (see KTD-13).
Per the plan, the canonical surface is `alc_query.get_outcomes(state)` reading from
`events.sqlite`. The aggregation formula:

`(1 + n_positive - n_negative) / (1 + n_positive + n_negative)` per recommendation kind.

Default is `1.0` when no verdicts exist for a kind.

**Implementation status:** `bin/analyst_score._load_outcome_weights` currently reads
a legacy `outcomes.json` file that no producer writes. Migration to the
`alc_query.get_outcomes` SQL-view path is pending: it requires extending the
events.sqlite schema with a `payload_json` column (EventV4 dataclass currently omits
payload) so the verdict + recommendation_kind can be queried. Until then,
`outcome_weight` defaults to `1.0` in production.

## Scoring formula

`score = impact * confidence * outcome_weight * evidence_strength`
