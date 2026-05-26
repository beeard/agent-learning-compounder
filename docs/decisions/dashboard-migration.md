# Dashboard Migration Decision

Decision: keep the existing `dashboard/` FastAPI + React surface and the newer `skills/alc-dashboard/` stdlib `http.server` surface coexisting for MVP.

Why: `skills/alc-dashboard/` adopts the read-only model required by R13 and is suitable for agent-native browsing of ALC artifacts. The existing `dashboard/` still owns the `muted-domains.json` workflow from R5, so deleting it now would remove an operator capability that has not been ported.

Muted domains preservation plan: preserve `dashboard/actions.py` atomic-write semantics for `muted-domains.json`. The stdlib dashboard remains read-only and must not modify `muted-domains.json`.

Migration timeline: after MVP, a follow-up unit will measure usage and, if the stdlib surface stabilizes, port the muted-domain behavior into `skills/alc-dashboard/` with equivalent atomic writes. After that port is verified, delete the legacy `dashboard/` surface.
