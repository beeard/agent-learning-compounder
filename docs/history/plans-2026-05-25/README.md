# Frozen — ALC plugin v2 refactor (2026-05-25)

The five plan documents + dispatch script in this directory drove the V1→V2
plugin refactor that landed in releases `2026.05.25` through
`2026.05.27+review7-plus2.2`. The CONSOLIDATED-REVIEW is the load-bearing
document: it captures the 16 ROOT findings from five independent review
passes, including ROOT 7 (2 sub-skills, not 4) that explains why the V1
plan was scrapped.

For active status: see `CHANGES.md` and `STRATEGY.md` at the repo root.

| File | What it is |
|---|---|
| `2026-05-25-alc-plugin-refactor.md` | V1 plan (scrapped) — kept for ROOT-traceability |
| `2026-05-25-alc-plugin-refactor-CONSOLIDATED-REVIEW.md` | Why V1 was scrapped (5-pass review, 16 ROOTs) |
| `2026-05-25-001-refactor-alc-plugin-rewrite-plan.md` | V2 plan (shipped) — executive view |
| `2026-05-25-001-refactor-alc-plugin-rewrite-plan-units.md` | V2 plan — 22 implementation units |
| `2026-05-25-001-LFG-INVOCATION-PROMPT.md` | Orchestrator prompt that drove the V2 build |
| `run-lfg.sh` | Dispatch script that fed the prompt to `codex exec` |
