#!/bin/sh
# bootstrap.sh — curl-pipe-sh installer for agent-learning-compounder.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/beeard/agent-learning-compounder/master/bootstrap.sh | sh
#   curl -fsSL .../bootstrap.sh | sh -s -- --plugin             # install as Claude Code plugin
#   curl -fsSL .../bootstrap.sh | sh -s -- --bootstrap-repo "$PWD" --verify
#
# Overrides:
#   ALC_REPO   override the source repo (default: beeard/agent-learning-compounder)
#   ALC_REF    override the git ref/tag (default: master)
#
# Downloads the repo tarball, extracts to a temp dir, and exec's install.sh
# with any forwarded arguments. The temp dir is removed on exit; the installer
# itself decides what to leave behind.

set -eu

repo="${ALC_REPO:-beeard/agent-learning-compounder}"
ref="${ALC_REF:-master}"
tarball_url="https://github.com/${repo}/archive/${ref}.tar.gz"

if ! command -v curl >/dev/null 2>&1; then
  echo "bootstrap.sh: curl is required" >&2
  exit 1
fi
if ! command -v tar >/dev/null 2>&1; then
  echo "bootstrap.sh: tar is required" >&2
  exit 1
fi

tmp="$(mktemp -d 2>/dev/null || mktemp -d -t 'alc-bootstrap')"
trap 'rm -rf "$tmp"' EXIT INT TERM HUP

echo "Fetching $tarball_url ..." >&2
curl -fsSL "$tarball_url" | tar -xz -C "$tmp" --strip-components=1

if [ ! -x "$tmp/install.sh" ]; then
  echo "bootstrap.sh: install.sh missing or not executable in fetched archive" >&2
  exit 1
fi

exec "$tmp/install.sh" "$@"
