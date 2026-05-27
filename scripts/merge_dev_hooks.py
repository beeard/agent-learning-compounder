#!/usr/bin/env python3
"""Merge plugin + understand-anything hooks into .claude/settings.local.json.

Plugin-level hooks (those in ``agent-learning-compounder/hooks/hooks.json``
and in ``~/.claude/plugins/cache/understand-anything*/hooks/hooks.json``)
are supposed to merge into the active session's effective hook config
automatically via the plugin loader. In practice they don't reliably do
so — verified by running ``git commit`` in a session with the plugin
enabled and observing no auto-update prompt fired.

This script copies those hooks into ``<repo>/.claude/settings.local.json``
by hand. Idempotent — checks for command-string equality before adding.

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
SETTINGS_REL = ".claude/settings.local.json"

# Hooks we expect to be present after setup. Each entry is:
#   (event_name, command_substring_to_match, full_command_to_add, matcher)
# command_substring keeps the idempotency check tolerant to absolute
# paths varying across machines while still catching duplicates.


def plugin_root(repo: pathlib.Path) -> pathlib.Path:
    return repo / "agent-learning-compounder"


def understand_anything_hook_command() -> str | None:
    """Return the auto-update PostToolUse command if the plugin is installed.

    Walks ``~/.claude/plugins/cache/understand-anything*/`` to find the
    plugin's hooks.json and lifts the exact PostToolUse Bash command. We
    can't blindly hardcode it because the plugin version changes the
    install path.
    """
    cache = pathlib.Path.home() / ".claude" / "plugins" / "cache"
    if not cache.is_dir():
        return None
    for candidate in cache.rglob("hooks.json"):
        if "understand-anything" not in str(candidate):
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for entry in data.get("hooks", {}).get("PostToolUse", []):
            for hook in entry.get("hooks", []):
                cmd = hook.get("command")
                if isinstance(cmd, str) and "understand-anything" in cmd:
                    return cmd
    return None


def expected_hooks(repo: pathlib.Path) -> list[dict[str, Any]]:
    plugin = plugin_root(repo)
    entries: list[dict[str, Any]] = [
        {
            "event": "Stop",
            "label": "warm-loop (events.sqlite refresh)",
            "match": "alc_bootstrap_pipeline",
            "matcher": "",
            "command": (
                f"{sys.executable} {plugin}/bin/alc_bootstrap_pipeline "
                f"--repo {repo} --quiet"
            ),
        },
        {
            "event": "Stop",
            "label": "refresh_dashboard (regenerate dashboard payload)",
            "match": "refresh_dashboard.py",
            "matcher": "",
            "command": f"{plugin}/hooks/refresh_dashboard.py",
        },
        {
            "event": "Stop",
            "label": "render_state_surface session-report",
            "match": "render_state_surface",
            "matcher": "",
            "command": (
                f"{plugin}/bin/render_state_surface --repo {repo} "
                "--format session-report"
            ),
        },
    ]
    ua_cmd = understand_anything_hook_command()
    if ua_cmd is not None:
        entries.append({
            "event": "PostToolUse",
            "label": "understand-anything auto-update (graph refresh on git commit)",
            "match": "understand-anything",
            "matcher": "Bash",
            "command": ua_cmd,
        })
    return entries


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
    skipped = 0
    for entry in expected_hooks(repo):
        event = entry["event"]
        rows = hooks_root.setdefault(event, [])
        if not isinstance(rows, list):
            raise SystemExit(f"{settings_path} hooks.{event} must be a list")
        if has_command_with_substring(rows, entry["match"]):
            skipped += 1
            continue
        add_hook(rows, entry["matcher"], entry["command"])
        added += 1
        print(f"  + {event:<12} {entry['label']}")
    if added:
        write_settings(settings_path, data)
    print(f"  added: {added}  already-present: {skipped}")
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
