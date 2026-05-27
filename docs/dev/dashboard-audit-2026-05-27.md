# Dashboard surface audit — 2026-05-27

ALC ships **three dashboard surfaces** that look superficially similar but
have radically different shapes, data flows, and lifecycles. This audit
covers what each actually does, where its data comes from, what overlaps,
and why Tom is seeing ~1% of the information his repo holds.

Repos audited:
- Source tree: `/home/tth/work/active/agent-learning-compounder/agent-learning-compounder/`
- Live state — repo-local: `/home/tth/work/active/agent-learning-compounder/.agent-learning/repos/agent-learning-compounder-45819fdf8f74/`
- Live state — personal: `/home/tth/.agent-learning/`

2026-05-27 update: the dashboard read-model split identified here is now
addressed by `bin/dashboard_read_model.py`. FastAPI `/api/data`,
`bin/render_dashboard`, and `skills/alc-dashboard/server.py` consume the shared
read model; project reads route through `alc_query`/`StateHandle`. Mutable
dashboard actions remain in the FastAPI action layer.

---

## 1. Surface comparison table

| # | Name | Tech | Entry point | Data source | Action surface | Status |
|---|------|------|-------------|-------------|----------------|--------|
| 1 | `dashboard/` (FastAPI shell + React injector) | FastAPI + Uvicorn; serves React bundle | `bin/serve_dashboard.py` → `dashboard.build_app()` | `bin/dashboard_read_model.py` assembles archive data plus project read surface via `alc_query`/`StateHandle`. Action API reads `<personal>/actions/{promoted-gates,muted-domains}.json`. | 9 REST endpoints (see §4). Mutates `promoted-gates.json` and `muted-domains.json`; triggers `auto_distill_session`; serves latest report. | FastAPI/React is the canonical rich local UI. Bundle path is the React SPA — same physical file as surface 2. |
| 2 | `dashboard/web/` (React SPA) | Vite + React 18 + TypeScript + Tailwind + Recharts + Radix UI + lucide-react. Bundled to single 626 KB `dist/index.html` (vite-plugin-singlefile). | Built file at `dashboard/web/dist/index.html`; injected by surface 1 OR opened standalone | `src/lib/data.ts::readDashboardData()` reads the inline `<script id="alc-payload">`. If FastAPI is up: `useConnection` pings `/api/health`, then `apiGet("/api/data")` refreshes every 25 s. **Same data structure as surface 1.** | Buttons that call surface 1's `/api/*` endpoints (Re-run distill, Latest report, Copy command, Payload, theme toggle, gate promotion). Falls back to "Offline · static" badge when API absent. | **The good one** per Tom. Genuinely polished UI; lives or dies with what `metrics.jsonl` + `report-payload` already contain. |
| 3 | `skills/alc-dashboard/` (stdlib fallback) | Python `http.server` + `socketserver.ThreadingMixIn`; vanilla JS template + Alpine.js + handwritten `app.js` | `python3 skills/alc-dashboard/server.py` (loopback only; port-fallback aware) | `bin/dashboard_read_model.py::build_stdlib_payload()`, backed by `bin/alc_query.py` for recommendations, patches, apply log, actor summary, gates, skill context, and suggestions. | **None.** GET-only. `POST/PUT/DELETE/PATCH` all return 405. Per ADR R13, all writes stay on the CLI; the markdown bodies hand back ready-to-paste `bin/alc_apply` commands. | No-Node, read-only fallback. Renders the same read-model data without FastAPI actions. |

> The two surfaces named `dashboard/` (1) and `dashboard/web/` (2) are
> tightly coupled — (1) is mostly a *server wrapper around* (2)'s build
> output. They share the same JSON payload schema (`DashboardData` in
> `src/lib/data.ts`) and the same `<script id="alc-payload">` injection.

---

## 2. What each surface displays today

### 2.1 FastAPI dashboard (`dashboard/`) — populated state

`/` returns the React bundle with payload injected. So whatever surface 2
shows. With `~/.agent-learning/reports/agent-learning/` populated (494
`metrics.jsonl` rows, ~1000 dated reports, `latest-report.html` with
embedded payload):

- Header: "repo unknown" (because `payload.repo` is `null` in every metrics
  row — `baseline.repo` not set in this corpus)
- KPI strip with 5 sparklines (gates, evidence_lines, corpus_meta,
  user_lines, skill_alerts). All non-zero except skill_alerts.
- TrendChart + DomainHeat stacked-bar both render from 494 rows.
- GateStabilityTable lists `{domain}::{gate_category}` pairs aggregated
  across runs.
- RunHistory: chronological list of distill runs.
- SkillPanel: **always empty** on this corpus — `skill_inventory.available_count`,
  `skill_usage.expected/loaded/applied`, `skill_health.*` are all empty
  because the distill output doesn't fill them and they're sourced from
  state files (`skill-usage.json` is 3 bytes, `skill-impact.json` is 3 bytes,
  `skill-map.json` has 19k of skill metadata but isn't projected into the
  distill payload).

With the **repo-local** state (the actual agent state directory), 
`<personal>/reports/agent-learning/metrics.jsonl` does not exist, no
report is ever found, and the bundle falls back to the `{_placeholder:true}`
JSON — so the React app paints headers + the "No runs recorded yet. Run
distill --write to populate this dashboard." string and every card empty.

### 2.2 React SPA (`dashboard/web/`) — empty vs populated

- **Empty** (placeholder or fresh repo): "Tracking & metrics" header,
  zero-value KPIs (no sparklines), "No history yet." in DomainHeat,
  "No data yet." in GateStabilityTable and RunHistory, SkillPanel empty
  state.
- **Populated** (as above): the polished output that Tom called amazing —
  but bottlenecked entirely on the fields above. **The components draw
  exactly what's in `payload.totals`, `payload.agent_compensation.rows`,
  `payload.skill_inventory/usage/health`, and `history[*].by_domain`.**
  That schema is *narrower* than the data ALC actually holds.

### 2.3 stdlib dashboard (`skills/alc-dashboard/`) — populated state

`/` returns `dashboard.html` with `{{ ALC_DASHBOARD_DATA }}` replaced by
the JSON blob built in `server.py::build_data_blob()`. UI: 8 ARIA tabs
with vanilla JS handlers, no SPA framework.

Tabs and what they query:

| Tab | Source | Verdict on this repo today |
|-----|--------|----------------------------|
| Recommendations | `alc_query.get_recommendations()` (reads `recommendations.json`) | Empty — file is 163 B `{"recommendations":[],"fallback_mode":true}`. Tab: "No records yet." |
| Pending patches | `alc_query.get_pending_patches()` (lists `<repo_state>/patches/*.json`) | Empty — no patches dir. |
| Anomalies / Patterns / Correlations | `_bucket_recommendations(recommendations)` | All three buckets empty because the source list is empty. |
| Apply log | `alc_query.get_apply_log()` (SELECT from `events.sqlite` WHERE event LIKE 'patch_%') | **Empty even though hook-events.jsonl has 4538 rows** — see §4 root cause. |
| Gates & insights | Raw `latest-approved-gates.md` + `latest-skill-context.md` + `actor_summary` | Gates: "domains: none". Insights: "no alerts". Actor summary: 0 events. |
| Suggestions | reads `<repo_state>/suggestions.json` inline | Empty — file doesn't exist. |

Same fundamental problem: schema is right; sources are dry.

---

## 3. Data flow trace

```
Surface 1 (FastAPI)         Surface 2 (React)         Surface 3 (stdlib)
─────────────────           ─────────────────         ──────────────────

dashboard.__init__.py       dashboard/web/src/*.tsx   skills/alc-dashboard/server.py
        │                            │                          │
        ▼                            ▼                          ▼
render_dashboard.build_     readDashboardData() reads  bin/alc_query.* (KTD-21)
  dashboard_data():           <script id="alc-payload"> 
   • find_latest_payload()    in the served HTML.       state_handle.StateHandle
     finds report-payload     If alone: placeholder.    .for_repo() → resolves
     in latest-report.html    If injected by (1): full   <repo>/.agent-learning/
   • read_history() reads     payload from (1)'s        repos/<repo-id>/
     metrics.jsonl            /api/data hit.
                                                       reports SQL: events.sqlite
   <personal>/                <same as (1) when         JSON: recommendations.json,
   reports/agent-learning/    served by (1); else        patches/*.json,
                              file:// placeholder>      suggestions.json
                                                       MD: latest-approved-gates.md
                                                           latest-skill-context.md
   actions: <personal>/
   actions/{muted,promoted}.json
   → distill_learning reads
     muted-domains.json
```

**Key observation:** surface 3 is the only one that consumes the canonical
KTD-21 read API. Surfaces 1 and 2 reimplement reads inline (grep
`alc-payload`-injected HTML, parse a regex-matched `report-payload`,
walk `metrics.jsonl`) — they don't go through `alc_query.py` at all.

The implication is that any future evolution of the read seam (new tables,
new aggregates, gate effectiveness, causal probe outputs, queue dedup,
domain rules learning) **does not reach the React UI** until somebody
updates `distill_learning.py`'s payload shape or
`render_dashboard.build_dashboard_data()`.

---

## 4. Why the React dashboard shows ~1% — multiple compounding causes

### 4a. `events.sqlite` is empty on every repo (root cause for stdlib + actor data)

Confirmed:
- `/home/tth/work/active/agent-learning-compounder/.agent-learning/repos/agent-learning-compounder-45819fdf8f74/events.sqlite`: **0 rows in `events`**, schema_version 4 intact.
- Sibling cursor file `events.sqlite.cursor`: contains `0`.
- `hook-events.jsonl`: 4538 lines, 1.3 MB.
- `events.jsonl`: 4309 lines, 1.3 MB.

`index_events` is **never called** by `auto_distill_session`,
`distill_learning`, `refresh_learning_state`, the hook scripts, or
`install_runtime_hooks`. The indexer exists at `bin/index_events.py` and
is expected to advance the cursor and write rows, but no flow invokes it.
Result: every `alc_query` function that depends on `events.sqlite`
(`get_apply_log`, `get_outcomes`, `get_actor_summary`,
`get_skill_usage_summary`, `get_event_dag`, `get_skill_invocation_history`)
returns `[]`. That hollows out the stdlib dashboard *and* would hollow out
the React SkillPanel if it were ever wired through the same seam.

### 4b. The React dashboard reads `<personal>` not the repo-local state

`render_dashboard.find_latest_payload(personal)` walks
`personal/reports/agent-learning/`. With `AGENT_LEARNING_PERSONAL` unset
and no `--personal` flag, it defaults to `~/.agent-learning/`. That root
has 494 metrics rows and 500+ dated reports — that's the data Tom saw
working. The **repo-local** state under
`<repo>/.agent-learning/repos/<id>/reports/` has only
`latest-approved-gates.md` (5 lines, "domains: none"),
`latest-skill-context.md` (no alerts), and `latest-next-action.json` —
**no `metrics.jsonl`, no `latest-report.html`**.

So the React dashboard is split-brain: the polished UI displays personal-
archive history while the rest of ALC (gates, recommendations, MCP
read-side, hooks, dashboard URL marker) keys off the repo-local state.
If Tom expects "see my repo's state in the React dashboard," that
expectation is structurally violated by the current code.

### 4c. The payload schema is narrower than what ALC produces

The React surface only consumes `DashboardData` = `{generated_at,
personal_root, latest: ReportPayload, history: MetricsRow[]}`. Notably
absent from `ReportPayload`:

- Recommendations / anomalies / patterns / correlations
  (`recommendations.json`)
- Pending patches (`patches/*.json`)
- Apply log (`events.sqlite` patch_%)
- Domain-rules-learning output (`propose_domain_rules` rows)
- Gate effectiveness signals (`evaluate_gate_effectiveness` per gate_id)
- Causal probe cohorts (`causal_probe`)
- Cross-repo promoted/inherited gates (`gates_promote` / `gates_inherit`
  with `derived_from:` provenance)
- Queue dedup metrics
- MCP tool catalog / call history
- Hook event log summaries
- Next-action recommendation (`latest-next-action.json`)
- Skill-impact correlations (`skill-impact.json`)
- Skill-map metadata (19 KB sitting in `skill-map.json`)

These are *all* surfaced by the stdlib dashboard's tabs (which the React
SPA lacks) or by MCP tools, **but never reach the React UI**, even when
the underlying data files are populated.

### 4d. Hide-instead-of-explain empty states

`KpiCards` shows a `0` with no explanation. `SkillPanel` collapses to a
single line ("No skill telemetry in this filing"). `DomainHeat` collapses
to "No history yet." None of these tell the operator *why* the data is
missing (events not indexed, distill never ran with `--write`, personal
root resolved wrong, no patches generated yet). A "diagnostic mode" would
be much more useful than empty cards.

---

## 5. Overlap matrix

| Capability | Surface 1 (FastAPI) | Surface 2 (React) | Surface 3 (stdlib) |
|------------|---------------------|-------------------|-------------------|
| KPI cards w/ sparklines | via 2 | yes | no |
| Trend chart (gates over time) | via 2 | yes | no |
| Domain heat (stacked bar) | via 2 | yes | no |
| Gate stability table | via 2 | yes | no |
| Run history list | via 2 | yes | no |
| Skill telemetry panel | via 2 | yes (placeholder-driven) | no |
| Recommendations tab | no | no | yes |
| Pending patches tab | no | no | yes |
| Anomalies / Patterns / Correlations tabs | no | no | yes |
| Apply log tab | no | no | yes |
| Suggestions tab | no | no | yes |
| Gates & insights tab | partial (raw `.md` via `/api/reports/latest`) | yes (gate stability synthesis) | yes (raw markdown render) |
| Promote/unpromote gate (write) | yes (`/api/actions/{promote,unpromote}`) | yes (UI button) | **no — by ADR R13** |
| Mute/unmute domain (write) | yes (`/api/actions/{mute,unmute}`) | yes (UI button) | **no — by ADR R13** |
| Trigger distill (`auto_distill_session`) | yes (`/api/actions/distill`, threaded) | yes (UI button) | no |
| Job tracking | yes (`/api/actions/jobs`, in-memory `JobRegistry`) | yes (toast + poll) | no |
| Latest report HTML/MD | yes (`/api/reports/latest{,.md}`) | yes (button) | no |
| Health/ping | yes (`/api/health`) | yes (`useConnection`) | no |

**Unique to each:**
- Surface 1 only: the action API + job tracking + report proxy.
- Surface 2 only: every visual element (sparklines, charts, heat, table,
  skill panel).
- Surface 3 only: every tab that surfaces recommendations / patches /
  apply-log / suggestions / raw gates+insights markdown.

**Net:** the React app is visually richer; the stdlib app surfaces 7
artifact classes the React app doesn't know about. They're complements,
not duplicates. The FastAPI shell is the only one with operator-driven
mutation.

---

## 6. The /api/* action surface

`dashboard/__init__.py` exposes (in addition to `/`):

| Method | Path | Implementation | Mutation |
|--------|------|----------------|----------|
| GET | `/api/health` | inline | none |
| GET | `/api/data` | `render_dashboard.build_dashboard_data` + `dashboard.actions.actions_summary` | none |
| POST | `/api/actions/distill` | spawns `bin/auto_distill_session` in a thread; in-memory `JobRegistry` | side-effect: distill run (writes to `<personal>/`) |
| GET | `/api/actions/jobs` | `JobRegistry.list()` | none |
| GET | `/api/actions/jobs/{job_id}` | `JobRegistry.get()` | none |
| POST | `/api/actions/promote` | `dashboard.actions.promote_gate` → atomic write `<personal>/actions/promoted-gates.json` | yes |
| POST | `/api/actions/unpromote` | `dashboard.actions.unpromote_gate` → atomic write | yes |
| POST | `/api/actions/mute` | `dashboard.actions.mute_domain` → atomic write `<personal>/actions/muted-domains.json` | yes (consumed by `distill_learning._load_muted_domains`) |
| POST | `/api/actions/unmute` | `dashboard.actions.unmute_domain` → atomic write | yes |
| GET | `/api/actions/state` | `actions_summary` | none |
| GET | `/api/reports/latest` | reads `<personal>/reports/agent-learning/latest-report.html` | none |
| GET | `/api/reports/latest.md` | newest `.md` in same dir | none |

**Is the muted-domains write workflow still load-bearing?** Yes — verified
via grep: `bin/distill_learning::_load_muted_domains()` reads
`<personal>/actions/muted-domains.json` and applies it during
classification (line 518). On this machine the file exists but is empty
(`[]`); the dashboard *has* been used to promote 3 gates
(`promoted-gates.json` has `repo-workflow::repo-gate`,
`validation::validation-check`, `scope-drift::scope-gate`).

So the ADR's stated migration plan is technically still valid: muted-
domains is a real operator workflow that the stdlib dashboard does not
yet provide. But see §8 — there are better ways to satisfy that than
forcing the muted-domains workflow into the stdlib surface.

---

## 7. Build & deploy story — the friction Tom hit

`dashboard/web/dist/` is **gitignored** (`agent-learning-compounder/.gitignore:16`).
`scripts/sanitize_skill_tree.sh:17` runs a `find … -name dist -prune` and
**deletes any `dist/` directory from the release archive** before
tarballing. `package.json::files` does not list `dashboard/web/dist/`,
so npm publish doesn't carry it either. There is no `postinstall` hook
in `package.json` and `install.sh`/`bootstrap.sh`/`scripts/alc-install.mjs`
contain zero references to `pnpm`, `npm`, or `vite`.

Concretely:

1. Operator runs `npx alc-install`.
2. Skill tree lands in `~/.claude/skills/agent-learning-compounder/`.
3. `dashboard/web/dist/index.html` is not there.
4. Operator runs `python3 scripts/serve_dashboard.py`.
5. FastAPI surface returns the `_fallback_html()`: "Dashboard bundle
   missing. Build it once: cd dashboard/web && pnpm install && pnpm
   build". Returns HTTP 503.
6. Operator must have Node + pnpm installed, 2234 modules of network +
   disk for a one-shot view.

That is exactly what Tom did. This is the single biggest reason this UI
isn't getting used: the world's nicest dashboard hidden behind a build
step the operator must do by hand, with no progress indicator and no
"oh by the way, you also need pnpm".

**There is a strong case to commit the built `dist/index.html` to git
and ship it in the npm tarball.** It's 626 KB, single-file, no
runtime fetches. That kills the friction completely. The downside is
build-output noise in git diffs — but the file is already the inlined
artifact of a determinstic build (`vite-plugin-singlefile`), so it
churns rarely (every dashboard change) and a `.gitattributes` `binary`
marker would hide the diff.

---

## 8. `get_dashboard_url` MCP tool — where does it point?

`bin/state_handle.dashboard_url(repo)`:

```python
marker = handle.dashboard_dir / "server.json"
if marker has "url" starting with http://127.0.0.1: → return that
index = handle.dashboard_dir / "index.html"
return index.resolve().as_uri() if exists else handle.dashboard_dir.resolve().as_uri()
```

On this repo: `<repo>/.agent-learning/repos/<id>/dashboard/` contains
`dashboard.html` (the stdlib template, 2.5 KB) and `data.json` (a snapshot,
2.4 KB) — but **no `server.json`** and **no `index.html`**. So the MCP
tool returns `file://…/dashboard/` (a directory URI). That's: (a) not a
working dashboard, (b) not the React one, (c) not the stdlib one running
in a server, (d) just a static folder listing. Tom is unlikely to find
the good experience this way.

The `server.json` marker would have to be *written by whichever server
process is currently bound to loopback* — neither `serve_dashboard.py`
(FastAPI) nor `skills/alc-dashboard/server.py` (stdlib) writes that file
today.

---

## 9. Recommendation

Tom's reaction ("fucking amazing but 1%") tells us two true things at once:
the React UI is the keeper, AND it doesn't reach 99% of what ALC
already knows. The ADR's "stdlib is the new direction; delete the legacy
FastAPI/React" call **was probably wrong, written before the React
surface looked like this.** It should be revisited.

Proposed direction:

1. **Promote the React UI to canonical.** Ship the `dist/` bundle in the
   npm tarball and the release archive. Drop the operator-builds-it
   friction. Add `dashboard/web/dist/index.html` to `package.json::files`
   and remove the `dist` pruning from `sanitize_skill_tree.sh`. Optionally
   gitignore the source `dist/` and add a published-snapshot file instead;
   or just commit it and accept the diff churn.

2. **Fix the empty-events.sqlite root cause first.** Add an
   `index_events` invocation at the start of `auto_distill_session` and
   `refresh_learning_state`. Without this, no dashboard helps. This is
   the source of the "1% information" complaint.

3. **Resolve the personal-vs-repo-local split-brain.** The React payload
   builder should resolve `personal` the same way the rest of ALC does
   (state-handle precedence: repo-local first). Today it defaults to
   `~/.agent-learning/`, which is why Tom is looking at the wrong corpus.

4. **Addressed: widen the React payload schema** to include what the stdlib
   dashboard already surfaces: recommendations, pending patches, anomalies/
   patterns/correlations, apply log, suggestions, next-action,
   actor_summary. `bin/dashboard_read_model.py` now pipes read payloads through
   `alc_query`/`StateHandle`; React types include the canonical `read_surface`.

5. **Keep the FastAPI shell.** It owns the write API (promote / mute /
   distill / job registry) which the stdlib surface cannot provide without
   violating ADR R13. The decision under R13 is fine for *what the stdlib
   dashboard exposes* — it just isn't a reason to delete the FastAPI shell
   that wraps the React UI.

6. **Demote the stdlib surface to "no-Node fallback".** Keep it
   buildable, keep it loopback-only, keep it read-only. Don't port the
   muted-domains workflow into it; instead, route operators to the
   FastAPI surface for any mutation. The stdlib dashboard's `app.js`
   tabs become the design spec for the missing tabs in the React UI.

7. **`get_dashboard_url` should look in two places.** Prefer the
   `server.json` marker (so a running FastAPI/stdlib server can broadcast
   its URL), then fall back to the `latest-dashboard.html` rendered by
   `render_dashboard.render()` (which is a working bundle, not a stub
   directory). The current "static folder URI" fallback is misleading.

8. **Addressed: update the ADR.** `docs/decisions/dashboard-migration.md`
   now records FastAPI + React as canonical, stdlib as the no-Node fallback,
   Dashboard Read Model as the shared read boundary, and mutable actions as
   FastAPI-owned until Proposal Lifecycle.

---

## 10. Appendix — concrete file evidence

- React bundle present, gitignored: `agent-learning-compounder/dashboard/web/dist/index.html` (626 KB, mtime 2026-05-25)
- React bundle pruned from releases: `scripts/sanitize_skill_tree.sh:17`
- Npm `files` array missing dist: `package.json:31-42`
- Indexer never called: `git grep index_events bin/` returns matches only inside `index_events.py` itself
- Events.sqlite empty: `sqlite3 events.sqlite "SELECT COUNT(*) FROM events"` → 0; cursor file → 0; jsonl → 4538 lines
- Split-brain personal vs repo-local: `~/.agent-learning/reports/agent-learning/metrics.jsonl` has 494 rows; `<repo>/.agent-learning/repos/<id>/reports/` has 4 files, no metrics
- Muted-domains is still load-bearing: `bin/distill_learning:518` calls `_load_muted_domains(personal)` → reads `<personal>/actions/muted-domains.json`
- Tom has used the promote workflow: `~/.agent-learning/actions/promoted-gates.json` has 3 entries from `"by": "dashboard"`
- `get_dashboard_url` returns dir URI: `bin/state_handle.py:171-180`, no `server.json` or `index.html` in repo-local `dashboard/` dir
- ADR predates the React app's current quality: `docs/decisions/dashboard-migration.md` (5 lines, treats the React app as legacy)
