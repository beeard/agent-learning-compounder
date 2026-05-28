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
#   ./scripts/build_release.sh [--version X] [--source-ref REF]
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
source_ref="HEAD"
local_experiment="${ALC_ALLOW_DIRTY_RELEASE:-0}"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --version)
      shift
      [ "$#" -gt 0 ] || { echo "--version requires a value" >&2; exit 2; }
      version="$1"
      ;;
    --source-ref)
      shift
      [ "$#" -gt 0 ] || { echo "--source-ref requires a value" >&2; exit 2; }
      source_ref="$1"
      ;;
    --local-experiment)
      local_experiment=1
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

command -v python3 >/dev/null 2>&1 || {
  echo "python3 required to read release metadata and layout" >&2
  exit 1
}

if [ -z "$version" ]; then
  version=$(python3 -c 'import json; print(json.load(open("MANIFEST.json"))["version"])')
fi

command -v tar >/dev/null 2>&1 || { echo "tar required" >&2; exit 1; }
command -v gzip >/dev/null 2>&1 || { echo "gzip required" >&2; exit 1; }
command -v zip >/dev/null 2>&1 || { echo "zip required" >&2; exit 1; }
command -v sha256sum >/dev/null 2>&1 || { echo "sha256sum required" >&2; exit 1; }

release_layout_py="$repo_root/agent-learning-compounder/bin/release_layout.py"
release_manifest_py="$repo_root/agent-learning-compounder/bin/release_manifest.py"
top_files=$(python3 "$release_layout_py" --shell top-files)
top_dirs=$(python3 "$release_layout_py" --shell top-dirs)
build_pruned_paths=$(python3 "$release_layout_py" --shell build-pruned-paths)

if [ "$local_experiment" != 1 ]; then
  command -v git >/dev/null 2>&1 || { echo "git required for publishable release source materialization" >&2; exit 1; }
  python3 "$release_manifest_py" check-source-clean --repo-root "$repo_root"
fi

name="agent-learning-compounder-$version"
dist_dir="$repo_root/dist"
mkdir -p "$dist_dir"

stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT

stage_root="$stage/$name"
mkdir -p "$stage_root"

if [ "$local_experiment" = 1 ]; then
  source_root="$repo_root"
else
  source_root="$stage/source"
  mkdir -p "$source_root"
  git archive --format=tar "$source_ref" | tar -xf - -C "$source_root"
fi

for f in $top_files; do
  [ -e "$source_root/$f" ] || { echo "missing $f at source root" >&2; exit 1; }
done
for d in $top_dirs; do
  [ -d "$source_root/$d" ] || { echo "missing $d/ at source root" >&2; exit 1; }
done

for f in $top_files; do
  cp -a "$source_root/$f" "$stage_root/$f"
done
for d in $top_dirs; do
  cp -a "$source_root/$d" "$stage_root/$d"
done

# Strip generated/cache files from every shipped top-level path. Same exclusion
# set install.sh enforces at install time, widened beyond the inner skill tree
# because top-level scripts/docs are shipped too.
sanitize_skill_tree "$stage_root"

for path in $build_pruned_paths; do
  rm -rf "$stage_root/$path"
done

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

# Regenerate SHA256SUMS over the current release set only. Stale entries in
# this file make release readiness ambiguous.
sums="$dist_dir/SHA256SUMS"
sums_tmp="$sums.tmp"
(
  cd "$dist_dir" && \
  printf '%s\n' "$name.tar.gz" "$name.zip" | LC_ALL=C sort | \
  while IFS= read -r entry; do
    sha256sum "$entry"
  done
) > "$sums_tmp"
mv "$sums_tmp" "$sums"

if [ "$local_experiment" = 1 ]; then
  echo "local experiment build: skipped publishable release-manifest source commit inventory" >&2
elif command -v npm >/dev/null 2>&1; then
  python3 "$release_manifest_py" write --dist "$dist_dir" --version "$version" --source-ref "$source_ref" >/dev/null
else
  echo "npm not found; skipped release-manifest npm inventory" >&2
fi

echo "built:"
echo "  $out_tar"
echo "  $out_zip"
echo
echo "dist/SHA256SUMS:"
sed 's/^/  /' "$sums"
