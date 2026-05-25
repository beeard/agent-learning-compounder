#!/usr/bin/env bash
# U18 — Codex plugin sync (NO-OP scaffold per W2 Phase A verdict).
#
# Phase A's G0.5.2 cross-runtime gate returned YELLOW (AGENTS.md-only):
# Codex's .codex-plugin/ discovery convention is unverified, so U3 ships
# AGENTS.md content only — no .codex-plugin/plugin.json manifest exists.
#
# This script is the placeholder for the future sync flow. When the Codex
# convention is verified (manifest discovery confirmed in a real Codex
# session), reactivate by:
#   1. Adding .codex-plugin/plugin.json to U3's scope (or a follow-up unit)
#   2. Implementing manifest parity logic here (mirror name/version/description
#      from .claude-plugin/plugin.json, regenerate AGENTS.md from CLAUDE.md)
#   3. Removing the no-op exit below
#
# Reference: agent-learning-compounder/scripts/spike/RESULTS.md "## G0.5.2"

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CODEX_MANIFEST="$ROOT/.codex-plugin/plugin.json"

if [ -f "$CODEX_MANIFEST" ]; then
  echo "✗ unexpected: .codex-plugin/plugin.json exists but U18 sync logic is not implemented yet." >&2
  echo "  This means either: (a) someone added the manifest without enabling the sync script," >&2
  echo "  or (b) the W2 verdict has been updated and U18 needs to be activated." >&2
  exit 2
fi

echo "✓ codex sync no-op: .codex-plugin/ absent (G0.5.2=YELLOW per W2). Nothing to sync."
exit 0
