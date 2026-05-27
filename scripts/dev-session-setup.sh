#!/usr/bin/env bash
# Dev-session setup for working ON agent-learning-compounder.
#
# What this does:
#   1. Re-runs install_runtime_hooks --apply so the collect_hook_event
#      adapter AND PR 5's warm-loop both wire into .claude/settings.local.json
#      on Stop.
#   2. Merges the plugin's other Stop hooks (refresh_dashboard.py,
#      render_state_surface --format session-report) into the same file.
#      These live in agent-learning-compounder/hooks/hooks.json and are
#      supposed to merge automatically via the plugin loader — but plugin-
#      level hooks aren't reliably merging into the active session config,
#      so we copy them in by hand.
#   3. Wires auto_distill_session with repo-local dev output roots under
#      .runtime/ so dogfood runs do not write to ~/.agent-learning.
#   4. Refreshes events.sqlite from hook-events.jsonl via the warm-loop
#      orchestrator so the read surfaces have current data on first session.
#   5. Verifies the merged settings.local.json by counting hook entries
#      per event, and reports what's wired vs missing.
#
# Idempotent — safe to re-run. Detects already-present hooks and skips them.
#
# To start a Claude session with this setup:
#   cd <this-repo>
#   claude
#
# Claude Code auto-discovers .claude/settings.local.json from the working
# directory. No --config flag needed; the discovery IS the flag.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

SETTINGS=".claude/settings.local.json"
PLUGIN_HOOKS="agent-learning-compounder/hooks/hooks.json"
PYTHON="${PYTHON:-/usr/bin/python3}"

mode="apply"
if [ "${1:-}" = "--verify" ] || [ "${1:-}" = "-v" ]; then
  mode="verify"
fi
if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  cat <<'USAGE'
dev-session-setup.sh — one-command setup for ALC dev sessions

Usage:
  scripts/dev-session-setup.sh          # apply setup (default)
  scripts/dev-session-setup.sh --verify # just verify, no changes
  scripts/dev-session-setup.sh --help

After running, `claude` from the repo root picks up everything.
USAGE
  exit 0
fi

echo "==> repo: $REPO_ROOT"
echo "==> mode: $mode"

if [ "$mode" = "apply" ]; then
  echo
  echo "[1/4] install_runtime_hooks --apply (collect_hook_event + warm-loop on Stop)"
  "$PYTHON" agent-learning-compounder/bin/install_runtime_hooks \
    --repo "$REPO_ROOT" --runtime claude --apply >/dev/null

  echo
  echo "[2/4] merging repo-local Stop hooks into $SETTINGS"
  "$PYTHON" scripts/merge_dev_hooks.py --repo "$REPO_ROOT"

  echo
  echo "[3/4] warming events.sqlite from hook-events.jsonl"
  "$PYTHON" agent-learning-compounder/bin/alc_bootstrap_pipeline --repo "$REPO_ROOT" --quiet || true
fi

echo
echo "[4/4] verifying $SETTINGS"
"$PYTHON" scripts/merge_dev_hooks.py --repo "$REPO_ROOT" --verify

echo
cat <<EOF
==> done.

To start a Claude session with the full ALC stack:

  cd $REPO_ROOT
  claude

Claude auto-discovers .claude/settings.local.json — no flag needed.
Re-run this script after pulling, or after any change to the plugin hooks.
EOF
