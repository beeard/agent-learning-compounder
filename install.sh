#!/bin/sh
set -eu

usage() {
  cat <<'USAGE'
Install agent-learning-compounder.

Usage:
  ./install.sh                                            (project install: detect runtime, verify, apply repo hooks)
  ./install.sh [--runtime codex|claude|all|auto] [--verify|--no-verify] [--install-deps] [--no-apply-runtime-hooks]
  ./install.sh [--codex|--codex-home|--claude|--plugin|--target DIR] [--runtime codex|claude|all|auto] [--verify]
  ./install.sh --bootstrap-repo DIR [--runtime codex|claude|all|auto] [--verify] [--apply-runtime-hooks]

Zero-argument project install behavior:
  - Uses the current directory as --bootstrap-repo.
  - Resolves runtime from AGENT_LEARNING_RUNTIME, repo hints, filesystem
    evidence (~/.claude/ vs ~/.agents/), then Codex by default.
  - Runs --verify and applies repo-local runtime hooks automatically.
  - Never writes user-scope runtime config unless you pass an explicit
    user/global install flag such as --codex, --claude, --codex-home, or --plugin.

Defaults:
  project scope   Install to <repo>/.agents/skills and/or <repo>/.claude/skills
  --runtime       auto (env/repo hints, filesystem runtime evidence, then codex)

Options:
  --codex                Install for Codex-compatible ~/.agents skills
  --codex-home           Install to ${CODEX_HOME:-$HOME/.codex}/skills
  --claude               Install to ${CLAUDE_HOME:-$HOME/.claude}/skills
  --plugin               Install as a Claude Code plugin under ${CLAUDE_HOME:-$HOME/.claude}/plugins
                         (agents/commands/hooks/skills all discovered together; implies --runtime claude)
  --target DIR           Install into an explicit skills root directory
  --runtime MODE         Codex/Claude runtime filter: codex|claude|all|auto
  --bootstrap-repo DIR    Install in project-local runtime roots and initialize the repo
  --apply-runtime-hooks  Apply runtime hooks during explicit bootstrap (default is dry-run)
  --no-apply-runtime-hooks
                         Do not apply hooks in zero-argument project install
  --no-first-run-index   Skip the post-bootstrap warm-loop (replay → index_events).
                         Default-on; also disabled by ALC_FIRST_RUN_INDEX=0.
  --install-deps         Install optional Python deps into <repo>/.agent-learning/venv
  --verify               Run the packaged unittest suite after install
  --no-verify            Skip the packaged unittest suite
  -h, --help             Show this help

The installer preserves an existing install by moving it to a timestamped backup.
USAGE
}

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
skill_src="$script_dir/agent-learning-compounder"

sanitizer="$script_dir/scripts/sanitize_skill_tree.sh"
if [ ! -f "$sanitizer" ]; then
  echo "missing $sanitizer (required for install-time sanitization)" >&2
  exit 1
fi
# shellcheck source=scripts/sanitize_skill_tree.sh
. "$sanitizer"

target_root="${AGENTS_SKILLS_DIR:-${AGENTS_HOME:-$HOME/.agents}/skills}"
target_mode="user"
runtime="auto"
bootstrap_repo=""
apply_runtime_hooks=0
verify=0
verify_explicit=0
install_mode_explicit=0
apply_runtime_hooks_explicit=0
target_root_explicit=0
plugin_mode=0
# Default-on warm-loop seam at end of --bootstrap-repo: replay hook events
# into events.jsonl then index into events.sqlite so a fresh install lands
# with a populated sqlite for alc_query/dashboard/MCP. Opt out via the
# --no-first-run-index flag or ALC_FIRST_RUN_INDEX=0 env var.
first_run_index="${ALC_FIRST_RUN_INDEX:-1}"
install_optional_deps=0
# Stays 0 until the caller selects a user/global install target or an explicit
# bootstrap repo. Runtime/verify/hook flags alone still use the default
# project-local install mode.

project_verify_env() {
  repo_root="$1"
  shift
  verify_home="$repo_root/.agent-learning/verify-home"
  mkdir -p "$verify_home"
  HOME="$verify_home" "$@"
}

resolve_runtime() {
  request="$1"
  repo="$2"
  if [ -n "$repo" ]; then
    topology_shell resolve-install-runtime --request "$request" --repo "$repo"
  else
    topology_shell resolve-install-runtime --request "$request"
  fi
}

# Pick a runtime from filesystem evidence. Used by the zero-arg install path
# only -- explicit flags and env vars take precedence and bypass this.
# Echoes one of: codex, claude, both, neither.
detect_runtime() {
  claude_dir="${CLAUDE_HOME:-$HOME/.claude}"
  codex_dir="${AGENTS_HOME:-$HOME/.agents}"
  claude_present=0
  codex_present=0
  [ -d "$claude_dir" ] && claude_present=1
  [ -d "$codex_dir" ] && codex_present=1
  if [ "$claude_present" = 1 ] && [ "$codex_present" = 0 ]; then
    printf 'claude'
  elif [ "$codex_present" = 1 ] && [ "$claude_present" = 0 ]; then
    printf 'codex'
  elif [ "$claude_present" = 1 ] && [ "$codex_present" = 1 ]; then
    printf 'both'
  else
    printf 'neither'
  fi
}

install_once() {
  root="$1"
  if [ -L "$root" ]; then
    echo "refusing to install into symlinked target root: $root" >&2
    exit 1
  fi
  mkdir -p "$root"
  dest="$root/agent-learning-compounder"
  if [ -L "$dest" ]; then
    echo "refusing to install into symlink: $dest" >&2
    exit 1
  fi
  if [ -e "$dest" ]; then
    stamp=$(date -u +%Y%m%dT%H%M%SZ)
    backup="$dest.bak-$stamp"
    if [ -e "$backup" ]; then
      i=2
      while [ -e "$backup-$i" ]; do
        i=$((i+1))
      done
      backup="$backup-$i"
    fi
    mv "$dest" "$backup"
    echo "existing install moved to $backup" >&2
  fi
  copy_skill "$dest"
  printf '%s\n' "$dest"
}

copy_skill() {
  dest="$1"
  cp -a "$skill_src" "$dest"
  sanitize_skill_tree "$dest"
}

# Ensure the React dashboard bundle exists. Published packages ship a built
# single-file bundle; source checkouts can rebuild it with pnpm.
build_dashboard_bundle() {
  dest="$1"
  bundle_root="$dest/dashboard/web"
  bundle_file="$bundle_root/dist/index.html"

  if [ ! -d "$bundle_root" ]; then
    return 0
  fi

  if [ -f "$bundle_file" ]; then
    echo "using shipped dashboard bundle: $bundle_file" >&2
    return 0
  fi

  if ! command -v pnpm >/dev/null 2>&1; then
    echo "dashboard bundle missing and pnpm not found in PATH." >&2
    echo "  expected packaged bundle: $bundle_file" >&2
    echo "  source checkout repair: cd \"$bundle_root\" && pnpm install && pnpm build" >&2
    return 1
  fi

  echo "building dashboard React bundle (pnpm install + pnpm build)..." >&2
  if (cd "$bundle_root" && pnpm install --silent && pnpm build) >&2; then
    if [ -f "$bundle_file" ]; then
      echo "  built $bundle_file" >&2
    else
      echo "  pnpm build completed but $bundle_file is missing" >&2
      rm -rf "$bundle_root/node_modules"
      return 1
    fi
    # node_modules is dev-only at this point; the built dist is all the
    # dashboard needs at runtime. Drop it to save ~200MB per install.
    rm -rf "$bundle_root/node_modules"
  else
    echo "  pnpm build failed; dashboard bundle is required for install." >&2
    echo "  retry with: cd \"$bundle_root\" && pnpm install && pnpm build" >&2
    rm -rf "$bundle_root/node_modules"
    return 1
  fi
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --codex)
      target_mode="user"
      runtime="codex"
      install_mode_explicit=1
      ;;
    --codex-home)
      target_mode="codex-home"
      runtime="codex"
      install_mode_explicit=1
      ;;
    --claude)
      target_mode="user"
      runtime="claude"
      install_mode_explicit=1
      ;;
    --plugin)
      plugin_mode=1
      runtime="claude"
      target_mode="plugin"
      target_root_explicit=1
      install_mode_explicit=1
      ;;
    --target)
      shift
      if [ "$#" -eq 0 ]; then
        echo "--target requires a directory" >&2
        exit 2
      fi
      target_root="$1"
      target_mode="explicit"
      target_root_explicit=1
      install_mode_explicit=1
      ;;
    --runtime)
      shift
      if [ "$#" -eq 0 ]; then
        echo "--runtime requires codex, claude, all, or auto" >&2
        exit 2
      fi
      case "$1" in
        codex|claude|all|auto)
          runtime="$1"
          ;;
        *)
          echo "--runtime must be codex, claude, all, or auto" >&2
          exit 2
          ;;
      esac
      ;;
    --bootstrap-repo)
      shift
      if [ "$#" -eq 0 ]; then
        echo "--bootstrap-repo requires a repo directory" >&2
        exit 2
      fi
      bootstrap_repo="$1"
      install_mode_explicit=1
      ;;
    --apply-runtime-hooks)
      apply_runtime_hooks=1
      apply_runtime_hooks_explicit=1
      ;;
    --no-apply-runtime-hooks)
      apply_runtime_hooks=0
      apply_runtime_hooks_explicit=1
      ;;
    --no-first-run-index)
      first_run_index=0
      ;;
    --install-deps|--install-optional-deps)
      install_optional_deps=1
      ;;
    --verify)
      verify=1
      verify_explicit=1
      ;;
    --no-verify)
      verify=0
      verify_explicit=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [ ! -f "$skill_src/SKILL.md" ] && [ ! -f "$skill_src/skills/alc-core/SKILL.md" ]; then
  echo "missing packaged skill at $skill_src" >&2
  exit 1
fi

if [ "$plugin_mode" = 1 ] && [ -n "$bootstrap_repo" ]; then
  echo "--plugin installs a user-global Claude Code plugin and cannot be combined with --bootstrap-repo" >&2
  exit 2
fi

if [ "$plugin_mode" = 1 ] && [ ! -f "$skill_src/.claude-plugin/plugin.json" ]; then
  echo "--plugin requires $skill_src/.claude-plugin/plugin.json (missing)" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required" >&2
  exit 1
fi

topology_shell() {
  python3 "$skill_src/bin/runtime_topology.py" --shell "$@"
}

# Default path: install into the current repo, not user scope. Explicit
# user/global install flags keep the old user-scope behavior.
if [ "$install_mode_explicit" = 0 ]; then
  bootstrap_repo="."
  if [ "$verify_explicit" = 0 ]; then
    verify=1
  fi
  if [ "$apply_runtime_hooks_explicit" = 0 ]; then
    apply_runtime_hooks=1
  fi
  if [ "$runtime" = "auto" ] && [ -z "${AGENT_LEARNING_RUNTIME:-}" ]; then
    repo_root=$(CDPATH= cd -- "$bootstrap_repo" && pwd)
    repo_hint=$(topology_shell runtime-hint --repo "$repo_root" 2>/dev/null || :)
    if [ -n "$repo_hint" ]; then
      runtime="$repo_hint"
    else
      detected=$(detect_runtime)
      case "$detected" in
        claude)
          echo "auto-detected runtime: claude (~/.claude/ present)" >&2
          runtime="claude"
          ;;
        codex)
          echo "auto-detected runtime: codex (~/.agents/ present)" >&2
          runtime="codex"
          ;;
        both)
          echo "auto-detected runtimes: codex and claude (~/.agents/ and ~/.claude present)" >&2
          runtime="all"
          ;;
        neither|*)
          echo "no runtime directory found; defaulting to codex project install" >&2
          runtime="codex"
          ;;
      esac
    fi
  fi
fi

if [ -n "$bootstrap_repo" ]; then
  repo_root=$(CDPATH= cd -- "$bootstrap_repo" && pwd)
  runtime=$(resolve_runtime "$runtime" "$repo_root")

  target_plan_file=$(mktemp "${TMPDIR:-/tmp}/alc-install-targets.XXXXXX")
  topology_shell install-targets --runtime "$runtime" --mode bootstrap --repo "$repo_root" > "$target_plan_file"

  bootstrap_dest=""
  while IFS='	' read -r mode dest_root; do
    dest="$(install_once "$dest_root")"
    if [ -z "$bootstrap_dest" ]; then
      bootstrap_dest="$dest"
    fi
  done < "$target_plan_file"

  if [ -z "$bootstrap_dest" ]; then
    echo "bootstrap failed to stage agent-learning-compounder" >&2
    exit 1
  fi

  if [ "$verify" -eq 1 ]; then
    (cd "$bootstrap_dest" && project_verify_env "$repo_root" python3 -m unittest discover -s fixtures/tests)
    (cd "$bootstrap_dest" && project_verify_env "$repo_root" python3 -m unittest discover -s tests)
    (cd "$bootstrap_dest" && project_verify_env "$repo_root" python3 scripts/run_pressure_tests.py)
    sanitize_skill_tree "$bootstrap_dest"
  fi

  while IFS='	' read -r mode dest_root; do
    build_dashboard_bundle "$dest_root/agent-learning-compounder"
  done < "$target_plan_file"

  python3 "$bootstrap_dest/bin/init_learning_system.py" \
    --repo "$repo_root" \
    --runtime "$runtime" \
    --install-repo-integration \
    --install-hooks \
    --self-test

  hook_mode="--dry-run"
  if [ "$apply_runtime_hooks" -eq 1 ]; then
    hook_mode="--apply"
  fi
  while IFS='	' read -r mode dest_root; do
    python3 "$bootstrap_dest/bin/install_runtime_hooks.py" \
      --repo "$repo_root" \
      --runtime "$mode" \
      "$hook_mode"
  done < "$target_plan_file"

  if [ "$hook_mode" = --dry-run ]; then
    echo "Runtime hooks ran in dry-run mode. Pass --apply-runtime-hooks to apply changes."
  fi

  # First-run: profile host repo, smoke alc_mcp, write session context.
  # Best-effort — failures here don't unwind the bootstrap.
  alc_init_extra=""
  if [ "$install_optional_deps" -eq 1 ]; then
    alc_init_extra="--install-deps"
  fi
  if ! python3 "$bootstrap_dest/bin/alc_init" --repo "$repo_root" $alc_init_extra >/dev/null; then
    echo "note: alc_init reported an issue (often just \"mcp not installed\"); run python3 $bootstrap_dest/bin/alc_init --repo $repo_root --install-deps to install optional deps into $repo_root/.agent-learning/venv." >&2
  fi

  # Warm-loop seam (PR 5): replay any accumulated hook events into
  # events.jsonl then advance the indexer cursor into events.sqlite. On a
  # truly fresh install hook-events.jsonl is empty and both steps no-op;
  # on a repo that already had a pre-bootstrap collector running this
  # backfills the sqlite the report pipeline, dashboard, and MCP read.
  # Best-effort — operator can re-run by hand if this trips.
  if [ "$first_run_index" -eq 1 ]; then
    if ! python3 "$bootstrap_dest/bin/alc_bootstrap_pipeline" --repo "$repo_root"; then
      echo "note: alc_bootstrap_pipeline reported an issue; re-run with: python3 $bootstrap_dest/bin/alc_bootstrap_pipeline --repo $repo_root" >&2
    fi
  fi

  printf 'bootstrapped agent-learning-compounder into: %s\n' "$repo_root"
  rm -f "$target_plan_file"
  exit 0
fi

runtime=$(resolve_runtime "$runtime" "")
if [ "$runtime" = "all" ] && [ "$target_root_explicit" -eq 0 ]; then
  echo "--runtime all requires --bootstrap-repo for explicit dual-runtime install; pass --runtime codex or --runtime claude" >&2
  exit 2
fi
target_root=$(topology_shell install-target-root --runtime "$runtime" --mode "$target_mode" --target-root "$target_root")

if [ -L "$target_root" ]; then
  echo "refusing to install into symlinked target root: $target_root" >&2
  exit 1
fi
dest="$target_root/agent-learning-compounder"

mkdir -p "$target_root"
if [ -L "$dest" ]; then
  echo "refusing to install into symlink: $dest" >&2
  exit 1
fi
if [ -e "$dest" ]; then
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  backup="$dest.bak-$stamp"
  if [ -e "$backup" ]; then
    i=2
    while [ -e "$backup-$i" ]; do
      i=$((i+1))
    done
    backup="$backup-$i"
  fi
  mv "$dest" "$backup"
  echo "existing install moved to $backup"
fi

copy_skill "$dest"
python3 -m py_compile "$dest/bin/init_learning_system" "$dest/bin/install_runtime_hooks"
sanitize_skill_tree "$dest"

if [ "$verify" -eq 1 ]; then
  (cd "$dest" && python3 -m unittest discover -s fixtures/tests)
  (cd "$dest" && python3 -m unittest discover -s tests)
  (cd "$dest" && python3 scripts/run_pressure_tests.py)
  sanitize_skill_tree "$dest"
fi

build_dashboard_bundle "$dest"

if [ "$plugin_mode" = 1 ]; then
  cat <<EOF
installed agent-learning-compounder as a Claude Code plugin to:
  $dest

Claude Code will auto-discover the plugin's agents, commands, hooks, and skills
from $dest/.claude-plugin/plugin.json on its next launch.

Per-repo init (optional, for the learning state under <repo>/.agent-learning/):
  python3 "$dest/scripts/init_learning_system.py" --repo "\$PWD" --runtime claude --install-repo-integration --install-hooks --self-test
EOF
else
  cat <<EOF
installed agent-learning-compounder to:
  $dest

Initialize a repo:
  python3 "$dest/scripts/init_learning_system.py" --repo "\$PWD" --runtime "$runtime" --install-repo-integration --install-hooks --self-test

Optionally wire runtime hooks after reviewing the plan:
  python3 "$dest/scripts/install_runtime_hooks.py" --repo "\$PWD" --runtime "$runtime" --dry-run
EOF
fi
