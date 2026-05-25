#!/usr/bin/env bash
# G0.5.1 — Premise validation driver (Phase A, ~4h manual grading).
#
# Question: does a specialist analyst, run against the operator's real
# ~/.claude/projects corpus, surface ≥3 non-obvious AND actionable
# recommendations in the top-10? V1 plan failed to validate this; if RED
# the rewrite collapses to "ship synthesizer + nudges only".
#
# This script does the mechanical work — produces samples.json from real
# corpus via the audit-export adapters, then runs an inline minimal
# anomaly probe and prints the top-10 in a grading-friendly format.
#
# PASS/FAIL is the operator's call. Record in scripts/spike/RESULTS.md.

set -euo pipefail

ADAPTER_DIR="${ADAPTER_DIR:-/home/tth/alc-agent-native-audit-export-2026-05-25T17-16-05/scripts}"
CORPUS_DIR="${CORPUS_DIR:-$HOME/.claude/projects}"
export OUTDIR="${OUTDIR:-$(mktemp -d -t alc-spike-premise.XXXXXX)}"

# ---- preflight ----
[ -d "$ADAPTER_DIR" ] || { echo "✗ adapter dir not found: $ADAPTER_DIR" >&2; exit 1; }
[ -f "$ADAPTER_DIR/claude-insights-extracted.mjs" ] || { echo "✗ claude-insights-extracted.mjs missing in $ADAPTER_DIR" >&2; exit 1; }
[ -f "$ADAPTER_DIR/alc-session-metrics-adapter.mjs" ] || { echo "✗ alc-session-metrics-adapter.mjs missing in $ADAPTER_DIR" >&2; exit 1; }
[ -d "$CORPUS_DIR" ] || { echo "✗ corpus dir not found: $CORPUS_DIR" >&2; exit 1; }
command -v node >/dev/null || { echo "✗ node not on PATH" >&2; exit 1; }
command -v python3 >/dev/null || { echo "✗ python3 not on PATH" >&2; exit 1; }

TRANSCRIPT_COUNT=$(find "$CORPUS_DIR" -maxdepth 2 -type f -name '*.jsonl' 2>/dev/null | wc -l | tr -d ' ')

echo "── premise spike (G0.5.1) ─────────────────────"
echo "adapter:    $ADAPTER_DIR"
echo "corpus:     $CORPUS_DIR ($TRANSCRIPT_COUNT *.jsonl transcripts)"
echo "outdir:     $OUTDIR"
echo ""

# ---- step 1: claude-insights extraction ----
echo "── step 1/3: extract claude-insights from real corpus ──"
node "$ADAPTER_DIR/claude-insights-extracted.mjs" --json > "$OUTDIR/claude-insights.json"
SESSIONS=$(python3 -c "
import json
d = json.load(open('$OUTDIR/claude-insights.json'))
s = d.get('sessions', d if isinstance(d, list) else [])
print(len(s))
")
echo "✓ $SESSIONS sessions extracted → $OUTDIR/claude-insights.json"
echo ""

# ---- step 2: normalize to session-metrics (samples.json shape) ----
echo "── step 2/3: normalize to session-metrics shape ──"
node "$ADAPTER_DIR/alc-session-metrics-adapter.mjs" \
  --claude-insights-json "$OUTDIR/claude-insights.json" \
  --output "$OUTDIR/samples.json"
SAMPLE_COUNT=$(python3 -c "
import json
d = json.load(open('$OUTDIR/samples.json'))
s = d.get('sessions', d if isinstance(d, list) else [])
print(len(s))
")
echo "✓ $SAMPLE_COUNT samples written → $OUTDIR/samples.json"
echo ""

# ---- step 3: inline minimal anomaly probe ----
echo "── step 3/3: anomaly probe (z-score on duration grouped by primary_tool) ──"
python3 - <<'PY'
import json, os, statistics
from collections import defaultdict

samples_path = os.path.join(os.environ["OUTDIR"], "samples.json")
with open(samples_path) as f:
    raw = json.load(f)

samples = raw["sessions"] if isinstance(raw, dict) and "sessions" in raw else raw

def bucket_for(s):
    tc = s.get("tool_counts") or {}
    if tc:
        return max(tc.items(), key=lambda kv: kv[1])[0]
    return s.get("skill") or s.get("primary_tool") or "(none)"

def duration_s(s):
    if "duration_s" in s and isinstance(s["duration_s"], (int, float)):
        return float(s["duration_s"])
    if "duration_minutes" in s and isinstance(s["duration_minutes"], (int, float)):
        return float(s["duration_minutes"]) * 60
    return None

by_bucket = defaultdict(list)
for s in samples:
    d = duration_s(s)
    if d is None:
        continue
    by_bucket[bucket_for(s)].append((s, d))

print(f"Buckets with ≥1 sample: {len(by_bucket)}")
print(f"Total samples with duration: {sum(len(r) for r in by_bucket.values())}")
print()
print("Top buckets by sample count:")
for b, rows in sorted(by_bucket.items(), key=lambda kv: -len(kv[1]))[:8]:
    durs = [d for _, d in rows]
    print(f"  {b:24s} n={len(rows):4d}  median={statistics.median(durs):7.1f}s  max={max(durs):7.1f}s")
print()

# Anomaly probe: z-score within bucket, min n=3
anomalies = []
for b, rows in by_bucket.items():
    if len(rows) < 3:
        continue
    durs = [d for _, d in rows]
    mean = statistics.mean(durs)
    sd = statistics.stdev(durs) if len(durs) > 1 else 0
    if sd == 0:
        continue
    for sample, dur in rows:
        z = (dur - mean) / sd
        if abs(z) >= 2:
            anomalies.append({
                "bucket": b,
                "duration_s": dur,
                "bucket_mean_s": mean,
                "z": z,
                "session_id": sample.get("session_id") or sample.get("id") or "?",
                "errors": sample.get("tool_errors", 0),
                "tokens": (sample.get("input_tokens") or 0) + (sample.get("output_tokens") or 0),
            })

anomalies.sort(key=lambda a: -abs(a["z"]))

print(f"── top-10 duration anomalies (|z| ≥ 2, bucket n ≥ 3) ──")
print(f"Total flagged: {len(anomalies)}")
print()
for i, a in enumerate(anomalies[:10], 1):
    sid = (a["session_id"] or "?")[:16]
    print(f"{i:2d}. bucket={a['bucket']:18s} dur={a['duration_s']:7.1f}s "
          f"(μ={a['bucket_mean_s']:7.1f}s) z={a['z']:+5.2f} "
          f"err={a['errors']:3d} tok={a['tokens']:7d} ses={sid}")
PY

echo ""
echo "── GRADING (manual) ──────────────────────────"
echo ""
echo "For each of the top-10 anomalies above, ask:"
echo "  (a) Non-obvious?  Would distill_learning (current pipeline) miss this?"
echo "  (b) Actionable?   Could you write a concrete recommendation from it?"
echo ""
echo "Tally how many pass BOTH (a) and (b):  ___ / 10"
echo ""
echo "Threshold:"
echo "  ≥ 3  →  G0.5.1 GREEN  (premise validated; proceed to Phase B)"
echo "  < 3  →  G0.5.1 RED    (scope collapse: drop Phase D-F; ship U3+U4+U5 only)"
echo ""
echo "Record decision in agent-learning-compounder/scripts/spike/RESULTS.md"
echo "under '## G0.5.1 — Premise validation'."
echo ""
echo "Artifacts retained at: $OUTDIR"
