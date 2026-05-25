#!/usr/bin/env bash
# G0.5.2 — Cross-runtime assumption check (Phase A, ~1h).
#
# V1 plan silently assumed Claude's ${CLAUDE_PLUGIN_ROOT}, Codex's
# .codex-plugin/ discovery, and Codex AGENTS.md auto-load all "just work".
# Three sub-checks confirm or refute, driving U3's conditional Codex scope.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

echo "── runtime spike (G0.5.2) ─────────────────────"
echo "repo:  $REPO_ROOT"
echo ""

# ---- check 1: CLAUDE_PLUGIN_ROOT availability ----
echo "── check 1/3: \${CLAUDE_PLUGIN_ROOT} in active Claude env ──"
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
  echo "✓ EXPORTED — CLAUDE_PLUGIN_ROOT=$CLAUDE_PLUGIN_ROOT"
  echo "  (verdict: GREEN)"
else
  echo "⚠ NOT exported in this shell"
  REFS=$(grep -rIl "CLAUDE_PLUGIN_ROOT" "$HOME/.claude" 2>/dev/null | head -5 || true)
  if [ -n "$REFS" ]; then
    echo "  but referenced in:"
    echo "$REFS" | sed 's/^/    /'
    echo "  (verdict: INDIRECT — confirm with a hook test run from within Claude Code itself,"
    echo "   not this orchestrator shell)"
  else
    echo "  and no references in ~/.claude (verdict: UNKNOWN — needs hook test)"
  fi
fi
echo ""

# ---- check 2: codex .codex-plugin/ discovery ----
echo "── check 2/3: codex .codex-plugin/ plugin convention ──"
if command -v codex >/dev/null; then
  echo "  codex: $(codex --version 2>&1 | head -1)"
  CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
  if [ -d "$CODEX_HOME" ]; then
    echo "  ~/.codex exists"
    if [ -d "$CODEX_HOME/plugins" ]; then
      INSTALLED=$(ls "$CODEX_HOME/plugins" 2>/dev/null | head -10)
      if [ -n "$INSTALLED" ]; then
        echo "  installed plugins:"
        echo "$INSTALLED" | sed 's/^/    /'
        DOTDIR_HITS=$(find "$CODEX_HOME/plugins" -maxdepth 3 -type d -name ".codex-plugin" 2>/dev/null | head -3)
        if [ -n "$DOTDIR_HITS" ]; then
          echo "  ✓ .codex-plugin/ dirs spotted:"
          echo "$DOTDIR_HITS" | sed 's/^/    /'
          echo "  (verdict: GREEN — convention in use)"
        else
          echo "  ⚠ no .codex-plugin/ dir found in installed plugins"
          echo "  (verdict: YELLOW — convention unverified; may need AGENTS.md-only path)"
        fi
      else
        echo "  ⚠ ~/.codex/plugins/ is empty"
        echo "  (verdict: UNKNOWN — no installed plugin to learn from)"
      fi
    else
      echo "  ✗ ~/.codex/plugins/ not present"
      echo "  (verdict: UNKNOWN — check codex docs for current plugin layout)"
    fi
  else
    echo "  ✗ ~/.codex absent — codex never run; cannot infer convention"
  fi
else
  echo "  ✗ codex CLI not on PATH"
fi
echo ""

# ---- check 3: AGENTS.md auto-load ----
echo "── check 3/3: AGENTS.md auto-load in codex ──"
echo "  Codex docs claim AGENTS.md at repo root is auto-loaded as system instructions."
echo "  This check just prints quick signals; the authoritative test is a manual"
echo "  smoke from a repo containing AGENTS.md:"
echo ""
echo "    cd /tmp && mkdir agents-md-smoke && cd agents-md-smoke && git init -q"
echo "    echo '# Test marker token: zorblax-7741' > AGENTS.md"
echo "    codex exec -m gpt-5.3-codex-spark --ignore-user-config --skip-git-repo-check \\"
echo "      'Repeat the test marker token verbatim.'"
echo ""
echo "  If the model echoes 'zorblax-7741' → GREEN. If not → RED."
echo ""
if codex --help 2>&1 | grep -qi "agents.md\|AGENTS\.md"; then
  echo "  ✓ codex --help mentions AGENTS.md"
else
  echo "  ⚠ codex --help has no AGENTS.md mention (may still be doc-only feature)"
fi
echo ""

echo "── GRADING ───────────────────────────────────"
echo ""
echo "Record per-check verdicts in scripts/spike/RESULTS.md '## G0.5.2 — Cross-runtime':"
echo "  [ ] CLAUDE_PLUGIN_ROOT exported in Claude session:    GREEN / YELLOW / RED"
echo "  [ ] .codex-plugin/ discovery convention works:        GREEN / YELLOW / RED"
echo "  [ ] AGENTS.md auto-load (manual smoke above):         GREEN / RED"
echo ""
echo "Decision tree per plan U3:"
echo "  fully GREEN          →  keep .codex-plugin/ + AGENTS.md (Codex full support)"
echo "  AGENTS.md only GREEN →  drop .codex-plugin/, keep AGENTS.md (content parity)"
echo "  fully RED            →  drop Codex entirely; Claude-only plan"
