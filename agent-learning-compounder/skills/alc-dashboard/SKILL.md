---
name: alc-dashboard
description: Read-only ALC dashboard for recommendations, patches, events, and operator guidance.
---

# ALC Dashboard skill

Single-page dashboard for surfacing recommendation artifacts and operator-facing signals.
All actions are proposed as copy/paste commands; the dashboard itself is read-only.

## Supported usage

- Start with `scripts/render_unified_report.py` to run the read-only reporting pipeline.
- Open `http://127.0.0.1:<port>/` and use the tabbed views:
  - Recommendations
  - Pending patches
  - Anomalies
  - Patterns
  - Correlations
  - Apply log
  - Gates & insights
  - Suggestions
- On each patch card, run the emitted terminal command:
  - `bin/alc_apply --patch <id> --write`
- For state changes use CLI-only commands:
  - `bin/alc_apply --mark-deferred <id>`
  - `bin/alc_apply --mark-rejected <id>`

## Operating constraints

- No `POST /apply`, `POST /defer`, or `POST /reject` routes.
- No external CDNs; all assets are local.
- Keyboard and ARIA support on tabs.
- Only GET endpoints are exposed.

## Local endpoints

- `GET /` — HTML shell with embedded JSON payload
- `GET /data.json` — current dashboard data snapshot
- `GET /static/<file>` — offline static assets
