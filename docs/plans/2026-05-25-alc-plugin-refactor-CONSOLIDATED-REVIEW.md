# ALC Plugin Refactor — Konsolidert Pre-Implementation Review

> **Status:** Plan SKAL IKKE implementeres som-er. 4 uavhengige review-pass har konvergert på samme kjerne-funn. Dette dokumentet samler ALT for én actionable changelist.

**Source plan:** `2026-05-25-alc-plugin-refactor.md` (samme katalog)

**Review-inputs (5):**

| # | Review | Format | Antall funn | Generert av |
|---|---|---|---|---|
| A | Architecture review | HTML, 9 kandidater | 4 STRONG / 3 WORTH / 2 SPEC | `/improve-codebase-architecture` (denne session) |
| B | Multi-persona doc-review | 7 reviewere | 53 findings | `/compound-engineering:ce-doc-review mode:headless` (denne session) |
| C | Agent-native audit | 5 rapporter + 3 scripts | ~49% overall score, 6 hovedkrav | Annen session (`/home/tth/alc-agent-native-audit-export-2026-05-25T17-16-05/`) |
| D | Adversarial deep-review | 11 findings (egen) | 3×100, 5×75, 3×50 confidence | `ce-adversarial-document-reviewer` (del av B) |
| E | `onecomai/workflow-engines` salvage review | Privat GitHub repo + shallow clone | Høy verdi som catalog/prompts, lav verdi som runtime | Denne session |

**Triangulering:** Samme rot-funn er identifisert av 7+ uavhengige perspektiv. Ingen single-source-call-outs prioriteres over de triangulerte uten egen begrunnelse.

---

## 1. TL;DR — én side

### Tre ting samtidig:

**(1) Premisset er empirisk uvalidert.** Goal ("specialist analyst surfaces patterns/anomalies/correlations the default distill misses") har null konkret evidens — ingen incident, ingen miss-eksempel, ingen baseline-vs-analyst sammenligning. **6 reviewere konvergerer her: AD#1, PR#F1, AN#exec-summary, SC#4, FE#4, CO#1.**

**(2) Data-substratet eksisterer ikke.** `samples.json = "[]"` hardkodet i orchestrator → `detect_anomalies` returnerer tom → `compute_correlations` tom → `score_recommendations` tom → `render_patch_bundle` 0 patches → dashboard's Apply-knapp (sentral UX-innovasjon) har ingenting å applye i 100% av kjøringer. Eksisterende `bin/auto_distill_session` gjør allerede den faktiske nyttige jobben. **Den andre sessionen har skrevet `alc-session-metrics-adapter.mjs` som løser dette.**

**(3) Apply-mekanismen har konkrete bugs + filosofisk overskudd.** Auth=0, path-traversal mulig, arbitrary file-write mulig, secrets lekker til apply-log, concurrency uten lock (single double-click korrupterer dashboardet), yaml-replace ødelegger på 5 dokumenterte måter. Agent-native-audit'en sier "fjern direct-apply fra MCP/dashboard helt — ALC skal observe + recommend, mutate er operator's job".

### Hva å gjøre

```
              ┌─────────────────────────────────────────────────────┐
              │  PHASE 0.5 — Validate (1 dag, blokker alt videre)   │
              └────────────────────┬────────────────────────────────┘
                                   ↓ (grønt: alle 3 gates passerte?)
                  ┌────────────────┴────────────────┐
              ┌───▼───┐                         ┌───▼───┐
              │ JA    │                         │ NEI   │
              └───┬───┘                         └───┬───┘
                  ↓                                 ↓
   Implementer revidert plan          STOPP. Reframe eller drop.
   (4 sub-skills → 2,                 Tom har 4 andre aktive
   inert patches + CLI apply,          prosjekter med klarere
   build synthesizer NÅ,               value-prop.
   keep gates queue-first)
```

### Mest impactfull endring: én linje

> Fjern setningen "specialist analyst that surfaces patterns/anomalies/correlations the default distill misses" fra goal-statement. Erstatt med konkret evidens-basert problem-statement etter Phase 0.5 spike. Det avgjør om Phase 4-12 i det hele tatt skal bygges.

---

## 2. Phase 0.5 — Validation Gates (1 dag, MÅ passere før Phase 1+)

Alle tre gates må gi grønn før neste fase. Hvis NEI på noen: stop og reframe planen.

### Gate G0.5.1 — Premiss-validering (4 timer)
**Spawnes av:** AD#1 ("specialist analyst's value never demonstrated") + PR#F1 + AN-#exec

```bash
# Dry-run de 4 analyst-scriptsene som standalone spike mot eksisterende corpus
mkdir -p /tmp/alc-spike
cd /home/tth/.agents/skills/agent-learning-compounder
python3 bin/extract_sessions --cwd ~ --days 30 --max-sessions 100 --output /tmp/alc-spike/corpus.txt
python3 bin/build_repo_baseline --repo ~ --output /tmp/alc-spike/baseline.json
# Kjør hver av de 4 analyst-scriptsene mot real data (bruker andre session's adapter)
node /home/tth/alc-agent-native-audit-export-2026-05-25T17-16-05/scripts/claude-insights-extracted.mjs --since 30d --json > /tmp/alc-spike/insights.json
node /home/tth/alc-agent-native-audit-export-2026-05-25T17-16-05/scripts/alc-session-metrics-adapter.mjs \
  --claude-insights-json /tmp/alc-spike/insights.json \
  --output /tmp/alc-spike/session-metrics.json
# Kjør analyst-prototypene manuelt og print top-10 recs
```

**Gate-spørsmål:** Er ≥3 av top-10 anbefalinger ikke-åpenbare OG handlingsklare?

| Resultat | Beslutning |
|---|---|
| ≥3 av 10 = ja | **Grønt** — premisset holder. Fortsett til G0.5.2. |
| <3 av 10 | **Rødt** — analyst surfacer støy, ikke signal. Drop Phase 4-12. Bygg evt. kun synthesizer + bedre SessionStart-nudges (én Phase). |

### Gate G0.5.2 — Cross-runtime-verifisering (1 time)
**Spawnes av:** FE#3 (`${CLAUDE_PLUGIN_ROOT}` Claude-only) + AD#8 (Codex AGENTS.md auto-load uverifisert)

```bash
# Verifiser ${CLAUDE_PLUGIN_ROOT} settes i Codex
codex --version 2>/dev/null || echo "Codex ikke installert"
# Sjekk om .codex-plugin/plugin.json discoveres
codex --print-loaded-plugins 2>/dev/null || echo "Codex har ikke --print-loaded-plugins"
# Manuell: start Codex-session i denne pluginen, kjør slash-command, se om CLAUDE_PLUGIN_ROOT er definert
```

**Gate-spørsmål:** Er begge sant?
1. `${CLAUDE_PLUGIN_ROOT}` (eller equivalent) er tilgjengelig i Codex
2. `.codex-plugin/plugin.json` discoveres av Codex

| Resultat | Beslutning |
|---|---|
| Begge ja | Grønt. |
| Bare AGENTS.md loades, ikke .codex-plugin/ | **Skaler ned cross-runtime**: drop `.codex-plugin/`, behold AGENTS.md, gjør parity-test content-level (samme description-string) ikke fil-level. |
| Ingenting auto-loades | **Drop cross-runtime fra Phase 1** helt. Kun Claude. Codex som manuell `python3 bin/X` brukstilfelle. |

### Gate G0.5.3 — Hook-events schema-verifisering (1 time)
**Spawnes av:** AD#3 ("Plan assumes per-session cost/tokens/duration but never verifies")

```bash
# Hvor finnes hook-events.jsonl i dag?
find ~/.agent-learning ~/.local/state/agent-learning -name "hook-events.jsonl" 2>/dev/null
# Sjekk én sample linje
head -1 $(find ~ -name "hook-events.jsonl" 2>/dev/null | head -1) | jq .
# Sjekk om session-report cost-tokens.json eksisterer
find ~/.claude -name "session-report*.json" -mtime -30 2>/dev/null | head -3
```

**Gate-spørsmål:** Har vi en path til `samples.json` med `{id, cost, tokens, duration_s}`?

| Resultat | Beslutning |
|---|---|
| Ja, hook-events har det rett (eller session-report skriver en parseable fil) | Grønt. |
| Nei, må syntetiseres fra flere kilder | Bygg adapter (`alc-session-metrics-adapter.mjs` finnes allerede, vurder gjenbruk) som Phase 1 prerequisite. |
| Ingen data-kilde tilgjengelig | Analyst-premisset feiler uansett G0.5.1-resultat. Drop Phase 4. |

---

## 3. Root Issues (rangert etter triangulering + severity)

### ROOT 1 — Tomt data-substrat ⚠️ KRITISK
**Triangulering:** 7 perspektiv (CO#1 ×100, FE#4 ×100, PR#F1 ×75, SC#4 ×100, AR#3 STRONG, AD#2 ×100, AN-exec)

**Hva:** `samples_path.write_text("[]")` (orchestrator line 3483) + "Phase 13 (future)" defer = `detect_anomalies` + `compute_correlations` + `score_recommendations` + `render_patch_bundle` får alltid empty input. Dashboard's hovedfaner (Anomalies, Correlations, Recommendations, Pending Patches) er tomme i 100% av runs. E2E-test (12.1) seeder `recommendations.json` direkte → grønne tester mens prod-pipeline produserer ingenting.

**Fix:** Bytt Phase 13 → Phase 3.5: bygg synthesizer FØR analyst. Gjenbruk `alc-session-metrics-adapter.mjs` fra andre session. Registrer `session-metrics` i `data-contracts.json`.

**Effort:** 2 timer (gjenbruk eksisterende script) eller 4 timer (Python-rewrite).

---

### ROOT 2 — Apply-mekanismen er overpowered, usikret, og buggy ⚠️ KRITISK
**Triangulering:** 8 perspektiv (SE#1-5, AD#4, AD#6, AN#3, AN#5)

**Sub-bugs (alle confidence 100):**

| ID | Bug | Concrete failure |
|---|---|---|
| SE#1 | Null auth | Enhver lokal prosess kan POST `/apply` → mutere `settings.json`, agent yaml, gates |
| SE#2 | Path traversal på `patch_id` | `../../etc/passwd-fake/patches/x` traverser ut av state_dir |
| SE#3 | Ubegrenset `params["file"]` | Strategier kan skrive `~/.ssh/authorized_keys` |
| SE#4 | Secrets i apply-log | `agents/openai.yaml` API-keys base64'es i apply-log.jsonl, vokser ubegrenset |
| AD#4 | Ingen `fcntl.flock` | Double-click → korrupt JSONL → `_load_apply_log` crash → dashboard 500 → utilgjengelig |
| AD#6 | `yaml_field_replace` naiv | Quoting, multiple matches, prefix-match, trailing comments, indentation — 5 dokumenterte breaks |
| AN#3 | Filosofi: ALC skal være tracker, ikke mutator | MCP+dashboard direct-apply hører ikke hjemme her |
| AN#5 | Gates queue-first | Recommender må ALDRI skrive `latest-approved-gates.md` direkte |

**To valg:**

#### Valg A — Behold apply, men hardene (ce-doc-review-anbefaling)
- Per-session secret (random token i URL/header, mintes ved server-start, embeddes i dashboard.html)
- Allowed-roots check: `Path(params["file"]).resolve()` MÅ være under definerte rots
- Path normalization på `patch_id`: assert `p.resolve().parent == (state_dir / "patches").resolve()`
- `scrub_secrets` integration FØR log-write
- `fcntl.flock` på `state_dir/.apply.lock` rundt read→write→log
- Try/except JSONDecodeError i `_load_apply_log` + skip bad lines
- Anchored regex i yaml_field_replace + refuse hvis match_count != 1
- Idempotency check: 409 hvis patch_id allerede applied uten matching revert
- Apply-log compaction policy
- Effort: ~6 timer

#### Valg B — Fjern apply fra MCP+dashboard helt (agent-native-audit-anbefaling)
- Dashboard rendrer kun read-only (recs + diffs + revert-commands), ingen knapper som POST'er
- `alc-recommender` emitter **inert** patch bundles
- Eksplisitt CLI: `python3 bin/alc_apply --patch <id> --write` med preflight checks
- Gates: recommender skriver `operator_proposed_gate` queue rows; operatør promoter via eksisterende gate flows
- Effort: ~3 timer (mindre kode å skrive)

**Min sterke anbefaling:** **Valg B**. Den eliminerer hele ROOT 2-overflaten heller enn å patche den. Agent-native-prinsippet "any action user can take, agent can also take" er ivaretatt fordi en MCP-tool kan invokere CLI'en — dashboardet er ikke seam'en for mutation.

---

### ROOT 3 — Eksisterende `dashboard/` pakke ignoreres ⚠️ KRITISK
**Triangulering:** 1 perspektiv (FE#1 ×100) — men implementeringsblokkerer

**Hva:** Dagens `dashboard/` har:
- `dashboard/__init__.py` — 285+ linjer FastAPI app (`build_app()`, `JobRegistry`, `/api/actions/distill`, `/api/actions/promote`, `/api/actions/mute`)
- `dashboard/actions.py` — 160 linjer promote_gate/mute_domain/actions_summary med atomic writes
- `dashboard/templates/` (4 HTML)
- `dashboard/web/` — React/Vite bundle, package.json, dist/
- Konsumert av `bin/render_dashboard.py` + `bin/serve_dashboard.py`
- **`distill_learning` leser `muted-domains.json`** for å skippe muted domains under classification — LIVE BEHAVIORAL DEPENDENCY

Plan sier kun "MIGRATE: actions.py → alc-dashboard/server.py". Hvis fulgt blindt: `distill_learning` mister sin mute-input.

**Fix:** Plan må EKSPLISITT velge:
- (a) Behold begge dashboards (klart eier-skille)
- (b) Slett React/FastAPI dashboard helt + port `promote_gate`/`mute_domain` til ny stdlib-server
- (c) Behold FastAPI-dashboard som "ops console", ny stdlib-server som "review console", definer klar skille

**Effort:** 1 time discovery + diskusjon, 4-12 timer implementasjon avhengig av valg.

---

### ROOT 4 — `validate_outputs.py` overload bryter eksisterende fixtures ⚠️ KRITISK
**Triangulering:** 1 perspektiv (FE#2 ×100) — men implementeringsblokkerer

**Hva:** Eksisterende `bin/validate_outputs.py` er en **report-content-validator** (markdown-tekst, regex-checks: `PSYCH_RE`, `RAW_HOOK_RE`, `CAUSAL_SKILL_RE`, `REQUIRED_MARKERS`, evidence-bullet shape, agent_compensation domain shape). Positional arg: `validate_outputs <report-path>`.

Plan prøver legge til `--check-contracts --state-dir` mode + imaginær `existing_main` wrapper. Fixtures som vil knuse:
- `fixtures/tests/test_validate_outputs_regex_metachars.py`
- `fixtures/tests/test_validate_outputs_psych_tightening.py`
- `fixtures/tests/test_agent_learning_compounder.py` (linjer 147, 525, 548)
- `fixtures/tests/test_gate_registry.py`

**Fix:** Lag NY script `bin/validate_artifacts.py` heller enn å overload. Eller dispatch-shim som bevarer positional path eksakt.

**Effort:** 1 time (omforming av Phase 3 Task 3.2).

---

### ROOT 5 — `${CLAUDE_PLUGIN_ROOT}` Claude-only → cross-runtime brytes ⚠️ KRITISK
**Triangulering:** 2 perspektiv (FE#3 ×100, AD#8 ×50)

**Hva:** Alle hooks + 4 slash commands hardkoder `${CLAUDE_PLUGIN_ROOT}`. Codex eksponerer ikke denne. `:-.` fallback fungerer kun når cwd = plugin root. Hele Phase 8+9 er Claude-only mens AGENTS.md (Phase 1.3) reklamerer for `/alc-report` osv. Codex AGENTS.md auto-load og `.codex-plugin/` discovery er IKKE verifisert.

**Fix:** Følg G0.5.2-utfallet. Ved minimum: bytt til `${ALC_PLUGIN_ROOT}` (sett selv via wrapper script som detect'er runtime). Eller bruk relative paths fra repo root.

**Effort:** 2 timer (eller drop cross-runtime entirely, 0 timer).

---

### ROOT 6 — "Feedback loop closes" er asserted, ikke implementert ⚠️ KRITISK
**Triangulering:** 2 perspektiv (PR#F6 ×75, AD#11 ×75)

**Hva:** Arkitektur-diagrammene (linje 64-68 + 109-142) lover step 7: "score_recommendations weighs down bad gates, up good ones". Men `score_recommendations.py` (Phase 4.5) leser KUN patterns/anomalies/correlations — aldri `apply-log.jsonl`, aldri `outcomes.json`. Ranker er stateless.

Pluss: scoring er teatersk:
- `confidence = 0.8` konstant for alle anomalies
- `impact = 0.7` konstant for alle model_swaps
- `impact = min(abs(z)/10.0, 1.0)` saturerer ved z=10 → ekte z=3 anomaly får impact=0.3 → score 0.24 → under risk-threshold → aldri vist
- Model_swaps outranker ALLTID anomalies (fixed preference order)

Project name "Compounder" beskriver ikke det koden faktisk gjør.

**Fix:** Valg:
- (a) Implementer outcomes-til-vekt-loopen: `score_recommendations.py` leser `apply-log.jsonl` + `outcomes.json`, multipliserer score med `(1 + n_positive - n_negative) / (1 + total)` per kind. Krever at `report_outcome` (MCP) faktisk skriver `outcomes.json` (også ikke implementert i planen).
- (b) Fjern "feedback loop closes" fra diagrammer + redefiner som "fixed-priority sort med z-score modulation". Mer ærlig men avslører at "compounder" er feilnavn.

**Effort:** Valg a = 4 timer + 2 timer. Valg b = 30 minutter.

---

### ROOT 7 — Over-strukturering (4 sub-skills, 4 generators, 3 personas, 4 commands)
**Triangulering:** 12 perspektiv (AR#1+#2+#6+#7, CO#4, SC#1+#2+#5+#6, FE#7, AD#5, CO#5)

**Tabell over kollapser:**

| Hva planen sier | Hva reviews konvergerer på | Hvor mange reviewere |
|---|---|---|
| 4 sub-skills (alc-core/analyst/recommender/dashboard) | 2 sub-skills (alc-core + alc-dashboard) | 5 |
| 4 `propose_*_patch.py` + `KIND_DISPATCH` auto-import | 1 `generators.py` med dispatch-dict literal | 6 |
| 3 nye personas (alc-analyst, alc-recommender, alc-reviewer) | Behold kun `alc-reviewer` (distinkt pre-apply rolle) | 2 |
| 4 slash commands (/alc-report, /alc-analyze, /alc-recommend, /alc-apply) | Kun `/alc-report` med flags | 2 |

**Sub-bug:** `KIND_DISPATCH` auto-import + `except ImportError: pass` (Phase 5.7 line 2438-2451):
- Typo i propose_X.py → silent miss, kind aldri registrert
- Test bruker manuelle imports → false confidence
- Future generators ship'es uten test-coverage av autoload-path

**Fix:** Adopter alle 4 kollapser. Tap: noen "leverage" som ikke fantes. Vinning: ~10 markdown-filer, ~8 scripts, 0 silent-failure-paths.

**Effort:** -8 timer (mindre å bygge).

---

### ROOT 8 — `copy_to_clipboard` pseudo-strategy + silently broken
**Triangulering:** 2 perspektiv (SC#3 ×100, DE#5 ×100)

**Hva:** 
- Apply-contract sier "snapshot original-bytes, log for revert". For `copy_to_clipboard`: `original = b""`, `original_bytes_b64 = ""`, revert er no-op. Bryter invariant.
- Worse: frontend's `apply()` mottar `clipboard_text` i response men kaller **aldri** `navigator.clipboard.writeText()`. Brukeren klikker Apply på workflow-chain, ser "✓ applied", men teksten kastes stille.

**Fix:** Skill `workflow_chain` ut av patch-pipeline. Render som "copy-paste suggestion"-panel (egen seksjon, ikke patch-bundle).

**Effort:** 30 minutter.

---

### ROOT 9 — Premiss og identitet uvalidert (samme som ROOT 1, men strategisk linse)
**Triangulering:** 5 perspektiv (PR#F1+F2+F3+F4+F7, AD#1, AD#10, AN-exec)

| Sub-issue | Detalj |
|---|---|
| PR#F1 | Premissen "analyst surfaces patterns default distill misses" har null konkret evidens |
| PR#F2 | Dashboard konkurrerer med ALC's eksisterende in-flow nudge surface (latest-approved-gates.md + latest-skill-context.md som lastes ved SessionStart) som faktisk får agentens oppmerksomhet ved handling, ikke "ukentlig" |
| PR#F3 | Identitetsskifte fra "compile evidence → memory" (én verb) til "compile + analyze + tune" (tre verbs) er ikke navngitt eller diskutert |
| PR#F4 | Maintenance surface øker dramatisk (4 sub-skills, sync-script, 2 manifester, hooks i bash som exec python, MCP server, dashboard server, 9 nye scripts) for én solo-bruker |
| PR#F7 | 12 faser alle implisitt P0; ingen MVP-validering-gate; planen committer til ~30 tasks før Tom kan validere at dashboardet brukes |
| AD#10 | Build-vs-use: alternativer aldri vurdert (Streamlit, datasette, plain markdown report + manual edit, MCP-only flow). Dashboard er duplikat av MCP-overflaten med to apply-paths uten guidance på hvilken |
| AN-exec | "ALC should observe, normalize, recommend, and queue. Direct mutation should be an explicit operator workflow." |

**Fix:** Phase 0.5 G0.5.1 spike avgjør. Hvis grønt: navngi identitetsskiftet eksplisitt i goal-statement. Hvis rødt: drop hele dashboard-initiativet, lever kun synthesizer + bedre SessionStart-nudges.

**Effort:** Avhenger 100% av Phase 0.5-utfallet.

---

### ROOT 10 — State fragmentering: ingen canonical `StateHandle`
**Triangulering:** 2 perspektiv (FE#8 ×75, AN#4 hovedkrav)

**Hva:** Orchestrator skriver til `<repo>/.agent-learning/`. MCP's `_state_dir_for_repo` med fallback til `repo_state_dir(repo)` returnerer `<state_root>/repos/<id>` (forskjellig). To pipelines, to state-dirs. Eksisterende `.agent-learning.json` har `latest_approved_gates` og `latest_skill_context` keys, men **ikke** `state_dir`.

Andre session foreslår eksplisitt `StateHandle`:
```
StateHandle:
  repo
  state_root
  repo_state_dir
  reports_dir
  dashboard_dir
  actions_dir
```

**Fix:** 
- `init_learning_system` skriver `state_dir` til `.agent-learning.json`
- Lag `bin/state_handle.py` modul; MCP, dashboard, hooks, distill, recommender, apply importerer fra denne
- Hver overflate leser `.agent-learning.json` først når repo er supplert

**Effort:** 3 timer.

---

### ROOT 11 — `data-contracts.json` drift + validator coverage gap
**Triangulering:** 4 perspektiv (AR#5 WORTH, CO#6 ×75, SC#7 ×75, AD#9 ×75)

**Sub-issues:**
- Hånd-vedlikeholdt JSON-fil → drift når scripts endrer paths
- Validator skipper templated dirs (`{patches, analyst, dashboard}`) med `continue` — orphan-filer INNE i disse oppdages aldri
- Validator kjører kun i tester; ikke i pre-commit, ikke i orchestrator, ikke i SessionEnd-hook
- Mangler entries for `hook-events.jsonl`, `cost-tokens.json`, `session-metrics.json`, `latest-skill-context`, `skill-usage`, `skill-impact`, `action-events`
- Mangler lifecycle-felt (`create`, `read`, `update`, `delete_or_retention`, `owner`, `states`, `max_age`, `max_count`, `cleanup_command`)

**Valg:**
- (a) Behold JSON-registry men: utvid templated-dir-handling med wildcard-pattern, kjør validator i orchestrator + pre-commit, legg til alle missing entries + lifecycle-felter
- (b) Migrer til in-code `@ARTIFACTS.register` decorator (AR#5)
- (c) Drop hele orphan-story hvis den ikke skal håndheves

**Fix:** Valg a + utvidelse er konsistent med AN-#6. Effort: ~4 timer.

---

### ROOT 12 — Dashboard UX-mangler
**Triangulering:** 1 perspektiv (DE alle 6 findings) — men flere er 100 confidence

| Sub | Detalj | Confidence |
|---|---|---|
| DE#1 | Tab-ordering separerer Recommendations fra Patches (kan ikke se rec + diff samtidig) | 75 |
| DE#2 | Manglende error/loading/success-states; ingen styling forskjell ✗ vs ✓ | 100 |
| DE#3 | User flow gap: ingen outcome-rapportering UI; revert-command skjult i `<details>` | 75 |
| DE#4 | Ingen viewport meta, ingen ARIA, gray button #6e7681 contrast 3.4:1 < WCAG AA 4.5:1 | 100 |
| DE#5 | Deferred + rejected patches akkumulerer uten filter; copy_to_clipboard silently broken | 100 |
| DE#6 | GitHub dark theme verbatim (#0d1117, #161b22, #1f6feb, #238636) → AI-slop-risiko; bryter Tom's "distinct aesthetic"-bar | 75 |

**Fix:** Hvis ROOT 2 Valg B (drop apply) velges: store deler av dette forsvinner. Det som gjenstår:
- Empty-state designs for alle 7 tabs (ROOT 1 fikses, så empty states kun for ekte zero-data)
- Distinkt visuell encoding (score som luminance, time-axis, cost-delta sparklines) for å unngå AI-slop
- Accessibility minimum: viewport meta, ARIA på tabs, contrast-fix på gray button

**Effort:** 4 timer for distinkt aesthetic + accessibility. Hvis ROOT 2 Valg B: 1 time totalt.

---

### ROOT 13 — Cross-process / runtime concerns
**Triangulering:** flere små unike + sammenfallende

| Sub | Bug |
|---|---|
| AD#7 / FE#5 | Port 8765 hardkodet 3 steder, ingen `allow_reuse_address`, TIME_WAIT-race, subprocess.PIPE deadlock-risk |
| AD#7 | `file://` Apply POST blokkeres cross-origin → "✗ Failed to fetch" UX |
| FE#6 | Alpine.js CDN dep bryter "stdlib only"-løftet; offline use fail'er |
| FE#9 | `git mv SKILL.md` mid-refactor (worktree handler det, men plan bør si eksplisitt at worktree ≠ live skill før Phase 12.3 merge) |
| CO#5 | SKILL.md vs skill-name inkonsistens (alc-analyst sin SKILL.md skriver det er invocable standalone, men commands kaller scripts direkte) |
| CO#7 | "Phase 13" label-ambiguitet (det er ingen Phase 13 i planen) |

**Fix:** 
- Pick free port via socket; `HTTPServer.allow_reuse_address = True`; `subprocess.DEVNULL`
- Drop static-file-dashboard-path; orchestrator starter alltid server, åpner `http://`
- Vendor Alpine.js inn i static/ (~50KB minified) eller drop Alpine til vanilla JS DOM
- Plan: legg til note om worktree-isolation i Phase 0
- Erstatt "Phase 13" → "Future phase (out of scope)"
- Hvis ROOT 7 adopteres: SKILL.md-konflikt forsvinner

**Effort:** 2 timer samlet.

---

### ROOT 14 — Context-injection safety mangler test-gates
**Triangulering:** 1 perspektiv (AN#6) men dette er sentral ALC-operating-rule

**Hva:** Andre session sier: "Context injection is unsafe unless raw prompt, transcript, absolute path, and original-byte flows are blocked by tests." Plan utvider ALC's load/write-overflater (gates → recs → patches → diffs → apply-logs) uten å bevare nåværende boundary-guarantees.

**Fix:** Legg til `tests/test_context_boundary.py` som asserer:
- Ingen `latest-approved-gates.md` linje > 200 chars
- Ingen absolute host path i loadable surfaces
- Ingen base64 blob > 1KB
- Ingen pattern som ligner secret (regex: `sk-`, `bearer `, `aws_`, osv.)
- Ingen raw transcript chunk i exports

Run ved hver SessionEnd via hook.

**Effort:** 2 timer.

---

### ROOT 15 — Capability discovery / agent-native parity
**Triangulering:** 1 perspektiv (AN-sub-7 score 4/7) — sentral agent-native-prinsipp

**Hva:** Plan adder skills, commands, manifester, dashboard-affordances. Det er ingen capability-map som binder user-actions til agent-callable tools. Brutto: brukeren kan klikke `[Apply]`, men hvilken MCP-tool gjør samme? `apply_patch` er navngitt men det er én av N user-actions.

**Fix:** Legg til `references/capability-map.md` (matrise: user-action → command → MCP tool → script-CLI). Test som asserer parity: hver dashboard-knapp HAR motsvarende MCP-tool og CLI-kommando.

**Effort:** 2 timer.

---

### ROOT 16 — Hermes-DSL salvage for apply-operasjoner og validator-pattern ⭐ NY
**Triangulering:** 1 perspektiv (E — workflow-engines salvage review) men solver flere existing roots samtidig

**Bakgrunn:** Tom har Hermes installert lokalt (`~/.hermes/`), med `skills/software-development/hermes-agent-skill-authoring/SKILL.md` som dokumenterer Hermes's `skill_manage`-mønster. Hermes har allerede prøvd og levert det ALC's apply-mekanisme prøver å være — kompakt DSL med action-types, validator, atomic write, subdir-allowlist, og size-limits.

**Hermes's skill_manage pattern (relevante deler):**

| Hermes-konsept | ALC-equivalent (planen i dag) | Konkret pattern |
|---|---|---|
| `skill_manage(action='create')` | (planen har ingen create) | Lager ny skill under `<root>/<category>/<name>/SKILL.md` med validator-check |
| `skill_manage(action='patch', old_string, new_string)` | `propose_skill_routing` + `markdown_append` | Lokalisert tekst-erstatning, ikke regex |
| `skill_manage(action='edit')` | Ingen direkte | Full content rewrite med validator-check |
| `skill_manage(action='write_file')` | `propose_agent_patch` (json_key_insert) | Atomic write til subdir-allowlist |
| `_validate_frontmatter()` | data-contracts.json post-hoc | Pre-write enforcement av frontmatter shape |
| Subdir allowlist (`references/`, `templates/`, `scripts/`, `assets/`) | `params["file"]` unrestricted (ROOT 2 SE#3) | Klart constraints på hva som kan skrives |
| Session-scoped loader-cache | (ikke håndtert) | "Den nye skill'en er ikke synlig før neste session" — eksplisitt dokumentert |
| Description ≤ 1024 chars, file ≤ 100k chars | (ikke håndtert) | Size limits enforced ved write |

**Hva dette løser i revidert plan:**

1. **ROOT 2 (apply-mekanismen):** Erstatt de 4 ad-hoc `_APPLY_STRATEGIES` (`json_key_insert`, `markdown_append`, `yaml_field_replace`, `copy_to_clipboard`) med Hermes-DSL operasjoner. Recommender emitter:
   ```json
   {
     "skill_manage_op": {
       "action": "patch",
       "target": "skills/alc-core/SKILL.md",
       "old_string": "...",
       "new_string": "..."
     },
     "preflight": {
       "allowed_roots": ["~/.agents/skills/", "~/.claude/skills/"],
       "expected_target_sha256": "abc...",
       "max_target_size": 100000
     },
     "revert_op": {
       "action": "patch",
       "old_string": "...",
       "new_string": "..."
     }
   }
   ```
   `bin/alc_apply` (ROOT 2 Valg B) blir en thin executor av denne DSL'en. Hele AD#6 (yaml_field_replace's 5 dokumenterte breaks) blir N/A fordi Hermes-DSL bruker `old_string`/`new_string` med eksakt match — multi-match → fail, ambiguity → fail, comments preserved.

2. **ROOT 8 (copy_to_clipboard pseudo-strategy):** Operasjonen er korrekt IKKE uttrykbar i Hermes-DSL. Den hører ikke hjemme i apply-pipeline — render som separat "suggestion"-panel.

3. **ROOT 11 (data-contracts drift):** Hermes-mønsteret enforcer ved write, ikke ved post-hoc validator-scan. ALC kan kopiere `_validate_frontmatter`-stilen: alle writes går gjennom `bin/artifact_writer.py` som validerer mot et registry i samme prosess. Hånd-vedlikeholdt JSON forsvinner — koden ER registret.

4. **ROOT 13 (SKILL.md naming, hooks): Hermes session-loader-cache** — eksplisitt dokumentert at "current session ser ikke ny skill". ALC bør dokumentere samme.

5. **ROOT 7 (over-strukturering):** Hermes har EN tool (`skill_manage`) med action-parameter, ikke fire separate `propose_*` filer. Modell for `generators.py`-kollapsen.

**Hva som IKKE skal trekkes inn (eksplisitt avvist):**

- Hele Hermes-runtime'en (massiv dependency, ikke greit for ALC som CC-plugin)
- Hermes's `delegate_task` / `todo` / MCP-config — overlapper med Claude Code's egne
- Hermes's category-tree (`autonomous-ai-agents`, `software-development`, osv.) — ALC har sin egen flate struktur
- Hermes's `hermes skills install <hub-url>` hub-modell — ALC distribueres som single plugin

#### ROOT 16b — Agent-creator-kvalitet på samme DSL (skills OG agents via samme executor)

Den samme `bin/alc_apply`-executoren skal kunne skrive **agenter** med agent-creator-quality-bar fra plugin-dev's `agent-creator.md`. Dette er en natural extension av DSL'en — bare en ny `target_type`.

**Plugin-dev's agent-creator quality bar (lifted verbatim):**

| Felt | Krav |
|---|---|
| `name` | lowercase + hyphens, 3-50 chars, 2-4 ord, ikke "helper"/"assistant" |
| `description` | Starter med "Use this agent when...", inneholder 2-4 `<example>` blokker med Context/user/assistant/commentary-struktur |
| System prompt body | 500-3000 ord, struktur: Role → Responsibilities (numbered) → Process (step-by-step) → Quality standards → Output format → Edge cases |
| `model` | `inherit` (default) eller `sonnet`/`haiku` for spesifikke valg |
| `color` | Semantisk: blue/cyan=analysis-review, green=generation-creation, yellow=validation-caution, red=security-critical, magenta=transformation-creative |
| `tools` | Minimal least-privilege list, eller omit for full access |

**Utvidet DSL — `target_type`-parameter:**

```json
{
  "skill_manage_op": {
    "action": "create" | "patch" | "edit" | "write_file",
    "target_type": "skill" | "agent" | "command" | "hook",
    "target": "agents/alc-eval-grader.md",
    "old_string": "...",       // for patch
    "new_string": "...",       // for patch
    "content": "..."           // for create/edit/write_file (full file body)
  },
  "preflight": {
    "allowed_roots": [...],    // varierer per target_type
    "expected_target_sha256": "...",
    "max_target_size": ...     // skills 100k, agents 30k, hooks 10k
  },
  "revert_op": { ... }
}
```

**Dispatch-table for executor:**

```python
DSL_TARGETS = {
    "skill": {
        "validator": validate_skill_frontmatter,
        "allowed_roots": ["skills/", "~/.hermes/skills/"],
        "max_size": 100_000,
        "required_fields": ["name", "description"],
        "name_pattern": r"^[a-z][a-z0-9-]{0,63}$",
    },
    "agent": {
        "validator": validate_agent_frontmatter,   # ⬅ matcher agent-creator
        "allowed_roots": [
            "agents/",                              # in-plugin (committed)
            "<state>/alc-agents/dev/",              # ⬅ ALC dev-arkiv
            "<state>/alc-agents/test/",             # ⬅ ALC test-arkiv
            "<state>/alc-agents/evals/",            # ⬅ ALC eval-arkiv
            "<personal>/alc-agents/",               # cross-repo personal arkiv
        ],
        "max_size": 30_000,
        "required_fields": ["name", "description"],
        "description_must_start_with": "Use this agent when",
        "min_examples": 2,
        "max_examples": 4,
        "body_word_count": (500, 3000),
        "allowed_colors": ["blue", "cyan", "green", "yellow", "red", "magenta"],
        "allowed_models": ["inherit", "sonnet", "haiku", "opus"],
    },
    "command": {
        "validator": validate_command_frontmatter,
        "allowed_roots": ["commands/"],
        "max_size": 10_000,
    },
    "hook": {
        "validator": validate_hook_executable,
        "allowed_roots": ["hooks/"],
        "max_size": 10_000,
    },
}
```

**Agent-validator (matcher agent-creator's standards):**

```python
def validate_agent_frontmatter(content: str) -> list[str]:
    errors = []
    fm = parse_frontmatter(content)
    if not fm.get("name"): errors.append("name required")
    if not re.match(r"^[a-z][a-z0-9-]{2,49}$", fm.get("name", "")):
        errors.append("name: 3-50 chars, lowercase + hyphens, must start with letter")
    if any(w in fm.get("name", "") for w in ("helper", "assistant", "agent-")):
        errors.append("avoid generic 'helper'/'assistant' or 'agent-' prefix")
    desc = fm.get("description", "")
    if not desc.startswith("Use this agent when"):
        errors.append("description must start with 'Use this agent when'")
    n_examples = desc.count("<example>")
    if not (2 <= n_examples <= 4):
        errors.append(f"description needs 2-4 <example> blocks, found {n_examples}")
    body = content.split("---", 2)[-1].strip()
    word_count = len(body.split())
    if not (500 <= word_count <= 3000):
        errors.append(f"system prompt: 500-3000 words, found {word_count}")
    for required_section in ("Role", "Responsibilities", "Process", "Output"):
        if required_section not in body and required_section.lower() not in body.lower():
            errors.append(f"system prompt missing section: {required_section}")
    if fm.get("color") and fm["color"] not in {"blue", "cyan", "green", "yellow", "red", "magenta"}:
        errors.append(f"color must be semantic: blue/cyan=analysis, green=create, yellow=validate, red=security, magenta=transform")
    if fm.get("model") and fm["model"] not in {"inherit", "sonnet", "haiku", "opus"}:
        errors.append(f"model: 'inherit' or sonnet/haiku/opus")
    return errors
```

#### ROOT 16c — Agent-arkiv: hvor ALC-genererte agenter bor

Tre arkiv-roots, hver med eget formål:

```
<state>/alc-agents/                  (per-repo, ikke committed)
├── dev/                             ← spike-experimenter, midlertidige varianter
│   └── analyst-zscore-vs-iqr.md    (ALC genererer for å sammenligne approaches)
├── test/                            ← agenter brukt i tester
│   └── eval-grader-noisy.md
└── evals/                           ← agenter som grader output av andre agenter
    └── rec-quality-judge.md         (gir verdict på alc-recommender output)

<personal>/alc-agents/               (cross-repo, ~/.local/share/agent-learning/alc-agents/)
├── tom-style-reviewer.md            (din personlige stil, bruk på alle repos)
└── ...

<plugin-root>/agents/                (committed, distribueres med pluginen)
├── alc-reviewer.md                  ← Phase 7's eneste committed persona
└── (drop alc-analyst, alc-recommender per ROOT 7)
```

**Hvordan ALC invokerer arkiv-agentene:**

| Use case | Hvordan |
|---|---|
| **Dev:** spike to varianter | Recommender genererer 2 agent-varianter via DSL, lagrer i `dev/`. CLI: `bin/alc_invoke --agent dev/analyst-zscore-vs-iqr --task <samples-corpus>`. Output sammenlignes manuelt eller via eval-grader. |
| **Test:** integrasjons-tester | `tests/test_recommender_e2e.py` lagrer en kjent agent i `test/`, kjører den med syntetisk input, asserer output-shape. Cleanup etter test. |
| **Evals:** grader rec-kvalitet | Periodisk eval-loop spawn'er `evals/rec-quality-judge` mot siste 20 recommendations, samler verdict (`approve`/`reject`/`modify`), føder tilbake til `score_recommendations.py` som outcomes (ROOT 6 fix). |

**Hvordan agentene faktisk invokeres:**

```python
# bin/alc_invoke
def invoke(agent_path: Path, task_prompt: str) -> dict:
    """Spawn arkiv-agent via Claude Code Task tool, return structured result."""
    agent_md = agent_path.read_text()
    # parser frontmatter for model/tools
    fm = parse_frontmatter(agent_md)
    system_prompt = agent_md.split("---", 2)[-1].strip()
    # invoker via Claude Code Agent tool (eller via MCP til en runtime som har Agent tool)
    return claude_code_agent_dispatch(
        subagent_type="claude",   # generisk fallback
        system_prompt=system_prompt,
        prompt=task_prompt,
        model=fm.get("model", "inherit"),
        tools=fm.get("tools"),
    )
```

For Codex / andre runtimes: tilsvarende wrapper som bruker runtime'ens subagent-primitiv.

**Hvorfor arkiv heller enn å committe til `agents/`:**

- **Eksperimenter:** dev-varianter er midlertidige, vil støye opp git-historikk
- **Per-repo state:** test-agenter er repo-spesifikke (forskjellig corpus, forskjellig domain)
- **Personlig stil:** `<personal>/alc-agents/` følger DEG på tvers av maskiner uten å forurense pluginen
- **Cleanup:** ALC kan periodisk slette `dev/`-agenter eldre enn N dager (lifecycle-felt fra ROOT 11)

**Eval-loop som lukker ROOT 6 (compounder-loopen):**

```
recommender produserer 20 patches
   │
   ▼
evals/rec-quality-judge (arkiv-agent) grader hver
   │
   ▼
verdicts → outcomes.json
   │
   ▼
score_recommendations.py leser outcomes.json
   │
   ▼
NESTE recommender-pass vekter ned recs som likner avviste, opp recs som likner approved
   │
   ▼
ekte compounding — projektnavnet stemmer endelig med koden
```

Dette er det første konkrete byggesteinet som faktisk lever opp til "compounder"-navnet. Krever ingen ny LLM-integrasjon — bruker bare Claude Code's eksisterende Agent-dispatch.

**Konkret integrasjon i revidert plan:**

- **Phase 5 (recommender):** `generators.py` emitter Hermes-DSL ops med `target_type: skill | agent | command | hook`. Skill-ops fra dag én; agent-ops legges til når recommender oppdager mønster "den samme analyst-spørringen kjøres N ganger" → forslag: "lag en dedikert agent for dette".
- **Phase 6.5 (alc_apply CLI):** dispatch-table over target_type, hvert med egen validator + allowed_roots + size limits
- **NY Phase 6.6:** `bin/alc_invoke` for å spawn arkiv-agenter. Wrapper rundt Claude Code Agent-dispatch.
- **NY Phase 6.7:** Eval-loop scaffold — `bin/alc_eval` som kjører `evals/rec-quality-judge` mot recommendations, skriver outcomes.json, lukker ROOT 6.
- **Phase 12:** validator-tests for hver target_type (skill, agent, command, hook). Test at agent-validator avviser invalid examples-count, manglende sections, generic names.
- **Data contracts:** legg til `alc-agents/dev/*.md`, `alc-agents/test/*.md`, `alc-agents/evals/*.md`, `<personal>/alc-agents/*.md`, `outcomes.json` med lifecycle-felt.

**Effort:** -2 timer (DSL er kompaktere) + 2 timer (agent-validator + agent-arkiv) + 2 timer (alc_invoke + eval-scaffold) = +2 timer netto. Men: ROOT 6 (compounder-loop) blir faktisk implementert, ikke bare lovet i diagrammer.

**Filstier for referanse:**
- `/home/tth/.hermes/skills/software-development/hermes-agent-skill-authoring/SKILL.md` (skill-DSL og validator-mønster)
- `/home/tth/.claude/plugins/cache/claude-plugins-official/plugin-dev/unknown/agents/agent-creator.md` (agent quality bar)

---

## 4. Cross-reference matrix

Hver finding fra hver review-input → root issue.

| Finding | Source | Confidence | Root |
|---|---|---|---|
| AR#1 Collapse 4 sub-skills | A | STRONG | ROOT 7 |
| AR#2 Collapse generators | A | STRONG | ROOT 7 |
| AR#3 Synthesizer NOW | A | STRONG | ROOT 1 |
| AR#4 Extract apply_engine | A | STRONG | ROOT 2 (interagerer) |
| AR#5 In-code registry | A | WORTH | ROOT 11 |
| AR#6 Drop personas | A | WORTH | ROOT 7 |
| AR#7 /alc-report only | A | WORTH | ROOT 7 |
| AR#8 Pre-commit sync | A | SPEC | ROOT 13 |
| AR#9 Drop bash wrappers | A | SPEC | ROOT 13 |
| CO#1 Synthesizer deferred contradiction | B | 100 | ROOT 1 |
| CO#2 Generator sys.path coupling | B | 100 | ROOT 2, ROOT 7 |
| CO#3 apply_engine not integrated | B | 75 | ROOT 2 |
| CO#4 4 vs 2 sub-skills | B | 75 | ROOT 7 |
| CO#5 SKILL.md naming inconsistency | B | 75 | ROOT 7, ROOT 13 |
| CO#6 data-contracts missing entries | B | 75 | ROOT 11 |
| CO#7 Phase 13 label | B | 50 | ROOT 13 |
| FE#1 Existing dashboard/ destructive | B | 100 | **ROOT 3** (unik blokker) |
| FE#2 validate_outputs.py conflict | B | 100 | **ROOT 4** (unik blokker) |
| FE#3 `${CLAUDE_PLUGIN_ROOT}` Claude-only | B | 100 | ROOT 5 |
| FE#4 Synthesizer makes Phases 4-6 demoware | B | 100 | ROOT 1 |
| FE#5 Port collisions | B | 75 | ROOT 13 |
| FE#6 Alpine.js CDN dep | B | 75 | ROOT 13 |
| FE#7 Auto-import silent failure | B | 100 | ROOT 7 |
| FE#8 .agent-learning.json pointer mismatch | B | 75 | ROOT 10 |
| FE#9 git mv breaks discovery | B | 75 | ROOT 13 |
| PR#F1 Premise: missing data not missing analysis | B | 75 | ROOT 1, ROOT 9 |
| PR#F2 Dashboard vs existing nudges | B | 75 | ROOT 9 |
| PR#F3 Identity shift unnamed | B | 75 | ROOT 9 |
| PR#F4 Adoption friction | B | 75 | ROOT 9 |
| PR#F5 Opportunity cost | B | 50 | ROOT 9 |
| PR#F6 Feedback loop not in code | B | 75 | ROOT 6 |
| PR#F7 No MVP gate | B | 75 | ROOT 9 |
| DE#1 IA tab ordering | B | 75 | ROOT 12 |
| DE#2 Missing states | B | 100 | ROOT 12 |
| DE#3 User flow gaps | B | 75 | ROOT 12, ROOT 6 |
| DE#4 No accessibility | B | 100 | ROOT 12 |
| DE#5 Deferred patches accumulate + clipboard broken | B | 100 | ROOT 8, ROOT 12 |
| DE#6 AI-slop GitHub theme | B | 75 | ROOT 12 |
| SE#1 No auth | B | 100 | ROOT 2 |
| SE#2 Path traversal | B | 100 | ROOT 2 |
| SE#3 Arbitrary file write | B | 100 | ROOT 2 |
| SE#4 Secret leak in apply-log | B | 75 | ROOT 2, ROOT 14 |
| SE#5 Cross-origin POST | B | 50 | ROOT 2, ROOT 13 |
| SC#1 4 sub-skills don't match goal | B | 100 | ROOT 7 |
| SC#2 KIND_DISPATCH unjustified | B | 100 | ROOT 7 |
| SC#3 copy_to_clipboard pseudo-strategy | B | 100 | ROOT 8 |
| SC#4 Empty samples.json hardcoded | B | 100 | ROOT 1 |
| SC#5 Pass-through personas | B | 100 | ROOT 7 |
| SC#6 3 of 4 commands redundant | B | 75 | ROOT 7 |
| SC#7 Hand-maintained registry | B | 75 | ROOT 11 |
| SC#8 MCP sys.path hack | B | 50 | ROOT 2 |
| AD#1 Premise asserted never demonstrated | D | 75 | ROOT 9, ROOT 1 |
| AD#2 samples.json empty by construction | D | 100 | ROOT 1 |
| AD#3 hook-events schema unverified | D | 75 | ROOT 1, Phase 0.5 G0.5.3 |
| AD#4 No cross-process locking | D | 100 | ROOT 2 |
| AD#5 Silent ImportError | D | 100 | ROOT 7 |
| AD#6 yaml_field_replace naive | D | 100 | ROOT 2 |
| AD#7 Port hardcoded + file:// | D | 75 | ROOT 13, ROOT 2 |
| AD#8 Codex AGENTS.md unverified | D | 50 | ROOT 5, Phase 0.5 G0.5.2 |
| AD#9 Validator coverage gap | D | 75 | ROOT 11 |
| AD#10 No alternatives considered | D | 50 | ROOT 9 |
| AD#11 Score theatrical | D | 75 | ROOT 6 |
| AN#1 session-metrics.json first-class | C | hovedkrav | ROOT 1 |
| AN#2 Claude insights as read-only adapter | C | hovedkrav | ROOT 1 |
| AN#3 Remove direct apply | C | hovedkrav | ROOT 2 (Valg B) |
| AN#4 Canonical StateHandle | C | hovedkrav | ROOT 10 |
| AN#5 Gates queue-first | C | hovedkrav | ROOT 2 (Valg B) |
| AN#6 Context-boundary tests | C | hovedkrav | ROOT 14 |
| AN-sub-1 Action Parity 6/15 | C | 49% | ROOT 15 |
| AN-sub-2 Tools-as-primitives 16/29 | C | 49% | ROOT 2 |
| AN-sub-3 Context Injection 4/10 | C | 49% | ROOT 14 |
| AN-sub-4 Shared Workspace 4/10 | C | 49% | ROOT 10 |
| AN-sub-5 CRUD Completeness 24/36 | C | 49% | ROOT 11 |
| AN-sub-6 UI Integration 4/10 | C | 49% | ROOT 12 |
| AN-sub-7 Capability Discovery 4/7 | C | 49% | ROOT 15 |
| AN-sub-8 Prompt-Native Features 5/10 | C | 49% | (ny: scripts skal være pure transforms, prompts gjør judgment) |
| E#1 Hermes skill_manage DSL pattern | E | salvage | ROOT 16, og solver ROOT 2 / 8 / 11 partielt |
| E#2 Hermes pre-write `_validate_frontmatter` enforcement | E | salvage | ROOT 16, ROOT 11 |
| E#3 Hermes subdir allowlist (references/templates/scripts/assets) | E | salvage | ROOT 16, ROOT 2 SE#3 |
| E#4 Hermes session-loader-cache dokumentert som "expected" | E | salvage | ROOT 16, ROOT 13 |
| E#5 Hermes hub-installer + delegate_task — IKKE relevant | E | reject | (avvist eksplisitt) |

**Triangulering count per root (kun rooter med 3+ triangulerende reviewere):**

| Root | Reviewere | Verdict |
|---|---|---|
| ROOT 1 (empty data substrate) | 7 | UAVVISELIG |
| ROOT 2 (apply over-empowered) | 8 + 1 salvage | UAVVISELIG |
| ROOT 7 (over-structuring) | 12 | UAVVISELIG |
| ROOT 9 (premise unvalidated) | 5 | STERKT |
| ROOT 11 (registry drift) | 4 + 1 salvage | STERKT |
| ROOT 13 (runtime concerns) | 5 + 1 salvage | STERKT |
| ROOT 6 (feedback loop) | 2 | KLAR (men crit) |
| ROOT 10 (state fragmentation) | 2 | KLAR |
| ROOT 12 (dashboard UX) | 1 (6 sub) | KLAR |
| ROOT 16 (Hermes-DSL salvage) | 1 (review E) | KLAR — solver flere existing roots |

---

## 5. Revidert plan-shape (konkret)

Basert på alle 5 review-inputs, hvis Phase 0.5 grønner alle 3 gates:

### Reviderte faser

```
PHASE 0    Worktree + baseline (uendret)
PHASE 0.5  Validate (3 gates — se §2)
PHASE 1    Plugin shell (cross-runtime hvis G0.5.2 grønn, ellers Claude-only)
PHASE 2    Refactor til skills/alc-core/ (eksisterende SKILL.md flyttes)
PHASE 2.5  ★ NY: Bygg session-metrics-synthesizer (gjenbruk eller port alc-session-metrics-adapter.mjs)
PHASE 3    data-contracts.json med lifecycle-felter + utvid validator (NY navn: bin/validate_artifacts.py).
           ★ ROOT 16: pre-write enforcement etter Hermes _validate_frontmatter-mønster
           hvis time tillater — ellers behold JSON-fil + ad-hoc validator.
PHASE 3.5  ★ NY: StateHandle modul (bin/state_handle.py) + .agent-learning.json {state_dir} write
PHASE 4    alc-analyst som bin/analyst_* scripts (IKKE sub-skill); 4 scripts som før
PHASE 5    alc-recommender som bin/recommender_* scripts (IKKE sub-skill); 1 generators.py med
           dispatch-dict (IKKE 4 propose_*).
           ★ ROOT 16: generators.py emitter Hermes-DSL-formaterte ops (action/target/old_string/
           new_string/preflight/revert_op) i stedet for ad-hoc dict. Inert patch bundles only.
PHASE 6    alc-dashboard som sub-skill — READ-ONLY (ingen [Apply]-knapper, kun [Defer]/[Reject]
           som ikke muterer filer); render-paths gjennom server, ingen file://
PHASE 6.5  ★ NY: bin/alc_apply CLI som parser Hermes-DSL ops + utfører med preflight checks
           (allowed-roots, hash-match, fcntl.flock, scrub_secrets, idempotency-check).
           ★ ROOT 16: subdir-allowlist-pattern fra Hermes (references/templates/scripts/assets).
           ★ ROOT 16b: dispatch-table over target_type (skill/agent/command/hook), hver med
           egen validator. Agent-validator håndhever agent-creator-quality (name, description
           starter med "Use this agent when", 2-4 <example>-blokker, 500-3000 ord body,
           Role/Responsibilities/Process/Output struktur, semantisk color, allowed model).
PHASE 6.6  ★ NY ROOT 16c: bin/alc_invoke for å spawn arkiv-agenter via Claude Code Agent
           tool. Wrapper som parser frontmatter for model/tools, dispatcher subagent.
PHASE 6.7  ★ NY ROOT 16c: bin/alc_eval scaffolding — kjører evals/rec-quality-judge mot
           recommendations, skriver outcomes.json. LUKKER ROOT 6 (compounder-loopen).
PHASE 7    1 ny persona: alc-reviewer (drop analyst+recommender personas)
PHASE 8    1 slash command: /alc-report med [--analyst-only] [--apply <id>] flags
           (drop /alc-analyze, /alc-recommend, /alc-apply)
PHASE 9    Hooks (post-distill refresh + SessionStart load) — bruk python-fil direkte, ikke bash heredoc.
           ★ ROOT 16: dokumenter at session-loader er cached ("ny skill synlig først neste session")
           — samme mønster Hermes har eksplisitt.
PHASE 10   MCP extensions: get_recommendations, list_pending_patches, propose_apply
           (KØER bin/alc_apply call med Hermes-DSL op, ikke utfører direkte).
           Drop apply_patch som direkte mutator. get_dashboard_url OK.
PHASE 11   Codex sync hvis G0.5.2 grønt — ellers drop
PHASE 12   Context-boundary tests + capability-map.md + e2e smoke (med ekte data, ikke seedet).
           ★ ROOT 16: validator-tests matcher Hermes's _validate_frontmatter shape
           (name, description ≤1024, body non-empty, total ≤100k).
```

### Endringer i tall

| Aspekt | Original plan | Revidert |
|---|---|---|
| Sub-skills | 4 | 2 |
| SKILL.md filer | 4 + 1 (alc-core) = 5 | 2 |
| Nye scripts | 9 | ~12 (analyst×4 + generators×1 + alc_apply×1 + state_handle×1 + synthesizer×1 + ev. python-hook×1) |
| Generator-filer | 4 + orchestrator | 1 (generators.py med dict, emitter Hermes-DSL ops) |
| Apply-strategier (planen) | 4 ad-hoc (`json_key_insert`, `markdown_append`, `yaml_field_replace`, `copy_to_clipboard`) | 1 Hermes-DSL action-vocabulary (`patch`/`edit`/`write_file`/`create`) + copy_to_clipboard ut av apply-pipeline |
| Personas | 3 | 1 (alc-reviewer) |
| Slash commands | 4 | 1 |
| MCP nye tools | 4 | 3 (drop direct apply_patch) |
| Faser totalt | 12 | 16 (med 0.5, 2.5, 3.5, 6.5, 6.6, 6.7) |
| Estimert effort | 15-20 timer | 13-18 timer (+2 timer for agent-arkiv + alc_invoke + eval-loop som lukker ROOT 6) |
| Apply target_types | 4 ad-hoc strategier | 4 DSL target_types (skill/agent/command/hook) gjennom ett executor |
| Agent-arkiv | Ingen | 3 roots: `<state>/alc-agents/{dev,test,evals}/` + `<personal>/alc-agents/` |
| Compounder-loop (ROOT 6) | Lovet i diagram, ikke implementert | Lukket: `evals/rec-quality-judge` → outcomes.json → score_recommendations leser outcomes |
| Apply-knapp i dashboard | Ja | Nei (kun read + CLI suggest) |
| Risiko-overflate | Stor (auth, paths, concurrency, secrets) | Liten (alt går gjennom CLI med preflight + DSL-validator) |
| yaml_field_replace's 5 dokumenterte breaks (AD#6) | Til stede | N/A (Hermes-DSL bruker eksakt match med multi-match-fail) |

### Kjerne-design endring

```
FØR (planen)
────────────
session data → distill → analyst → recommender → dashboard
                                                     │
                                                     ▼ [Apply] (POST)
                                              server muter fil
                                                     │
                                                     ▼
                                              apply-log + revert

ETTER (post-review, med ROOT 16 Hermes-DSL salvage)
───────────────────────────────────────────────────
session data → distill → analyst → recommender → INERT HERMES-DSL OPS
                                                     │
                                                     │  { action: patch|edit|write_file,
                                                     │    target: ...,
                                                     │    old_string: ..., new_string: ...,
                                                     │    preflight: { allowed_roots, hash, max_size },
                                                     │    revert_op: { swapped strings } }
                                                     ▼ (dashboard render-only)
                                              user reviewer + velger patch
                                                     │
                                                     ▼ (terminal)
                                              bin/alc_apply --patch <id> --write
                                                     │
                                                     ▼ Hermes-DSL executor:
                                                       - parse op
                                                       - allowed-roots check
                                                       - hash-match verify
                                                       - fcntl.flock state_dir/.apply.lock
                                                       - scrub_secrets på original-bytes
                                                       - exact-match patch (multi-match → fail)
                                                       - atomic write
                                                       - append apply-log (med revert_op)
                                                     │
                                                     ▼
                                              apply-log + alc_apply --revert <id>
                                              (executor kjører revert_op samme vei)
                                                     │
                                                     ▼
                                              MCP report_outcome → outcomes.json
                                                     │
                                                     ▼
                                              score_recommendations leser outcomes
                                              → ekte compounding (ROOT 6 fix)
```

---

## 6. Effort-rebalansering

| Tidligere antagelse | Nytt estimat |
|---|---|
| Original plan (uendret) | 15-20 timer ferdigstilt med tomme dashboards og kjente bugs |
| **Phase 0.5 (1 dag, blokkerer alt videre)** | **6 timer** |
| Implementer revidert plan (hvis 0.5 grønn) | 12-18 timer |
| Drop Phase 4-12, bygg kun synthesizer + bedre SessionStart (hvis 0.5 rødt) | 4 timer |

**Total worst case:** 6 (gate) + 4 (drop most) = 10 timer  
**Total best case:** 6 (gate) + 12 (revidert plan) = 18 timer  
**Total original plan as-is:** 15-20 timer + N timer for å fikse bugs post-implementasjon

---

## 7. Out of scope / eksplisitt deferred (basert på alle reviews)

Etter konsolidering, ekte deferred items:
1. **Auth + multi-user dashboard** — bare valid hvis ROOT 2 Valg A (behold apply); ellers ikke relevant
2. **Cursor / OpenCode / Gemini cross-runtime** — Codex + Claude først, og kun hvis G0.5.2 grønn
3. **Auto-trigger ce-* chains fra recs** — eksplisitt avvist tidligere i denne session
4. **Pre-commit hook for sync-to-codex-plugin** — AR#8, SPECULATIVE, kun hvis manifest endres ofte
5. **Live-reload av dashboard via WebSocket** — refresh-on-hook er nok for MVP
6. **outcome-based skill-routing** — ROOT 6 Valg b (drop framing) hvis Valg a er for stort

---

## 8. Anbefaling i én setning

**Implementer ikke planen som-er.** Kjør Phase 0.5 (3 gates, ~6 timer). Hvis grønt, implementer revidert plan over ~11-16 timer med: 2 sub-skills (ikke 4), inerte Hermes-DSL patches + CLI apply (ikke MCP/dashboard mutator), synthesizer bygget først (ikke deferred til Phase 13), StateHandle modul, kun `alc-reviewer` persona, kun `/alc-report` command, og context-boundary tests før noen durable write. Hvis Phase 0.5 rødt på premiss-validering, drop Phase 4-12 og lever kun synthesizer + bedre SessionStart-nudges som single-phase work.

**Hermes-DSL salvage (ROOT 16)** kommer naturlig inn på 3 steder uten å trekke inn Hermes-runtime: Phase 5 (generators.py emitter `skill_manage`-formaterte ops), Phase 6.5 (`bin/alc_apply` parser + utfører med preflight), og Phase 12 (validator-tests matcher `_validate_frontmatter`-shape). Tap: ingenting. Vinning: yaml_field_replace-bugs forsvinner, copy_to_clipboard ut av apply-pipeline, ett kompakt DSL i stedet for fire ad-hoc strategier, og kompatibel med Hermes hvis du senere vil hand-execute samme op der.

---

## Appendix A — Files referenced

- Plan: `docs/plans/2026-05-25-alc-plugin-refactor.md`
- Architecture review (HTML): `/tmp/architecture-review-1779721590.html`
- Agent-native-audit export: `/home/tth/alc-agent-native-audit-export-2026-05-25T17-16-05/`
  - `reports/00-executive-summary.md` (decision summary)
  - `reports/01-agent-native-audit.md` (scored by principle)
  - `reports/02-plan-change-brief.md` (6 hovedkrav)
  - `reports/03-script-review.md` (claude-insights-extracted.mjs)
  - `reports/04-subagent-findings.md` (consolidated subagent outputs)
  - `scripts/alc-session-metrics-adapter.mjs` (★ klar til bruk for ROOT 1 fix)
  - `scripts/claude-insights-extracted.mjs` (read-only adapter)
- Eksisterende ALC: `/home/tth/.agents/skills/agent-learning-compounder/`
  - `dashboard/` (FastAPI + React/Vite, må håndteres i ROOT 3)
  - `bin/validate_outputs.py` (overload-konflikt, ROOT 4)
  - `bin/state_paths.py` (eksisterende, basis for StateHandle ROOT 10)
  - `alc_mcp/server.py` (eksisterende MCP, 5 tools)
  - `bin/init_learning_system.py` (skriver `.agent-learning.json`, må utvides med `state_dir`)
- Hermes (ROOT 16 salvage-kilde): `/home/tth/.hermes/`
  - `skills/software-development/hermes-agent-skill-authoring/SKILL.md` (DSL og validator-mønster)
  - `skills/autonomous-ai-agents/hermes-agent/SKILL.md` (orchestration-mønster, NOT salvaged)
  - Hermes-runtime'en er installert lokalt, men IKKE en dependency for ALC — vi løfter kun patterns.

## Appendix B — Hvilke konkrete kodelinjer trenger oppmerksomhet

| File | Lines | Issue | Root |
|---|---|---|---|
| Plan | 5 | Goal-statement "specialist analyst" — reframe etter G0.5.1 | ROOT 9 |
| Plan | 64-68 | "Feedback loop closes" lover noe ikke implementert | ROOT 6 |
| Plan | 219 | "MIGRATE: actions.py → alc-dashboard/server.py" undervurderer eksisterende dashboard/ | ROOT 3 |
| Plan | 754-873 | data-contracts.json mangler entries + lifecycle-felter | ROOT 11 |
| Plan | 1486 (detect_anomalies) | `--min-n 5` på `[]` returnerer alltid empty | ROOT 1 |
| Plan | 2438-2451 | `except ImportError: pass` autoload | ROOT 7 |
| Plan | 3082-3085 | `_append_jsonl` uten flock | ROOT 2 |
| Plan | 3088-3092 | `_load_patch` uten path normalization | ROOT 2 |
| Plan | 3099 | `_load_apply_log` crash on malformed line | ROOT 2 |
| Plan | 3114-3148 | `params["file"]` unrestricted | ROOT 2 |
| Plan | 3134 | `yaml_field_replace` naive text replace | ROOT 2 |
| Plan | 3151-3154 | `copy_to_clipboard` pseudo-strategy | ROOT 8 |
| Plan | 3177-3185 | `original_bytes_b64` uten scrub | ROOT 2 |
| Plan | 3285-3305 | `do_POST` no auth | ROOT 2 |
| Plan | 3328 | `HTTPServer` ikke `ThreadingHTTPServer`, ikke `allow_reuse_address` | ROOT 13 |
| Plan | 3446-3447, 4034-4042 | State-dir resolution mismatch orchestrator vs MCP | ROOT 10 |
| Plan | 3483-3484 | `samples_path.write_text("[]")` | ROOT 1 |
| Plan | 3743 og rundt | `${CLAUDE_PLUGIN_ROOT}` Claude-only | ROOT 5 |
| Plan | 4077-4079 | MCP sys.path hack | ROOT 2 |
| Plan | 4317 | "Phase 13 (future)" — synthesizer deferred | ROOT 1 |
| Plan | 4219 | E2E test seeder recommendations.json direkte (skjuler empty pipeline) | ROOT 1 |

---

## Appendix C — `workflow-engines` salvage review

**Repo:** `https://github.com/onecomai/workflow-engines`  
**Status:** privat, default branch `main`, sist pushet `2026-04-09T03:11:33Z`  
**Shallow inspect path:** `/tmp/workflow-engines-inspect`

### Konklusjon

`workflow-engines` har fortsatt verdi, men **ikke** som kjørbar Claude
subscription/headless-runtime. Den skal behandles som:

1. pipeline-katalog
2. agent-prompt-bibliotek
3. phased execution-design
4. issue extraction / `.review/issues.md` design
5. orientation-cache og cost/scope heuristikk

Den skal **ikke** gjenbrukes direkte som runtime i ALC.

### Hva repoet faktisk inneholder

Inspect viste:

- `.claude-plugin/plugin.json`
- `commands/` med 29 Claude slash commands
- `pipelines/` med 26 Python pipeline scripts
- `agent-prompts/` med 56 prompt-filer
- `engine/` med felles orchestration, phase runner, issue extraction,
  worktree support og report writer
- `tests/` med omfattende unittest-dekning

`README.md` beskriver repoet som "Multi-agent pipeline orchestration for Claude
Code" og krever `claude` CLI installed/authenticated. `docs/ARCHITECTURE.md`
bekrefter hard coupling til `claude -p`.

### Runtime-binding som nå er lav verdi

`engine/core.py` spawner direkte:

```text
claude -p --output-format json --model ... --max-budget-usd ...
```

Den bruker også:

- `--permission-mode bypassPermissions`
- `--disable-slash-commands`
- `--no-session-persistence`
- Claude tool allowlist via `--tools`
- Claude-specific cost output: `total_cost_usd`, `num_turns`, `duration_ms`

Dette var verdifullt da Claude headless kunne kjøres mot subscription. Nå er det
en API-cost/runtime-binding, ikke en billig worker substrate.

### Deler som bør høstes inn i ALC

#### 1. Pipeline catalog

Importer pipeline-navn og beskrivelser som ALC job families:

- `review-codebase`
- `deep-audit`
- `pre-merge-gate`
- `tech-debt-scan`
- `dependency-audit`
- `api-contract-audit`
- `arch-review`
- `api-surface-audit`
- `api-coverage`
- `perf-audit`
- `query-optimize`
- `migrate-framework`
- `pipeline-optimize`
- `docker-audit`
- `infra-review`
- `doc-gen`
- `changelog-gen`
- `onboard-guide`
- `fix-issues`
- `fix-issues-team`
- `skill-eval`

Output: `workflow-catalog.json`.

#### 2. Agent prompts

`agent-prompts/*.md` bør migreres til:

- `alc-analyst` personas
- `alc-reviewer` pre-apply persona
- optional Codex skills
- ALC recommender prompt templates

Viktig: promptene skal være data/templates, ikke instructions som auto-loades
ukritisk.

#### 3. Phased execution model

Behold konseptet:

```text
phase 1: orientation / scan
phase 2: targeted analysis
phase 3: synthesis
phase N: report / issue extraction
```

Behold også:

- `depends_on`
- context truncation
- orientation cache
- per-phase agent sets
- per-agent timeout/budget metadata

Men bytt runner fra Claude-subprocess til adapter pattern:

```text
runner:
  kind: codex | claude-api | github-agentic-workflows | dry-run
```

#### 4. Issue extraction

`review_codebase.py` har nyttige mønstre:

- inline `<issues>` extraction
- severity/category sorting
- fingerprint dedupe
- `.review/issues.md`
- persistent triage

Dette passer godt inn i ALC som:

```text
finding -> structured issue -> triage -> fix loop -> report_outcome
```

#### 5. Orientation cache

`~/.cache/workflow-engines/orientation`-ideen bør flyttes til repo-local ALC
state og kobles til:

- git SHA
- scope
- pipeline id
- relevant `latest-skill-context.md`
- session-metrics

### Deler som ikke bør importeres

Ikke importer:

- `claude -p` subprocess runner som default
- `--permission-mode bypassPermissions`
- Claude plugin-only slash command format som eneste entrypoint
- API budget semantics som om de representerer subscription usage
- `.claude/settings.local.json` eller Claude runtime state

### Anbefalt høstingsfase

Legg inn etter Phase 0.5, før ny ALC analyst/recommender implementasjon:

```text
Phase 0.6: Harvest workflow-engines

Inputs:
- workflow-engines/commands/*.md
- workflow-engines/pipelines/*.py
- workflow-engines/agent-prompts/*.md

Outputs:
- {repo_state}/workflow-catalog.json
- {repo_state}/prompt-catalog.json
- docs/reference/workflow-engines-salvage.md

Rules:
- no Claude subprocess execution
- no .claude runtime writes
- prompts treated as data
- runner adapter is explicit and defaults to dry-run
```

### Minimal useful artifact shape

```json
{
  "id": "review-codebase",
  "description": "Profile-based code review with issue extraction",
  "phases": [
    {"phase": 1, "agents": ["orientation", "git_hygiene"]},
    {"phase": 2, "agents": ["architecture", "security"]},
    {"phase": 3, "agents": ["quality", "testing", "performance", "ops"]}
  ],
  "prompts": [
    "review_codebase_orientation.md",
    "review_codebase_architecture.md"
  ],
  "recommended_runner": "codex",
  "requires_write": false
}
```

### Impact on current ALC refactor decision

This strengthens, not weakens, the recommendation to **avoid building a new
direct-mutation dashboard first**. `workflow-engines` shows the durable value is
in:

- reusable job families
- prompt libraries
- structured issue extraction
- phased orchestration
- cache/scope/cost metadata

Those all feed naturally into ALC's tracker/recommender role. They do not
require resurrecting Claude subscription headless execution.

---

**Generert:** 2026-05-25 av konsolidering av 5 separate review-pass.
