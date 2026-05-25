#!/bin/sh
# Drive the ALC plugin v2 LFG plan execution via `codex exec`.
#
# Extracts the "Prompt to paste" block from the LFG invocation markdown,
# runs preflight checks, dispatches the orchestrator codex session with
# the lean flag set (--ignore-user-config + medium reasoning), and tees
# the full transcript to a timestamped log under logs/.
#
# The orchestrator is resumable: re-running this script after W1 stops
# for operator (W2 gates) will continue from the last completed wave —
# codex exec reads merged commits on alc-plugin-v2 and skips them.
#
# Usage:
#   ./scripts/run-lfg.sh                    # full run (orchestrator drives)
#   ./scripts/run-lfg.sh --dry-run          # preflight + extraction only, no codex call
#   ./scripts/run-lfg.sh --reasoning low    # cheaper orchestrator (default: medium)
#
# Requirements: codex CLI 0.130+, git, awk, sed.

set -eu

# ---- args ----
DRY_RUN=0
REASONING="medium"
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --reasoning) REASONING="$2"; shift 2 ;;
    --reasoning=*) REASONING="${1#*=}"; shift ;;
    -h|--help)
      sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

# ---- paths ----
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_root=$(CDPATH= cd -- "$script_dir/.." && pwd)
cd "$repo_root"

PROMPT_MD="docs/plans/2026-05-25-001-LFG-INVOCATION-PROMPT.md"
PROMPT_OUT="/tmp/lfg-prompt-$(date +%Y%m%dT%H%M%S).txt"
LOG_DIR="logs"
LOG_FILE="$LOG_DIR/lfg-$(date +%Y%m%dT%H%M%S).log"

# ---- preflight ----
say() { printf '%s\n' "$*"; }
fail() { printf '✗ %s\n' "$*" >&2; exit 1; }

say "── preflight ─────────────────────────────────"

# codex CLI present
command -v codex >/dev/null 2>&1 || fail "codex CLI not on PATH"
say "✓ codex $(codex --version 2>&1 | head -1)"

# on the right branch
branch=$(git branch --show-current 2>/dev/null || echo "")
[ "$branch" = "alc-plugin-v2" ] || fail "expected branch alc-plugin-v2, got: $branch"
say "✓ branch: $branch"

# working tree clean for in-scope files (rough check — any uncommitted changes block)
if ! git diff --quiet || ! git diff --cached --quiet; then
  fail "uncommitted changes present — commit or stash before LFG run (orchestrator expects clean start)"
fi
say "✓ working tree clean"

# prompt markdown exists
[ -f "$PROMPT_MD" ] || fail "LFG prompt markdown missing: $PROMPT_MD"
say "✓ prompt source: $PROMPT_MD"

# extract the "Prompt to paste" block (between first ``` and next ``` after the H2 header)
awk '/^## Prompt to paste/,/^---$/' "$PROMPT_MD" \
  | sed -n '/^```$/,/^```$/p' \
  | sed '1d;$d' \
  > "$PROMPT_OUT"

prompt_lines=$(wc -l < "$PROMPT_OUT" | tr -d ' ')
[ "$prompt_lines" -gt 20 ] || fail "extracted prompt looks empty/truncated ($prompt_lines lines) — check '## Prompt to paste' block delimiters in $PROMPT_MD"
say "✓ extracted prompt: $PROMPT_OUT ($prompt_lines lines)"

# verify first line is the expected start ("Execute the implementation plan...")
first_line=$(head -1 "$PROMPT_OUT")
case "$first_line" in
  "Execute the implementation plan"*) ;;
  *) fail "extracted prompt does not start with 'Execute the implementation plan' — got: $first_line" ;;
esac
say "✓ prompt starts with 'Execute the implementation plan...'"

# hermes reference patterns
[ -d "$HOME/.hermes" ] || say "⚠ ~/.hermes not found — S1 reference patterns dep may break U-units that reference Hermes"

# audit export from prior session
audit_export="$HOME/alc-agent-native-audit-export-2026-05-25T17-16-05/scripts/alc-session-metrics-adapter.mjs"
[ -f "$audit_export" ] || say "⚠ audit export missing: $audit_export (U5 synthesizer Path-A wraps this — Path-B fallback exists)"

# optional venv (needed by U10 dashboard + U17 MCP in Phase D; Phase A/B don't need it)
if [ -d ".venv" ]; then
  say "✓ .venv present (optional deps available for Phase D)"
else
  say "⚠ .venv not found — install with: python3 -m venv .venv && .venv/bin/pip install -r agent-learning-compounder/requirements-optional.txt"
fi

say ""
say "── dispatch ──────────────────────────────────"
say "model:              gpt-5.3-codex-spark"
say "reasoning effort:   $REASONING"
say "sandbox:            workspace-write"
say "user config:        ignored (~12K tokens of prelude bloat stripped)"
say "log:                $LOG_FILE"

if [ "$DRY_RUN" -eq 1 ]; then
  say ""
  say "── dry-run mode: preflight + extraction OK, skipping codex exec ──"
  say "to actually run: $0 (without --dry-run)"
  exit 0
fi

say ""
say "── handing off to codex exec ─────────────────"
say "orchestrator will run W1, then stop for operator-driven W2 (3 validation gates)."
say "interrupt with Ctrl-C to pause; re-run this script to resume from last merged wave."
say ""

mkdir -p "$LOG_DIR"

# shellcheck disable=SC2086
codex exec \
  -m gpt-5.3-codex-spark \
  -s workspace-write \
  --ignore-user-config \
  -c "model_reasoning_effort=\"$REASONING\"" \
  - < "$PROMPT_OUT" 2>&1 | tee "$LOG_FILE"

exit_code=$?
say ""
say "── codex exec exited ($exit_code) — log: $LOG_FILE ──"
exit $exit_code
