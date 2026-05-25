# ALC Plugin Rewrite - Spike Results

Date: 2026-05-25
Wave: W1
Unit: U1 (Worktree + baseline test snapshot)

## Baseline verification

- `python3 -m unittest discover -s fixtures/tests`
  - Ran `251` tests in `25.882s`
  - `OK (skipped=4)`
- `python3 -m unittest discover -s tests`
  - Ran `1` test in `0.000s`
  - `OK`
- `python3 scripts/run_pressure_tests.py`
  - `pressure checks passed: 4`

## Dashboard import check

- `import dashboard` succeeds.
- `dashboard.build_app()` currently raises: `ImportError: fastapi required for dashboard (pip install fastapi uvicorn)`

## Phase A gates (dry-run template)

- [ ] G0.5.1 — Premise validation (manual)
- [ ] G0.5.2 — Cross-runtime assumption check (manual)
- [ ] G0.5.3 — Data-schema discovery + path validation (manual)

### Decision (to be recorded after W2)

- `scope_collapse` = pending
- `phase_b_green_light` = pending
