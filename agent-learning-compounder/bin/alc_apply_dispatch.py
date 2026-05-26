#!/usr/bin/env python3
"""Hermes-DSL executors for alc_apply."""

from __future__ import annotations

import base64
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import pathlib
import stat
import tempfile
import time
from typing import Any

try:
    from alc_apply_contracts import ApplyError, ApplyResult, DSL_TARGETS, Executor, RevertError, RevertResult
    from alc_query import get_apply_log
    from event_schema import EventV4
    from event_writer import write_event
    from scrub_secrets import scrub
    from state_handle import StateHandle
except ImportError:  # pragma: no cover
    from bin.alc_apply_contracts import ApplyError, ApplyResult, DSL_TARGETS, Executor, RevertError, RevertResult
    from bin.alc_query import get_apply_log
    from bin.event_schema import EventV4
    from bin.event_writer import write_event
    from bin.scrub_secrets import scrub
    from bin.state_handle import StateHandle


LOCK_TIMEOUT_S = 5.0


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _repo_relative(repo: pathlib.Path, target: str) -> pathlib.Path:
    raw = pathlib.Path(target).expanduser()
    return raw if raw.is_absolute() else repo / raw


def _root_paths(state: StateHandle, roots: list[str]) -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for root in roots:
        if root.startswith("<state>/alc-agents/"):
            for key in ("dev", "test", "evals"):
                out.append(state.alc_agents_dirs[key])
            continue
        if root == "<personal>/alc-agents/":
            out.append(state.alc_agents_dirs["personal"])
            continue
        path = pathlib.Path(root.replace("~", str(pathlib.Path.home()), 1)).expanduser()
        out.append(path if path.is_absolute() else state.repo / path)
    return [p.resolve() for p in out]


def _under(path: pathlib.Path, root: pathlib.Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _check_no_symlink(path: pathlib.Path) -> None:
    for node in [path, *path.parents]:
        try:
            mode = node.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise ApplyError(f"target path contains symlink: {node}")


def _read_bytes(path: pathlib.Path) -> bytes:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return b""


def _apply_op_to_bytes(op: dict[str, Any], current: bytes) -> bytes:
    action = str(op.get("action", ""))
    if action in {"create", "write_file"}:
        if "content_b64" in op:
            return base64.b64decode(str(op.get("content_b64") or ""))
        return str(op.get("content", "")).encode("utf-8")
    if action in {"patch", "edit"}:
        text = current.decode("utf-8")
        old = str(op.get("old_string", ""))
        new = str(op.get("new_string", ""))
        if old not in text:
            raise ApplyError("old_string not found in target")
        if text.count(old) != 1:
            raise ApplyError("old_string must match exactly once")
        return text.replace(old, new, 1).encode("utf-8")
    raise ApplyError(f"unsupported action: {action}")


@contextlib.contextmanager
def _event_state(state: StateHandle):
    previous = os.environ.get("AGENT_LEARNING_STATE_DIR")
    os.environ["AGENT_LEARNING_STATE_DIR"] = str(state.repo_state_dir)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("AGENT_LEARNING_STATE_DIR", None)
        else:
            os.environ["AGENT_LEARNING_STATE_DIR"] = previous


@contextlib.contextmanager
def _apply_lock(state: StateHandle):
    state.repo_state_dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(state.repo_state_dir / ".apply.lock"), os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.monotonic() + LOCK_TIMEOUT_S
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise ApplyError("timed out acquiring apply lock") from exc
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _atomic_write(path: pathlib.Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = pathlib.Path(tmp)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def _load_event_payload(state: StateHandle, event_id: str) -> dict[str, Any] | None:
    if not state.events_jsonl.exists():
        return None
    with state.events_jsonl.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("event_id") == event_id:
                return row.get("payload") if isinstance(row.get("payload"), dict) else {}
    return None


def _index_state(state: StateHandle) -> None:
    try:
        from index_events import run as index_events
    except ImportError:  # pragma: no cover
        from bin.index_events import run as index_events

    index_events(state.repo_state_dir)


class HermesExecutor(Executor):
    def __init__(self, state: StateHandle):
        self.state = state

    def _target(self, op: dict[str, Any]) -> tuple[pathlib.Path, bytes, bytes]:
        target_type = str(op.get("target_type", ""))
        if target_type not in DSL_TARGETS:
            raise ApplyError(f"unsupported target_type: {target_type}")
        spec = DSL_TARGETS[target_type]
        target = _repo_relative(self.state.repo, str(op.get("target", "")))
        _check_no_symlink(target)
        resolved = target.resolve()
        if not any(_under(resolved, root) for root in _root_paths(self.state, spec.allowed_roots)):
            raise ApplyError("target outside allowed_roots")

        current = _read_bytes(resolved)
        if len(current) > spec.max_size:
            raise ApplyError("target exceeds max_size")
        new = _apply_op_to_bytes(op, current)
        if len(new) > spec.max_size:
            raise ApplyError("new content exceeds max_size")
        expected = str(op.get("expected_target_sha256") or op.get("preflight", {}).get("expected_target_sha256") or "")
        if expected and expected != sha256_bytes(current):
            raise ApplyError("expected_target_sha256 mismatch")
        if spec.validator and not (str(op.get("action")) == "write_file" and not new):
            errors = spec.validator(new.decode("utf-8"))
            if errors:
                raise ApplyError("; ".join(errors))
        return resolved, current, new

    def _unreverted_apply(self, patch_id: str) -> dict[str, Any] | None:
        rows = get_apply_log(self.state, kind_filter=["patch_applied", "patch_reverted"])
        reverted = {r.get("parent_event_id") for r in rows if r.get("event") == "patch_reverted" and r.get("parent_event_id")}
        for row in rows:
            if row.get("event") != "patch_applied" or row.get("event_id") in reverted:
                continue
            payload = _load_event_payload(self.state, str(row.get("event_id")))
            if payload and payload.get("patch_id") == patch_id:
                return {**row, "payload": payload}
        return None

    def apply(self, op: dict[str, Any]) -> ApplyResult:
        patch_id = str(op.get("patch_id", "")).strip()
        if not patch_id:
            raise ApplyError("patch_id is required")
        if str(op.get("apply_strategy", "hermes_dsl")) == "copy_to_clipboard":
            raise ApplyError("copy_to_clipboard is not a Hermes-DSL op")
        if self._unreverted_apply(patch_id):
            raise ApplyError("patch already applied")

        # Early validation against current state (fails fast before grabbing the
        # lock); the authoritative read+transform happens INSIDE the lock to
        # close the TOCTOU window — file may change between these two reads.
        self._target(op)
        with _apply_lock(self.state):
            _index_state(self.state)
            if self._unreverted_apply(patch_id):
                raise ApplyError("patch already applied")
            target, current, new = self._target(op)
            expected = str(op.get("expected_target_sha256") or "")
            if expected and expected != sha256_bytes(current):
                raise ApplyError("expected_target_sha256 mismatch after lock")
            apply_ts = _now()
            scrubbed_original = scrub(current.decode("utf-8", errors="replace")).encode("utf-8")
            original_b64 = base64.b64encode(scrubbed_original).decode("ascii")
            event_id = EventV4.deterministic_id("operator", "patch_applied", f"{patch_id}:{apply_ts}")
            rel_target = str(target.relative_to(self.state.repo)) if _under(target, self.state.repo) else str(target.name)
            payload = {
                "patch_id": patch_id,
                "target": rel_target,
                "original_sha256": sha256_bytes(current),
                "original_bytes_b64": original_b64,
                "revert_op": {
                    "action": "write_file",
                    "target_type": op.get("target_type"),
                    "target": rel_target,
                    "content_b64": original_b64,
                },
                "apply_ts": apply_ts,
            }
            event = {
                "event_id": event_id,
                "event": "patch_applied",
                "schema_version": 4,
                "actor": {"kind": "operator", "name": "alc_apply"},
                "ts": apply_ts,
                "payload": payload,
            }
            with _event_state(self.state):
                write_event(event, source="apply", auto_id_fallback=False)
            _index_state(self.state)
            _atomic_write(target, new)
        return ApplyResult(True, patch_id, str(target), sha256_bytes(current), sha256_bytes(new), event_id)

    def revert(self, patch_id: str) -> RevertResult:
        applied = self._unreverted_apply(patch_id)
        if not applied:
            raise RevertError("no unreverted patch_applied event found")
        payload = applied["payload"]
        revert_op = payload.get("revert_op")
        if not isinstance(revert_op, dict):
            revert_op = {
                "action": "write_file",
                "target_type": "skill",
                "target": payload.get("target"),
                "content": base64.b64decode(str(payload.get("original_bytes_b64", ""))).decode("utf-8"),
            }
        op = dict(revert_op)
        op["patch_id"] = patch_id
        target, current, new = self._target(op)
        revert_ts = _now()
        event_id = EventV4.deterministic_id("operator", "patch_reverted", f"{patch_id}:{revert_ts}")
        event = {
            "event_id": event_id,
            "event": "patch_reverted",
            "schema_version": 4,
            "actor": {"kind": "operator", "name": "alc_apply"},
            "ts": revert_ts,
            "parent_event_id": applied.get("event_id"),
            "payload": {"patch_id": patch_id, "target": payload.get("target"), "reverted_event_id": applied.get("event_id")},
        }
        with _apply_lock(self.state):
            with _event_state(self.state):
                write_event(event, source="apply", auto_id_fallback=False)
            _atomic_write(target, new)
        return RevertResult(True, patch_id, str(target), sha256_bytes(current), sha256_bytes(new), event_id)
