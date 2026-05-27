# PR 3 — Make the dashboard show both scopes

> **For the next Claude session.** Self-contained brief. Drop the contents
> of this file into the next session and start.

## Where we are

Commits on `master` (no push yet):

| Commit | What |
|---|---|
| `986ccd0` | PR 2 — scope-aware read API + MCP catalog + next_action signal |
| `c24d01b` | PR 1 — rename `personal` → `user`, add `StateHandle.for_user`/`for_project` |
| `4c12fd9` | (pre-existing) chore(gitignore) |

What landed:

- **PR 1:** `AGENT_LEARNING_USER` env, `--user` CLI flag (alias `--personal`), `StateHandle.for_user(user_root=None)`, `StateHandle.for_project(repo)` (alias of `for_repo`). Old names still work for one minor release.
- **PR 2:** Every `alc_query.*` read takes `scope: Literal["user","project","both"]` (kw-only, default `"project"`). `get_gates` reads both state-roots and dedupes by `gate_id`; `_source_scope` tag added to each row (`"user"` or `"project"`). MCP catalog M1–M4 bumped to `version=2`. `next_action` signals now include `approved_gates: {total, user, project}`.

Live verification this repo:

- `scope="user"`: **3 gates** surface from `~/.agent-learning/reports/agent-learning/latest-approved-gates.md` — `repo-workflow`, `validation`, `scope-drift`. These have been silently accumulated by `auto_distill_session` since 2026-05-25 and were invisible to dashboard/MCP before PR 2.
- `scope="project"`: 0 (project events.sqlite still empty — that's PR 4's territory).

## PR 3 goal

The two state-roots are now visible to the API. Make the dashboard surfaces actually *show* them. Operator should see two views of the same surface: "This project" and "Across all your work."

No new pipeline work in PR 3 — purely a presentation change on top of PR 2's API.

## The five-PR plan (reference)

1. ✓ Rename `personal` → `user` (shim, no behavior change) — **shipped**
2. ✓ Scope-aware read APIs + MCP catalog — **shipped**
3. **← you are here** — Dashboard shows both scopes
4. Fix project-scope pipeline (B1 boundary check, B3 event_writer dir, B12 cursor; backfill the 4,309 rows already on disk)
5. Wire pipeline into install (npx / curl / `/plugin install` all bootstrap `index_events`)

## Files PR 3 touches

| File | Change |
|---|---|
| `agent-learning-compounder/dashboard/__init__.py` | The `/api/data` endpoint at ~line 190 builds the dashboard payload from `state` only. Add a parallel user-scope read, return both as a structured payload. Read paths: `alc_query.get_gates(state, scope="both")`, `get_skill_context(state, scope="both")`. |
| `agent-learning-compounder/skills/alc-dashboard/server.py` | Same pattern as the FastAPI shell. Lines 144–160 issue read calls — switch to `scope="both"` for gates + skill_context, keep `scope="project"` for events-backed reads. |
| `agent-learning-compounder/dashboard/templates/_gates.html` | Render a per-row badge or column indicating `_source_scope`. The `get_gates(scope="both")` rows already carry the field — just surface it. |
| `agent-learning-compounder/bin/render_dashboard.py` | If this file builds the payload that `_gates.html` consumes, propagate `_source_scope`. Verify with `grep get_gates render_dashboard.py`. |
| `agent-learning-compounder/dashboard/web/src/lib/data.ts` | React SPA fetches `/api/data`. If the JSON schema gains a `scope` field or grouped rows, update the type. React side is currently in `layer:dashboard` (41 nodes) per the knowledge graph. |

## Design decision the next session needs to make

Pick **one** of two presentation models:

**Option A — Single list, scope badge per row.** Each gate row gets a small `[user]` or `[project]` badge. Simpler. One table, one query. UI noise low. Loses the "across all your work" mental model — feels like a metadata field rather than two views.

**Option B — Two columns / tabs.** "This project" tab shows project-scope reads; "Across all your work" tab shows user-scope. Switching is a UI state, not another API call (both came from the same `scope="both"` payload, just filtered client-side). Clearer narrative; matches the architecture doc's framing.

Recommendation: **Option B for the operator dashboard** (the React SPA is set up for this — tab routing already exists in `dashboard/web/src/components/`). **Option A for the FastAPI/Jinja shell** (it's compact, no tab infra). They can coexist — different surfaces, different idioms.

## Concrete starting steps

```bash
cd /home/tth/work/active/agent-learning-compounder

# 1. Confirm both APIs return data live
python3 -c "
import sys
sys.path.insert(0, 'agent-learning-compounder/bin')
import alc_query, state_handle, pathlib
state = state_handle.StateHandle.for_repo(pathlib.Path.cwd())
gates = alc_query.get_gates(state, scope='both')
print(f'gates: {len(gates)} total, {sum(1 for g in gates if g[\"_source_scope\"]==\"user\")} user, {sum(1 for g in gates if g[\"_source_scope\"]==\"project\")} project')
"

# 2. Read current dashboard payload shape
sed -n '180,220p' agent-learning-compounder/dashboard/__init__.py

# 3. Update the /api/data handler to pass scope='both' for gates + skill_context
# 4. Update templates/_gates.html to render the badge
# 5. If touching the React SPA, also update data.ts type definition
```

## Tests to run after PR 3

```bash
cd agent-learning-compounder
python3 -m unittest discover -s fixtures/tests      # 251 — must stay green
python3 -m unittest discover -s tests               # 364 — must stay green
python3 scripts/run_pressure_tests.py               # 4 pressure gates

# Dashboard-specific:
python3 -m unittest tests.test_dashboard_readonly tests.test_render_dashboard 2>&1 | tail
```

## Knowledge graph snapshot

The `/understand` graph from this session lives at
`.understand-anything/knowledge-graph.json` (1.2 MB, 1351 nodes, 1633
edges, 8 layers, 15 tour steps). The `dashboard` layer has 41 nodes —
FastAPI/Jinja shell + React SPA + `skills/alc-dashboard/`. Use the
graph to navigate without re-scanning the repo.

## Constraints the user has set (don't violate)

- Keep both the top interface (3 install paths: npx / curl / claude marketplace) and the deep interface (`alc_query`/`alc_propose` seam) working.
- No new state roots. PR 3 reads from the two that already exist.
- Backwards compat: anything that worked with `scope="project"` (the default) must keep working unchanged.

## What NOT to do in PR 3

- Don't touch the pipeline (B1–B4 fixes are PR 4).
- Don't touch the installer (PR 5).
- Don't add a third state root or "team" scope. The user explicitly rejected that framing.
- Don't change the public MCP catalog signature again — it's already v2.

## When you're done

Commit message convention to follow:

```
feat(scope): dashboard surfaces user + project scopes (PR 3)
```

Push when the user says push. Then move to PR 4.
