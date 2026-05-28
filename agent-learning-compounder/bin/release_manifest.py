#!/usr/bin/env python3
"""Inspect release package contents and write deterministic file manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from typing import Iterable

import release_layout
import release_metadata


EXCLUDED_LABEL = "__pycache__|*.pyc|*.pyo|.pytest_cache|node_modules|dist|.agent-learning"


@dataclass(frozen=True)
class FileEntry:
    path: str
    size: int
    sha256: str

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path, "size": self.size, "sha256": self.sha256}


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_archive_path(name: str) -> str:
    path = pathlib.PurePosixPath(name)
    parts = path.parts
    if not parts:
        return ""
    first = parts[0]
    if first == "package" or first.startswith("agent-learning-compounder-"):
        parts = parts[1:]
    return pathlib.PurePosixPath(*parts).as_posix() if parts else ""


def inspect_tree(root: pathlib.Path) -> list[FileEntry]:
    entries: list[FileEntry] = []
    for path in sorted(pathlib.Path(root).rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        entries.append(FileEntry(relative, path.stat().st_size, sha256_file(path)))
    return entries


def extract_tarball(archive: pathlib.Path, destination: pathlib.Path) -> pathlib.Path:
    with tarfile.open(archive, "r:*") as tar:
        tar.extractall(destination)
    roots = [path for path in destination.iterdir() if path.is_dir()]
    if len(roots) != 1:
        raise ValueError(f"expected one extracted root in {destination}, found {len(roots)}")
    return roots[0]


def extract_zip(archive: pathlib.Path, destination: pathlib.Path) -> pathlib.Path:
    with zipfile.ZipFile(archive) as zip_file:
        zip_file.extractall(destination)
    roots = [path for path in destination.iterdir() if path.is_dir()]
    if len(roots) != 1:
        raise ValueError(f"expected one extracted root in {destination}, found {len(roots)}")
    return roots[0]


def find_excluded_paths(paths: Iterable[str]) -> list[str]:
    excluded: list[str] = []
    for raw in paths:
        normalized = normalize_archive_path(raw)
        if normalized and release_layout.is_sanitizer_excluded(normalized):
            excluded.append(normalized)
    return sorted(set(excluded))


def validate_no_excluded(entries: Iterable[FileEntry]) -> list[str]:
    return find_excluded_paths(entry.path for entry in entries)


def git_commit(repo_root: pathlib.Path, source_ref: str = "HEAD") -> str:
    result = subprocess.run(
        ["git", "rev-parse", source_ref],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return result.stdout.strip()


def _dirty_status(repo_root: pathlib.Path) -> list[tuple[str, str]]:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--ignored=matching", "--untracked-files=all"],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    rows: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        status = line[:2]
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        rows.append((status, path))
    return rows


def _under_root(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def is_package_affecting_path(path: str) -> bool:
    if release_layout.is_release_excluded(path):
        return False
    if path in release_layout.SHIPPED_TOP_LEVEL_FILES:
        return True
    if path in {"package.json", "LICENSE", ".claude-plugin/marketplace.json"}:
        return True
    if any(_under_root(path, root) for root in release_layout.SHIPPED_TOP_LEVEL_DIRS):
        return True
    if _under_root(path, "agent-learning-compounder"):
        return True
    if any(_under_root(path, item.rstrip("/")) for item in release_layout.NPM_FILES if item.endswith("/")):
        return True
    return path in {item for item in release_layout.NPM_FILES if not item.endswith("/")}


def package_affecting_dirty_paths(repo_root: pathlib.Path) -> list[str]:
    dirty = []
    for status, path in _dirty_status(repo_root):
        if status == "!!" and not is_package_affecting_path(path):
            continue
        if is_package_affecting_path(path):
            dirty.append(f"{status} {path}")
    return dirty


def npm_pack_entries(repo_root: pathlib.Path, version: str) -> list[FileEntry]:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        env = os.environ.copy()
        env.setdefault("npm_config_cache", str(tmp_path / "npm-cache"))
        result = subprocess.run(
            ["npm", "pack", "--pack-destination", str(tmp_path)],
            cwd=repo_root,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stdout + result.stderr)
        tgz_files = sorted(tmp_path.glob("*.tgz"))
        if len(tgz_files) != 1:
            raise RuntimeError(f"expected one npm pack tgz, found {len(tgz_files)}")
        extract_root = tmp_path / "npm"
        extract_root.mkdir()
        with tarfile.open(tgz_files[0], "r:gz") as tar:
            tar.extractall(extract_root)
        package_root = extract_root / "package"
        entries = inspect_tree(package_root)
        for entry in entries:
            if entry.path.startswith("package/"):
                raise RuntimeError(f"unexpected package prefix after extraction: {entry.path}")
        return entries


def package_difference_reasons(
    archive_entries: Iterable[FileEntry],
    npm_entries: Iterable[FileEntry],
) -> dict[str, list[dict[str, str]]]:
    archive_paths = {entry.path for entry in archive_entries}
    npm_paths = {entry.path for entry in npm_entries}
    archive_only = [
        {"path": path, "reason": "archive ships source/docs beyond the npm entrypoint set"}
        for path in sorted(archive_paths - npm_paths)
    ]
    npm_only = [
        {"path": path, "reason": "npm-only package metadata or marketplace surface"}
        for path in sorted(npm_paths - archive_paths)
    ]
    return {"archive_only": archive_only, "npm_only": npm_only}


def build_manifest(
    *,
    version: str,
    source_commit: str,
    archive_root: str,
    tar_entries: list[FileEntry],
    zip_entries: list[FileEntry],
    npm_entries: list[FileEntry],
) -> dict[str, object]:
    return {
        "package": release_metadata.PROJECT_NAME,
        "version": version,
        "source_commit": source_commit,
        "archive_root": archive_root,
        "archive": {"files": [entry.to_dict() for entry in sorted(tar_entries, key=lambda item: item.path)]},
        "zip": {"files": [entry.to_dict() for entry in sorted(zip_entries, key=lambda item: item.path)]},
        "npm": {"files": [entry.to_dict() for entry in sorted(npm_entries, key=lambda item: item.path)]},
        "differences": package_difference_reasons(tar_entries, npm_entries),
    }


def write_manifest(dist_dir: pathlib.Path, version: str, source_ref: str = "HEAD") -> pathlib.Path:
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    source_commit = git_commit(repo_root, source_ref)
    name = f"agent-learning-compounder-{version}"
    tar_path = dist_dir / f"{name}.tar.gz"
    zip_path = dist_dir / f"{name}.zip"
    if not tar_path.exists() or not zip_path.exists():
        raise FileNotFoundError(f"missing release archives for {version}")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        tar_root = extract_tarball(tar_path, tmp_path / "tar")
        zip_root = extract_zip(zip_path, tmp_path / "zip")
        tar_entries = inspect_tree(tar_root)
        zip_entries = inspect_tree(zip_root)
        npm_entries = npm_pack_entries(repo_root, version)
    errors = []
    for label, entries in (("tar", tar_entries), ("zip", zip_entries), ("npm", npm_entries)):
        leaked = validate_no_excluded(entries)
        if leaked:
            errors.append(f"{label} contains excluded paths: {', '.join(leaked)}")
    if errors:
        raise RuntimeError("\n".join(errors))
    manifest = build_manifest(
        version=version,
        source_commit=source_commit,
        archive_root=name,
        tar_entries=tar_entries,
        zip_entries=zip_entries,
        npm_entries=npm_entries,
    )
    out = dist_dir / f"{name}.release-manifest.json"
    out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def _cmd_check_source_clean(args: argparse.Namespace) -> int:
    dirty = package_affecting_dirty_paths(pathlib.Path(args.repo_root))
    if not dirty:
        return 0
    print("package-affecting source changes present:", file=sys.stderr)
    for item in dirty:
        print(f"  {item}", file=sys.stderr)
    print("commit these changes or set ALC_ALLOW_DIRTY_RELEASE=1 for a non-publishable local experiment", file=sys.stderr)
    return 1


def _cmd_write(args: argparse.Namespace) -> int:
    out = write_manifest(pathlib.Path(args.dist), args.version, args.source_ref)
    print(out)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    clean = sub.add_parser("check-source-clean")
    clean.add_argument("--repo-root", required=True)
    clean.set_defaults(func=_cmd_check_source_clean)

    write = sub.add_parser("write")
    write.add_argument("--dist", required=True)
    write.add_argument("--version", required=True)
    write.add_argument("--source-ref", default="HEAD")
    write.set_defaults(func=_cmd_write)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
