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

Weights are derived from outcomes JSON when available:

`(1 + n_positive - n_negative) / (1 + n_positive + n_negative)`

Default is `1.0` when no outcomes are present.

## Scoring formula

`score = impact * confidence * outcome_weight * evidence_strength`
