#!/bin/sh
# Shared dev-artifact stripper for install.sh and scripts/build_release.sh.
# Sourced (not executed) so the same exclusion set is enforced at both
# package time and install time. Drift between those two layers is what
# shipped .pytest_cache/ inside dist/agent-learning-compounder-2026.05.24+review7-plus1.tar.gz.
#
# Usage:
#   . "$dir/scripts/sanitize_skill_tree.sh"
#   sanitize_skill_tree /path/to/agent-learning-compounder

SANITIZE_DIR_EXCLUDES='__pycache__ .pytest_cache .agent-learning node_modules dist'
SANITIZE_FILE_EXCLUDES='*.pyc *.pyo .agent-learning.json'

sanitize_skill_tree() {
  root="$1"
  if [ -z "$root" ] || [ ! -d "$root" ]; then
    echo "sanitize_skill_tree: not a directory: $root" >&2
    return 1
  fi
  find "$root" \( -name '__pycache__' -o -name '.pytest_cache' -o -name '.agent-learning' -o -name 'node_modules' -o -name 'dist' \) -type d -prune -exec rm -rf {} +
  find "$root" \( -name '*.pyc' -o -name '*.pyo' -o -name '.agent-learning.json' \) -type f -exec rm -f {} +
}
