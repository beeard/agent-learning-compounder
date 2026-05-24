#!/bin/sh
# Reproducible release builder for agent-learning-compounder.
#
# Stages a clean copy of the repo, strips dev artifacts via the shared
# sanitize_skill_tree helper, and writes two content-reproducible archives:
#
#   dist/agent-learning-compounder-<version>.tar.gz
#   dist/agent-learning-compounder-<version>.zip
#
# Reproducibility is anchored by sorted file ordering, fixed mtimes,
# numeric ownership, and a gzip header with no embedded timestamp.
#
# Usage:
#   ./scripts/build_release.sh [--version X]
#
# Version defaults to MANIFEST.json["version"].
# Requires: GNU tar, zip, gzip, python3.

set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_root=$(CDPATH= cd -- "$script_dir/.." && pwd)
cd "$repo_root"

# shellcheck source=sanitize_skill_tree.sh
. "$script_dir/sanitize_skill_tree.sh"

version=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --version)
      shift
      [ "$#" -gt 0 ] || { echo "--version requires a value" >&2; exit 2; }
      version="$1"
      ;;
    -h|--help)
      sed -n 's/^# \{0,1\}//;3,18p' "$0"
      exit 0
      ;;
    *)
      echo "unknown option: $1" >&2
      exit 2
      ;;
  esac
  shift
done

if [ -z "$version" ]; then
  command -v python3 >/dev/null 2>&1 || {
    echo "python3 required to read MANIFEST.json (or pass --version)" >&2
    exit 1
  }
  version=$(python3 -c 'import json; print(json.load(open("MANIFEST.json"))["version"])')
fi

command -v tar >/dev/null 2>&1 || { echo "tar required" >&2; exit 1; }
command -v gzip >/dev/null 2>&1 || { echo "gzip required" >&2; exit 1; }
command -v zip >/dev/null 2>&1 || { echo "zip required" >&2; exit 1; }
command -v sha256sum >/dev/null 2>&1 || { echo "sha256sum required" >&2; exit 1; }

# Top-level layout shipped in the release. Matches the existing tarball.
top_files=".gitignore CHANGES.md MANIFEST.json README.md install.sh"
# `docs` ships so README and CHANGES references to
# docs/history/PLAN-eight-upgrade.md and docs/llm-install-prompt.md
# resolve inside a freshly-extracted tarball. docs/dev is pruned below
# because A-3 moved those internal release-process docs out of the
# user-facing surface on purpose.
top_dirs="agent-learning-compounder scripts docs"

for f in $top_files; do
  [ -e "$repo_root/$f" ] || { echo "missing $f at repo root" >&2; exit 1; }
done
for d in $top_dirs; do
  [ -d "$repo_root/$d" ] || { echo "missing $d/ at repo root" >&2; exit 1; }
done

name="agent-learning-compounder-$version"
dist_dir="$repo_root/dist"
mkdir -p "$dist_dir"

stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT

stage_root="$stage/$name"
mkdir -p "$stage_root"

for f in $top_files; do
  cp -a "$repo_root/$f" "$stage_root/$f"
done
for d in $top_dirs; do
  cp -a "$repo_root/$d" "$stage_root/$d"
done

# Strip __pycache__, .pytest_cache, .agent-learning, *.pyc, *.pyo,
# .agent-learning.json. Same exclusion set install.sh enforces at install time.
sanitize_skill_tree "$stage_root/agent-learning-compounder"

# docs/dev/ holds internal release-process notes that A-3 moved out of
# the shipped skill. Keep them in the source tree but not in the tarball.
rm -rf "$stage_root/docs/dev"

# Normalize on-disk mtimes so the zip archive (which records per-file
# mtimes from the filesystem) is reproducible. tar --mtime overrides
# embedded entries independently, but normalizing once keeps both paths
# anchored to the same timestamp.
mtime_iso="2026-05-24T00:00:00Z"
mtime_touch="202605240000.00"
find "$stage_root" -exec touch -t "$mtime_touch" {} +

out_tar="$dist_dir/$name.tar.gz"
out_tar_tmp="$out_tar.tmp"
(
  cd "$stage" && \
  find "$name" -print | LC_ALL=C sort | \
  tar --owner=0 --group=0 --numeric-owner \
      --mtime="$mtime_iso" \
      --no-recursion \
      --files-from=- \
      -cf -
) | gzip -n -9 > "$out_tar_tmp"
mv "$out_tar_tmp" "$out_tar"

out_zip="$dist_dir/$name.zip"
out_zip_tmp="$out_zip.tmp"
rm -f "$out_zip_tmp"
(
  cd "$stage" && \
  find "$name" -print | LC_ALL=C sort | zip -X -q -@ "$out_zip_tmp"
)
mv "$out_zip_tmp" "$out_zip"

# Regenerate SHA256SUMS over every archive currently in dist/.
# Sorted by filename so re-runs produce identical sums files.
sums="$dist_dir/SHA256SUMS"
sums_tmp="$sums.tmp"
(
  cd "$dist_dir" && \
  ls -1 *.tar.gz *.zip 2>/dev/null | LC_ALL=C sort | \
  while IFS= read -r entry; do
    sha256sum "$entry"
  done
) > "$sums_tmp"
mv "$sums_tmp" "$sums"

echo "built:"
echo "  $out_tar"
echo "  $out_zip"
echo
echo "dist/SHA256SUMS:"
sed 's/^/  /' "$sums"
