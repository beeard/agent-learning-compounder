#!/usr/bin/env python3
"""Canonical release layout policy for package and archive adapters."""

from __future__ import annotations

import argparse
import fnmatch
import pathlib
import shlex


SHIPPED_TOP_LEVEL_FILES = (
    ".gitignore",
    "CHANGES.md",
    "MANIFEST.json",
    "README.md",
    "install.sh",
)

SHIPPED_TOP_LEVEL_DIRS = (
    "agent-learning-compounder",
    "scripts",
    "docs",
)

BUILD_PRUNED_PATHS = (
    "docs/dev",
)

SANITIZER_DIR_EXCLUSIONS = (
    "__pycache__",
    ".pytest_cache",
    ".agent-learning",
    "node_modules",
    "dist",
)

SANITIZER_FILE_EXCLUSIONS = (
    "*.pyc",
    "*.pyo",
    ".agent-learning.json",
)

MANIFEST_EXCLUDED_FROM_PACKAGE = (
    "__pycache__",
    ".pytest_cache",
    ".agent-learning",
    "node_modules",
    "dist",
    "*.pyc",
    "*.pyo",
    ".agent-learning.json",
    "docs/dev",
    "review-patches.diff",
    "runtime state",
)

REQUIRED_DOCS = (
    "README.md",
    "CHANGES.md",
    "agent-learning-compounder/skills/alc-core/SKILL.md",
    "agent-learning-compounder/skills/alc-core/references/agent-quickstart.md",
    "agent-learning-compounder/skills/alc-core/references/architecture.md",
    "agent-learning-compounder/skills/alc-core/references/event-schema-evolution.md",
    "agent-learning-compounder/skills/alc-core/references/queue-dedup.md",
    "agent-learning-compounder/skills/alc-core/references/gate-effectiveness.md",
    "agent-learning-compounder/skills/alc-core/references/domain-rules-learning.md",
    "agent-learning-compounder/skills/alc-core/references/cross-repo-gates.md",
)

NPM_FILES = (
    "install.sh",
    "bootstrap.sh",
    "scripts/alc-install.mjs",
    "scripts/sanitize_skill_tree.sh",
    "scripts/build_release.sh",
    "agent-learning-compounder/",
    ".claude-plugin/marketplace.json",
    "README.md",
    "CHANGES.md",
    "MANIFEST.json",
    "LICENSE",
)


def _normalized_parts(relative_path: pathlib.Path | str) -> tuple[str, ...]:
    return pathlib.PurePosixPath(str(relative_path)).parts


def is_build_pruned(relative_path: pathlib.Path | str) -> bool:
    path = pathlib.PurePosixPath(str(relative_path))
    for pruned in BUILD_PRUNED_PATHS:
        pruned_path = pathlib.PurePosixPath(pruned)
        if path == pruned_path or pruned_path in path.parents:
            return True
    return False


def is_sanitizer_excluded(relative_path: pathlib.Path | str) -> bool:
    parts = _normalized_parts(relative_path)
    if any(part in SANITIZER_DIR_EXCLUSIONS for part in parts):
        return True
    name = pathlib.PurePosixPath(str(relative_path)).name
    return any(fnmatch.fnmatch(name, pattern) for pattern in SANITIZER_FILE_EXCLUSIONS)


def is_release_excluded(relative_path: pathlib.Path | str) -> bool:
    return is_build_pruned(relative_path) or is_sanitizer_excluded(relative_path)


def iter_release_files(repo_root: pathlib.Path) -> list[pathlib.Path]:
    """Return repo-relative files/symlinks that the archive layout ships."""
    root = pathlib.Path(repo_root)
    files: list[pathlib.Path] = []
    for rel in SHIPPED_TOP_LEVEL_FILES:
        path = root / rel
        if path.exists():
            files.append(pathlib.Path(rel))
    for rel_dir in SHIPPED_TOP_LEVEL_DIRS:
        base = root / rel_dir
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() and not path.is_symlink():
                continue
            relative = path.relative_to(root)
            if not is_release_excluded(relative):
                files.append(relative)
    return sorted(files, key=lambda path: path.as_posix())


def _shell_words(values: tuple[str, ...]) -> str:
    return " ".join(shlex.quote(value) for value in values)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--shell",
        choices=("top-files", "top-dirs", "build-pruned-paths"),
        help="print a shell-safe list for release shell adapters",
    )
    args = parser.parse_args()

    if args.shell == "top-files":
        print(_shell_words(SHIPPED_TOP_LEVEL_FILES))
    elif args.shell == "top-dirs":
        print(_shell_words(SHIPPED_TOP_LEVEL_DIRS))
    elif args.shell == "build-pruned-paths":
        print(_shell_words(BUILD_PRUNED_PATHS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
