#!/usr/bin/env python3
"""Merge repo-local ALC dev hooks into .claude/settings.local.json.

Plugin-level hooks (those in ``agent-learning-compounder/hooks/hooks.json``
are supposed to merge into the active session's effective hook config
automatically via the plugin loader. In practice they don't reliably do
so — verified by running ``git commit`` in a session with the plugin
enabled and observing no auto-update prompt fired.

This script copies those hooks into ``<repo>/.claude/settings.local.json``
by hand. Idempotent — checks for command-string equality before adding.
It deliberately does not copy hooks from user-scope plugin caches.

Verify mode prints per-event hook counts and flags any expected hook
that's missing, without changing the file.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from typing import Any

REPO_DEFAULT = pathlib.Path(__file__).resolve().parents[1]
BIN_DIR = REPO_DEFAULT / "agent-learning-compounder" / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

from runtime_topology import dev_hook_specs

SETTINGS_REL = ".claude/settings.local.json"

def expected_hooks(repo: pathlib.Path) -> list[dict[str, Any]]:
    # Centralized in runtime_topology so mode semantics are not duplicated
    # across adapter scripts.
    return dev_hook_specs(repo)


def load_settings(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return {"hooks": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read {path}: {exc}")
    if not isinstance(data, dict):
        raise SystemExit(f"{path} must contain a JSON object")
    data.setdefault("hooks", {})
    return data


def write_settings(path: pathlib.Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
    fd = os.open(str(path), flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")


def has_command_with_substring(
    rows: list[Any], needle: str
) -> bool:
    for row in rows:
        if not isinstance(row, dict):
            continue
        for hook in row.get("hooks", []):
            if not isinstance(hook, dict):
                continue
            cmd = hook.get("command")
            if isinstance(cmd, str) and needle in cmd:
                return True
    return False


def find_hook_with_substring(
    rows: list[Any], needle: str
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    for row in rows:
        if not isinstance(row, dict):
            continue
        for hook in row.get("hooks", []):
            if not isinstance(hook, dict):
                continue
            cmd = hook.get("command")
            if isinstance(cmd, str) and needle in cmd:
                return row, hook
    return None


def prune_user_scope_hooks(hooks_root: dict[str, Any]) -> int:
    """Remove known user-scope plugin-cache hooks from repo-local settings."""
    removed = 0
    for event, rows in list(hooks_root.items()):
        if not isinstance(rows, list):
            continue
        kept_rows = []
        for row in rows:
            if not isinstance(row, dict):
                kept_rows.append(row)
                continue
            hooks = row.get("hooks", [])
            if not isinstance(hooks, list):
                kept_rows.append(row)
                continue
            kept_hooks = []
            for hook in hooks:
                cmd = hook.get("command") if isinstance(hook, dict) else None
                if (
                    isinstance(cmd, str)
                    and "understand-anything" in cmd
                    and "/.claude/plugins/cache/" in cmd
                ):
                    removed += 1
                    continue
                kept_hooks.append(hook)
            if kept_hooks:
                new_row = dict(row)
                new_row["hooks"] = kept_hooks
                kept_rows.append(new_row)
        hooks_root[event] = kept_rows
    return removed


def add_hook(rows: list[Any], matcher: str, command: str) -> None:
    rows.append({
        "matcher": matcher,
        "hooks": [{"type": "command", "command": command}],
    })


def apply(repo: pathlib.Path) -> tuple[int, int]:
    settings_path = repo / SETTINGS_REL
    data = load_settings(settings_path)
    hooks_root: dict[str, Any] = data.setdefault("hooks", {})
    added = 0
    updated = 0
    skipped = 0
    pruned = prune_user_scope_hooks(hooks_root)
    for entry in expected_hooks(repo):
        event = entry["event"]
        rows = hooks_root.setdefault(event, [])
        if not isinstance(rows, list):
            raise SystemExit(f"{settings_path} hooks.{event} must be a list")
        found = find_hook_with_substring(rows, entry["match"])
        if found is not None:
            _, hook = found
            if hook.get("command") != entry["command"]:
                hook["command"] = entry["command"]
                updated += 1
                print(f"  ~ {event:<12} {entry['label']}")
                continue
            skipped += 1
            continue
        add_hook(rows, entry["matcher"], entry["command"])
        added += 1
        print(f"  + {event:<12} {entry['label']}")
    if added or updated or pruned:
        write_settings(settings_path, data)
    print(f"  added: {added}  updated: {updated}  pruned: {pruned}  already-present: {skipped}")
    return added, skipped


def verify(repo: pathlib.Path) -> int:
    settings_path = repo / SETTINGS_REL
    if not settings_path.exists():
        print(f"MISSING {settings_path} — run scripts/dev-session-setup.sh", file=sys.stderr)
        return 1
    data = load_settings(settings_path)
    hooks_root = data.get("hooks", {})
    print(f"  reading {settings_path}")
    print(f"  per-event counts:")
    for event in ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"):
        rows = hooks_root.get(event, [])
        total = sum(len(r.get("hooks", [])) for r in rows if isinstance(r, dict))
        print(f"    {event:<18} {total}")
    print(f"  expected-hook check:")
    missing = 0
    for entry in expected_hooks(repo):
        rows = hooks_root.get(entry["event"], [])
        present = has_command_with_substring(rows, entry["match"])
        marker = "OK " if present else "MIS"
        print(f"    [{marker}] {entry['event']:<12} {entry['label']}")
        if not present:
            missing += 1
    return 0 if missing == 0 else 2


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=pathlib.Path, default=REPO_DEFAULT,
                   help="Repo root (default: this script's parent's parent).")
    p.add_argument("--verify", action="store_true",
                   help="Verify-only mode; don't modify settings.local.json.")
    args = p.parse_args(argv)
    repo = args.repo.expanduser().resolve()
    if args.verify:
        return verify(repo)
    apply(repo)
    return verify(repo)


if __name__ == "__main__":
    raise SystemExit(main())
