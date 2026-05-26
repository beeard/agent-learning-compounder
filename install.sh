#!/bin/sh
set -eu

usage() {
  cat <<'USAGE'
Install agent-learning-compounder.

Usage:
  ./install.sh                                            (zero-config: detect runtime, verify)
  ./install.sh [--codex|--codex-home|--claude|--target DIR] [--runtime codex|claude|all|auto] [--verify]
  ./install.sh --bootstrap-repo DIR [--runtime codex|claude|all|auto] [--verify] [--apply-runtime-hooks]

Zero-config behavior (when no runtime/target flag is passed and
AGENT_LEARNING_RUNTIME is unset):
  - Detect runtime from filesystem (~/.claude/ vs ~/.agents/);
    prompt once if both are present, default to codex if neither.
  - Run --verify automatically.

Defaults:
  --codex         Install to ${AGENTS_HOME:-$HOME/.agents}/skills
  --runtime       auto (from AGENT_LEARNING_RUNTIME or repo instruction, then codex)

Options:
  --codex                Install for Codex-compatible ~/.agents skills
  --codex-home           Install to ${CODEX_HOME:-$HOME/.codex}/skills
  --claude               Install to ${CLAUDE_HOME:-$HOME/.claude}/skills
  --target DIR           Install into an explicit skills root directory
  --runtime MODE         Codex/Claude runtime filter: codex|claude|all|auto
  --bootstrap-repo DIR    Install in project-local runtime roots and initialize the repo
  --apply-runtime-hooks  Apply runtime hooks during bootstrap (default is dry-run)
  --verify               Run the packaged unittest suite after install
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
runtime="auto"
bootstrap_repo=""
apply_runtime_hooks=0
verify=0
target_root_explicit=0
# Stays 1 while no runtime/target/bootstrap flag has been passed; the
# zero-arg install path picks the runtime by filesystem detection and
# turns on --verify only when this is still 1 after arg parsing.
auto_detect=1

runtime_hint() {
  repo="$1"
  for path in "$repo/AGENTS.md" "$repo/CLAUDE.md" "$repo/GEMINI.md"; do
    if [ ! -f "$path" ]; then
      continue
    fi
    hint=$(awk '
      {
        line = tolower($0)
        if (match(line, /runtime[[:space:]]*[:=][[:space:]]*(codex|claude|all)/)) {
          match_value = substr(line, RSTART, RLENGTH)
          sub(/.*runtime[[:space:]]*[:=][[:space:]]*/, "", match_value)
          print match_value
          exit
        }
      }' "$path" || true)
    if [ -n "$hint" ]; then
      printf '%s' "$hint"
      return 0
    fi
  done
  return 1
}

resolve_runtime() {
  request="$1"
  repo="$2"
  if [ "$request" != "auto" ]; then
    printf '%s' "$request"
    return
  fi

  requested_runtime="${AGENT_LEARNING_RUNTIME:-}"
  case "$requested_runtime" in
    codex|claude|all) printf '%s' "$requested_runtime"; return ;;
  esac

  if [ -n "$repo" ]; then
    hint=$(runtime_hint "$repo" || true)
    if [ -n "$hint" ]; then
      printf '%s' "$hint"
      return
    fi
  fi

  printf 'codex'
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

runtime_targets() {
  mode="$1"
  if [ "$mode" = "all" ]; then
    echo "codex"
    echo "claude"
    return
  fi
  printf '%s\n' "$mode"
}

runtime_root() {
  repo="$1"
  mode="$2"
  case "$mode" in
    codex)
      printf '%s/.agents/skills' "$repo"
      ;;
    claude)
      printf '%s/.claude/skills' "$repo"
      ;;
    *)
      return 1
      ;;
  esac
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

while [ "$#" -gt 0 ]; do
  case "$1" in
    --codex)
      target_root="${AGENTS_SKILLS_DIR:-${AGENTS_HOME:-$HOME/.agents}/skills}"
      auto_detect=0
      ;;
    --codex-home)
      target_root="${CODEX_HOME:-$HOME/.codex}/skills"
      auto_detect=0
      ;;
    --claude)
      target_root="${CLAUDE_HOME:-$HOME/.claude}/skills"
      auto_detect=0
      ;;
    --target)
      shift
      if [ "$#" -eq 0 ]; then
        echo "--target requires a directory" >&2
        exit 2
      fi
      target_root="$1"
      target_root_explicit=1
      auto_detect=0
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
      auto_detect=0
      ;;
    --bootstrap-repo)
      shift
      if [ "$#" -eq 0 ]; then
        echo "--bootstrap-repo requires a repo directory" >&2
        exit 2
      fi
      bootstrap_repo="$1"
      auto_detect=0
      ;;
    --apply-runtime-hooks)
      apply_runtime_hooks=1
      ;;
    --verify)
      verify=1
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

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required" >&2
  exit 1
fi

# Zero-arg path: detect the runtime from filesystem state and turn on
# --verify by default. Skipped when any explicit flag set auto_detect=0,
# and skipped when AGENT_LEARNING_RUNTIME is set so env-var configuration
# still wins (consistent with resolve_runtime's precedence).
if [ "$auto_detect" = 1 ] && [ -z "${AGENT_LEARNING_RUNTIME:-}" ]; then
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
      printf 'both ~/.claude/ and ~/.agents/ present. Install runtime? [codex/claude] (default codex): ' >&2
      choice=""
      if [ -r /dev/tty ]; then
        read -r choice < /dev/tty || choice=""
      fi
      case "$choice" in
        c|C|claude|Claude|CLAUDE) runtime="claude" ;;
        *) runtime="codex" ;;
      esac
      echo "selected runtime: $runtime" >&2
      ;;
    neither|*)
      echo "no runtime directory found; defaulting to codex (~/.agents/skills)" >&2
      runtime="codex"
      ;;
  esac
  verify=1
fi

if [ -n "$bootstrap_repo" ]; then
  repo_root=$(CDPATH= cd -- "$bootstrap_repo" && pwd)
  runtime=$(resolve_runtime "$runtime" "$repo_root")

  bootstrap_dest=""
  for mode in $(runtime_targets "$runtime"); do
    dest_root="$(runtime_root "$repo_root" "$mode")"
    dest="$(install_once "$dest_root")"
    if [ -z "$bootstrap_dest" ]; then
      bootstrap_dest="$dest"
    fi
  done

  if [ -z "$bootstrap_dest" ]; then
    echo "bootstrap failed to stage agent-learning-compounder" >&2
    exit 1
  fi

  if [ "$verify" -eq 1 ]; then
    (cd "$bootstrap_dest" && python3 -m unittest discover -s fixtures/tests)
    (cd "$bootstrap_dest" && python3 -m unittest discover -s tests)
    (cd "$bootstrap_dest" && python3 scripts/run_pressure_tests.py)
    sanitize_skill_tree "$bootstrap_dest"
  fi

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
  for mode in $(runtime_targets "$runtime"); do
    python3 "$bootstrap_dest/bin/install_runtime_hooks.py" \
      --repo "$repo_root" \
      --runtime "$mode" \
      "$hook_mode"
  done

  if [ "$hook_mode" = --dry-run ]; then
    echo "Runtime hooks ran in dry-run mode. Pass --apply-runtime-hooks to apply changes."
  fi
  printf 'bootstrapped agent-learning-compounder into: %s\n' "$repo_root"
  exit 0
fi

runtime=$(resolve_runtime "$runtime" "")
if [ "$runtime" = "all" ] && [ "$target_root_explicit" -eq 0 ]; then
  echo "--runtime all requires --bootstrap-repo for explicit dual-runtime install; pass --runtime codex or --runtime claude" >&2
  exit 2
fi
if [ "$runtime" = "codex" ] && [ "$target_root_explicit" -eq 0 ]; then
  target_root="${AGENTS_SKILLS_DIR:-${AGENTS_HOME:-$HOME/.agents}/skills}"
fi
if [ "$runtime" = "claude" ] && [ "$target_root_explicit" -eq 0 ]; then
  target_root="${CLAUDE_HOME:-$HOME/.claude}/skills"
fi

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

cat <<EOF
installed agent-learning-compounder to:
  $dest

Initialize a repo:
  python3 "$dest/scripts/init_learning_system.py" --repo "\$PWD" --runtime "$runtime" --install-repo-integration --install-hooks --self-test

Optionally wire runtime hooks after reviewing the plan:
  python3 "$dest/scripts/install_runtime_hooks.py" --repo "\$PWD" --runtime "$runtime" --dry-run
EOF
