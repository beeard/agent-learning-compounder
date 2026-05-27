# Dashboard Migration Decision

Decision: keep the FastAPI + React dashboard as the canonical rich local UI, and keep `skills/alc-dashboard/` as the no-Node, read-only fallback.

The shared read boundary is `bin/dashboard_read_model.py`. FastAPI `/api/data`, `bin/render_dashboard`, and the stdlib fallback consume that module; project-scoped reads route through `bin/alc_query.py` or `StateHandle`.

Mutable dashboard behavior stays outside the read model. Promote, unpromote, mute, unmute, distill jobs, job status, and latest-report serving remain in the FastAPI shell/action layer. Proposal Lifecycle now owns proposal records and read mirrors, but it does not absorb dashboard-specific actions.

The stdlib dashboard remains GET-only. It may render recommendations, patches, apply logs, gates, insights, suggestions, and diagnostics from the shared read model, but it must not grow FastAPI action parity or write `muted-domains.json`.

Migration direction: future dashboard work should widen the shared read model and React components, not delete the FastAPI/React surface. Proposal-related queue, patch, suggestion, apply, eval, and outcome state should use `bin/proposal_lifecycle.py` plus `alc_query` read mirrors instead of adding dashboard-local proposal parsing.
