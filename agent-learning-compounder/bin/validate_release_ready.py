#!/usr/bin/env python3
"""End-to-end local release readiness gate."""

from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
import tempfile

import docs_freshness
import release_manifest
import release_metadata


ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent


def _run(command: list[str], *, cwd: pathlib.Path = REPO_ROOT) -> None:
    result = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command)}\n{result.stdout}{result.stderr}"
        )


def _assert_same(entries_a: list[release_manifest.FileEntry], entries_b: list[release_manifest.FileEntry]) -> None:
    left = {entry.path: entry.sha256 for entry in entries_a}
    right = {entry.path: entry.sha256 for entry in entries_b}
    if left != right:
        missing = sorted(set(left) - set(right))
        extra = sorted(set(right) - set(left))
        changed = sorted(path for path in set(left) & set(right) if left[path] != right[path])
        raise RuntimeError(f"tar/zip inventories differ: missing={missing[:10]} extra={extra[:10]} changed={changed[:10]}")


def _assert_current_sums(version: str) -> None:
    sums = REPO_ROOT / "dist" / "SHA256SUMS"
    if not sums.exists():
        raise RuntimeError("dist/SHA256SUMS missing")
    allowed = {
        f"agent-learning-compounder-{version}.tar.gz",
        f"agent-learning-compounder-{version}.zip",
    }
    stale = []
    for line in sums.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 2 and pathlib.PurePosixPath(parts[-1]).name not in allowed:
            stale.append(parts[-1])
    if stale:
        raise RuntimeError("SHA256SUMS contains stale artifacts: " + ", ".join(stale))


def validate(version: str, source_ref: str) -> pathlib.Path:
    release_manifest.release_metadata = release_metadata
    _run(["python3", str(ROOT / "bin" / "validate_artifacts"), "--check-manifest-merge"], cwd=ROOT)
    _run([str(REPO_ROOT / "scripts" / "build_release.sh"), "--version", version, "--source-ref", source_ref])

    name = f"agent-learning-compounder-{version}"
    tar_path = REPO_ROOT / "dist" / f"{name}.tar.gz"
    zip_path = REPO_ROOT / "dist" / f"{name}.zip"
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        tar_root = release_manifest.extract_tarball(tar_path, tmp_path / "tar")
        zip_root = release_manifest.extract_zip(zip_path, tmp_path / "zip")
        tar_entries = release_manifest.inspect_tree(tar_root)
        zip_entries = release_manifest.inspect_tree(zip_root)
        npm_entries = release_manifest.npm_pack_entries(REPO_ROOT, version)

        for label, entries in (("tar", tar_entries), ("zip", zip_entries), ("npm", npm_entries)):
            leaked = release_manifest.validate_no_excluded(entries)
            if leaked:
                raise RuntimeError(f"{label} contains excluded paths: {', '.join(leaked)}")

        _assert_same(tar_entries, zip_entries)

        release_findings = docs_freshness.scan_release_scope(tar_root, enforce_test_counts=True)
        release_findings.extend(docs_freshness.scan_release_scope(zip_root, enforce_test_counts=True))
        if release_findings:
            raise RuntimeError("\n".join(finding.render() for finding in release_findings))

    source_findings = docs_freshness.scan_source_scope(enforce_test_counts=True)
    if source_findings:
        raise RuntimeError("\n".join(finding.render() for finding in source_findings))

    _assert_current_sums(version)
    manifest_path = release_manifest.write_manifest(REPO_ROOT / "dist", version, source_ref)
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default=release_metadata.RELEASE_METADATA.manifest_version)
    parser.add_argument("--source-ref", default="HEAD")
    args = parser.parse_args()
    try:
        manifest_path = validate(args.version, args.source_ref)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"release ready: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
