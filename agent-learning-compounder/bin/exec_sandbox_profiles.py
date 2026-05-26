#!/usr/bin/env python3
"""Tier definitions for exec_sandbox."""

from __future__ import annotations


# Single source of truth for sandbox tier behavior.
SCOPES = {
    "read": {
        "label": "read",
        "default_timeout_s": 30,
        "max_timeout_s": 120,
        "require_worktree": False,
        "allowlist_tokens": [
            ("git", "log"),
            ("git", "show"),
            ("git", "diff"),
            ("git", "blame"),
            ("ls",),
            ("find",),
            ("cat",),
            ("head",),
            ("tail",),
            ("wc",),
            ("grep",),
            ("stat",),
            ("python", "-m", "unittest"),
            ("python3", "-m", "unittest"),
            ("pytest",),
            ("diff",),
        ],
    },
    "worktree": {
        "label": "worktree",
        "default_timeout_s": 60,
        "max_timeout_s": 300,
        "require_worktree": True,
    },
    "eval": {
        "label": "eval",
        "default_timeout_s": 300,
        "max_timeout_s": 900,
        "require_worktree": True,
    },
}
