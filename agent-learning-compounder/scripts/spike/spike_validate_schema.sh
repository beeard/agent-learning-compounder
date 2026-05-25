#!/usr/bin/env bash
# G0.5.3 — Data-schema discovery + path validation (Phase A, ~1h).
#
# Finds existing hook-events.jsonl (the v3 telemetry stream U5.5 will
# upgrade to v4). Confirms the v3→v4 migration has a real corpus to target,
# and that the {id, cost, tokens, duration_s} contract U5 synthesizer
# depends on is recoverable from available data sources.

set -euo pipefail

echo "── schema spike (G0.5.3) ──────────────────────"
echo ""

# ---- hook-events.jsonl location + schema ----
echo "── search 1/2: locate hook-events.jsonl files ──"
HOOK_FILES=$(find "$HOME" -maxdepth 7 -type f -name "hook-events.jsonl" 2>/dev/null | head -20 || true)

if [ -z "$HOOK_FILES" ]; then
  echo "✗ NO hook-events.jsonl found under \$HOME (depth ≤ 7)"
  echo ""
  echo "Common locations to check by hand:"
  for p in \
    "$HOME/.agent-learning" \
    "$HOME/.local/state/agent-learning" \
    "$HOME/work/active/*/.agent-learning"; do
    echo "  • $p"
  done
  echo ""
  echo "(verdict: RED — no live telemetry corpus; v4 migration testable only on synthetic fixtures)"
else
  COUNT=$(echo "$HOOK_FILES" | wc -l | tr -d ' ')
  echo "✓ $COUNT hook-events.jsonl file(s) found:"
  echo "$HOOK_FILES" | sed 's/^/  /'
  echo ""

  NEWEST=$(echo "$HOOK_FILES" | xargs -I{} stat -c "%Y {}" {} 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2- || echo "$HOOK_FILES" | head -1)
  echo "── newest: $NEWEST ──"
  echo "  size: $(stat -c %s "$NEWEST" 2>/dev/null || stat -f %z "$NEWEST") bytes"
  echo "  lines: $(wc -l < "$NEWEST" | tr -d ' ')"
  echo ""

  echo "── sample (line 1) ──"
  head -1 "$NEWEST" | python3 -m json.tool 2>/dev/null || head -1 "$NEWEST"
  echo ""

  echo "── schema scan: keys + types across first 200 rows ──"
  python3 - <<PY
import json, os, sys
path = "$NEWEST"
seen = {}
n = 0
with open(path) as f:
    for line in f:
        if n >= 200: break
        try:
            r = json.loads(line)
        except Exception:
            continue
        for k, v in r.items():
            t = type(v).__name__
            seen.setdefault(k, set()).add(t)
        n += 1
print(f"  rows scanned: {n}")
print(f"  unique top-level fields: {len(seen)}")
for k in sorted(seen):
    types = "|".join(sorted(seen[k]))
    print(f"    {k:24s} : {types}")

# Look for schema_version explicitly
import json as j
versions = set()
with open(path) as f:
    for i, line in enumerate(f):
        if i >= 500: break
        try:
            r = j.loads(line)
            v = r.get("schema_version") or r.get("schemaVersion") or r.get("version")
            if v is not None:
                versions.add(v)
        except: pass
if versions:
    print()
    print(f"  schema_version values observed: {sorted(versions)}")
else:
    print()
    print("  (no schema_version field on first 500 rows — v3 likely implicit)")
PY
fi
echo ""

# ---- session-report cost-tokens path ----
echo "── search 2/2: locate {id, cost, tokens, duration_s} source ──"
for p in \
  "$HOME/.claude/usage-data/session-meta" \
  "$HOME/.claude/usage-data/facets" \
  "$HOME/.claude/usage-data" \
  "$HOME/.claude/projects"; do
  if [ -d "$p" ]; then
    N=$(find "$p" -maxdepth 2 -type f 2>/dev/null | wc -l | tr -d ' ')
    echo "  ✓ $p ($N files)"
  else
    echo "  ✗ $p (absent)"
  fi
done
echo ""

echo "Note: Claude transcripts (~/.claude/projects/*.jsonl) carry token counts in"
echo "  message metadata but NOT cost_usd directly — cost is downstream computation."
echo "  This is YELLOW for the 'cost' field: derivable but not stored. The premise"
echo "  spike (G0.5.1) will produce real samples.json — check whether 'cost' is"
echo "  populated there. If null/missing, U5 synthesizer needs to compute USD from"
echo "  model + tokens via a pricing table (existing pattern in bin/collect_hook_event)."
echo ""

echo "── GRADING ───────────────────────────────────"
echo ""
echo "Record in scripts/spike/RESULTS.md under '## G0.5.3 — Data-schema':"
echo "  [ ] hook-events.jsonl found + schema captured:        GREEN / RED"
echo "  [ ] schema_version v3→v4 migration target identified: GREEN / RED"
echo "  [ ] {id, tokens, duration_s} recoverable:             GREEN / RED"
echo "  [ ] {cost_usd} recoverable (raw or computed):         GREEN / YELLOW / RED"
echo ""
echo "Verdict semantics:"
echo "  fully GREEN  →  U5.5 + U5 implementations have a real corpus to target"
echo "  YELLOW on cost  →  acceptable; U5 derives cost from tokens × model pricing"
echo "  RED on hook-events  →  v4 schema work proceeds on synthetic fixtures only"
