---
name: alc-dashboard
description: This skill should be used when the user asks to "open the alc dashboard", "show the dashboard", "view recommendations", "see pending patches", "inspect anomalies", "review the apply log", "open gates and insights", "show correlations", "show patterns", or any variant requesting a visual view of the agent-learning state. Also use when work touches the dashboard's tabbed views (Recommendations, Pending patches, Anomalies, Patterns, Correlations, Apply log, Gates & insights, Suggestions) or when an operator needs the copy/paste apply / defer / reject commands the dashboard surfaces. The dashboard is strictly read-only — all state mutations route through CLI commands the dashboard renders, never through HTTP POST.
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

## References

- `../alc-core/references/capability-map.md` — every dashboard section mapped
  to its slash command, MCP tool, and CLI partner. Load this to verify which
  signal a view should be showing.
- `../alc-core/references/architecture.md` — production architecture and
  trust boundaries enforced by the dashboard (read-only, no event-writer
  imports, no direct `events.sqlite` access).
- `../alc-core/references/output-schema.md` — schema of the durable artifacts
  the dashboard renders (`latest-approved-gates.md`, `latest-skill-context.md`,
  `recommendations.json`).
- `../alc-core/references/threat-model.md` — why state mutations stay in the
  CLI rather than HTTP POST routes.

## Implementation notes

The skill directory bundles the running web app: `server.py` (the FastAPI
service), `templates/` (Jinja2 shells), and `static/` (offline JS/CSS). The
report-renderer script `scripts/render_unified_report.py` is symlinked from
the package root so the path stays valid relative to this skill directory.
