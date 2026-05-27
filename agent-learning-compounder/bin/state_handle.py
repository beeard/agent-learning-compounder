#!/usr/bin/env python3
"""Canonical state resolver for agent-learning.

`StateHandle` is the single source of truth for mapping a repo path to all
primary on-disk locations used by ALC.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import logging
import os
import pathlib
import re
import stat
from dataclasses import dataclass
from typing import Literal


logger = logging.getLogger(__name__)


ReadScope = Literal["user", "project", "both"]
_VALID_READ_SCOPES: frozenset[str] = frozenset({"user", "project", "both"})


@dataclass(frozen=True)
class UserScope:
    """Resolved user-scope state root and derived report directory."""

    root: pathlib.Path
    reports_dir: pathlib.Path
    tier: str


@dataclass(frozen=True)
class EventWriteTarget:
    """Resolved event write target with the audit label persisted on rows."""

    event_dir: pathlib.Path
    events_jsonl: pathlib.Path
    write_scope: str


def _slugify(value: str, fallback: str = "repo") -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-").lower()
    return slug or fallback


def _repo_id(repo: pathlib.Path) -> str:
    resolved = str(repo.expanduser().resolve())
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:12]
    return f"{_slugify(pathlib.Path(resolved).name)}-{digest}"


def _read_json_or_none(path: pathlib.Path) -> dict | None:
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _resolve_state_root(
    state_dir: str | pathlib.Path | None = None,
    personal: str | pathlib.Path | None = None,
    repo: str | pathlib.Path | None = None,
    user: str | pathlib.Path | None = None,
) -> tuple[pathlib.Path, str]:
    """Resolve `state_root` using the documented precedence chain.

    Resolution order (first match wins):
      1. explicit ``state_dir`` argument (`--state-dir`)
      2. ``AGENT_LEARNING_STATE_DIR`` env
      3. explicit ``user`` argument (`--user`; alias: ``personal``/`--personal`,
         deprecated and still honoured for one minor release)
      4. ``AGENT_LEARNING_USER`` env (compat: ``AGENT_LEARNING_PERSONAL``)
      5. ``repo/.agent-learning`` when a repo path is supplied
      6. ``$XDG_STATE_HOME/agent-learning``
      7. ``~/.local/state/agent-learning``

    See ARCHITECTURE.md § 4 ("Scope model") for the user-vs-project
    distinction this resolver enforces.
    """
    if state_dir:
        return pathlib.Path(state_dir).expanduser().resolve(), "legacy_explicit_state_dir"

    env_state = os.environ.get("AGENT_LEARNING_STATE_DIR")
    if env_state:
        return pathlib.Path(env_state).expanduser().resolve(), "legacy_env_state_dir"

    user_arg = user if user is not None else personal
    if user_arg:
        return pathlib.Path(user_arg).expanduser().resolve() / "reports" / "agent-learning", "legacy_personal"

    env_user = os.environ.get("AGENT_LEARNING_USER") or os.environ.get("AGENT_LEARNING_PERSONAL")
    if env_user:
        return pathlib.Path(env_user).expanduser().resolve() / "reports" / "agent-learning", "legacy_env_user"

    if repo is not None:
        return pathlib.Path(repo).expanduser().resolve() / ".agent-learning", "legacy_repo_root"

    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return pathlib.Path(xdg).expanduser().resolve() / "agent-learning", "legacy_xdg"

    return pathlib.Path.home() / ".local" / "state" / "agent-learning", "legacy_home"


def _resolve_user_scope(user_root: str | pathlib.Path | None = None) -> UserScope:
    if user_root is not None:
        root = pathlib.Path(user_root).expanduser().resolve()
        tier = "explicit_user_root"
    elif env_user := os.environ.get("AGENT_LEARNING_USER"):
        root = pathlib.Path(env_user).expanduser().resolve()
        tier = "env_user"
    elif env_personal := os.environ.get("AGENT_LEARNING_PERSONAL"):
        root = pathlib.Path(env_personal).expanduser().resolve()
        tier = "legacy_env_personal"
    else:
        root = (pathlib.Path.home() / ".agent-learning").resolve()
        tier = "default_user_home"
    return UserScope(root=root, reports_dir=root / "reports" / "agent-learning", tier=tier)


def _event_write_target(
    *,
    repo: str | pathlib.Path | None = None,
    state: "StateHandle | None" = None,
    state_root: str | pathlib.Path | None = None,
    background_root: str | pathlib.Path | None = None,
) -> EventWriteTarget:
    intents = [
        name
        for name, value in (
            ("state", state),
            ("repo", repo),
            ("state_root", state_root),
            ("background_root", background_root),
        )
        if value is not None
    ]
    if len(intents) > 1:
        raise ValueError(f"ambiguous event write target: pass only one of {', '.join(intents)}")

    if state is not None:
        event_dir = state.events_jsonl.parent
        return EventWriteTarget(event_dir=event_dir, events_jsonl=state.events_jsonl, write_scope="project_state_handle")
    if repo is not None:
        handle = StateHandle.for_repo(pathlib.Path(repo))
        return EventWriteTarget(event_dir=handle.repo_state_dir, events_jsonl=handle.events_jsonl, write_scope="project_repo")
    if background_root is not None:
        event_dir = pathlib.Path(background_root).expanduser().resolve()
        return EventWriteTarget(
            event_dir=event_dir,
            events_jsonl=event_dir / "events.jsonl",
            write_scope="background_explicit_root",
        )
    if state_root is not None:
        event_dir = pathlib.Path(state_root).expanduser().resolve()
        return EventWriteTarget(
            event_dir=event_dir,
            events_jsonl=event_dir / "events.jsonl",
            write_scope="legacy_state_root",
        )

    state_dir, tier = _resolve_state_root()
    event_dir = state_dir.expanduser().resolve()
    label = "legacy_state_dir_fallback" if tier in {"legacy_env_state_dir", "legacy_home", "legacy_xdg"} else tier
    return EventWriteTarget(event_dir=event_dir, events_jsonl=event_dir / "events.jsonl", write_scope=label)


def _resolve_repo_state_dir(
    repo: str | pathlib.Path,
    state_dir: str | pathlib.Path | None = None,
    personal: str | pathlib.Path | None = None,
    user: str | pathlib.Path | None = None,
) -> tuple[pathlib.Path, str]:
    resolved, tier = _resolve_state_root(state_dir, personal, repo, user)
    return resolved / "repos" / _repo_id(pathlib.Path(repo)), tier


def _load_state_root_from_repo_config(repo: pathlib.Path) -> pathlib.Path | None:
    payload = _read_json_or_none(repo / ".agent-learning.json")
    if not payload:
        return None
    state_dir = payload.get("state_dir")
    if not isinstance(state_dir, str) or not state_dir.strip():
        return None

    return pathlib.Path(state_dir).expanduser().resolve()


@dataclass(frozen=True)
class StateHandle:
    """Canonical resolver for a repo-local state surface."""

    repo: pathlib.Path
    state_root: pathlib.Path
    repo_state_dir: pathlib.Path
    reports_dir: pathlib.Path
    dashboard_dir: pathlib.Path
    alc_agents_dirs: dict[Literal["dev", "test", "evals", "personal"], pathlib.Path]
    alc_apply_log: pathlib.Path
    outcomes_json: pathlib.Path
    events_jsonl: pathlib.Path
    events_sqlite: pathlib.Path

    @staticmethod
    def repo_id(repo: pathlib.Path) -> str:
        return _repo_id(repo)

    @staticmethod
    def resolve_state_root(
        state_dir: str | pathlib.Path | None = None,
        personal: str | pathlib.Path | None = None,
        repo: str | pathlib.Path | None = None,
        user: str | pathlib.Path | None = None,
    ) -> tuple[pathlib.Path, str]:
        return _resolve_state_root(state_dir, personal, repo, user)

    @staticmethod
    def resolve_repo_state_dir(
        repo: str | pathlib.Path,
        state_dir: str | pathlib.Path | None = None,
        personal: str | pathlib.Path | None = None,
        user: str | pathlib.Path | None = None,
    ) -> tuple[pathlib.Path, str]:
        return _resolve_repo_state_dir(repo, state_dir, personal, user)

    @classmethod
    def for_user(cls, user_root: str | pathlib.Path | None = None) -> pathlib.Path:
        """Return the user-scope state-root path (cross-repo learning).

        Resolution: explicit ``user_root`` → ``AGENT_LEARNING_USER`` env →
        ``AGENT_LEARNING_PERSONAL`` env (compat) → ``~/.agent-learning``.

        Returns a bare path (not a StateHandle dataclass) because user-scope
        is single-rooted by design — no per-repo subdirectory.
        """
        return _resolve_user_scope(user_root).root

    @staticmethod
    def user_scope(user_root: str | pathlib.Path | None = None) -> UserScope:
        return _resolve_user_scope(user_root)

    @staticmethod
    def user_reports_dir(user_root: str | pathlib.Path | None = None) -> pathlib.Path:
        return _resolve_user_scope(user_root).reports_dir

    @staticmethod
    def validate_read_scope(scope: str) -> ReadScope:
        if scope not in _VALID_READ_SCOPES:
            raise ValueError(f"scope must be one of {sorted(_VALID_READ_SCOPES)}, got {scope!r}")
        return scope  # type: ignore[return-value]

    @staticmethod
    def event_write_target(
        *,
        repo: str | pathlib.Path | None = None,
        state: "StateHandle | None" = None,
        state_root: str | pathlib.Path | None = None,
        background_root: str | pathlib.Path | None = None,
    ) -> EventWriteTarget:
        return _event_write_target(repo=repo, state=state, state_root=state_root, background_root=background_root)

    @classmethod
    def for_project(cls, repo_path: pathlib.Path) -> "StateHandle":
        """Project-scope state surface for a specific repo (canonical name).

        Equivalent to :meth:`for_repo`; the latter is kept as a deprecated
        alias for one minor release.
        """
        return cls.for_repo(repo_path)

    @classmethod
    def project_state(
        cls,
        repo_path: str | pathlib.Path,
        *,
        state_dir: str | pathlib.Path | None = None,
    ) -> "StateHandle":
        """Return the project-scope StateHandle for repo plus optional root."""
        return cls.for_repo(pathlib.Path(repo_path), state_dir=state_dir)

    @classmethod
    def for_repo(
        cls,
        repo_path: pathlib.Path,
        *,
        state_dir: str | pathlib.Path | None = None,
    ) -> "StateHandle":
        repo = pathlib.Path(repo_path).expanduser().resolve()

        if state_dir is not None:
            state_root = pathlib.Path(state_dir).expanduser().resolve()
            tier = "explicit_state_dir"
        else:
            state_root = _load_state_root_from_repo_config(repo)
            tier = "repo_config_state_dir" if state_root is not None else None

            if state_root is None:
                state_root, tier = _resolve_state_root(repo=repo)

        repo_state = state_root / "repos" / cls.repo_id(repo)
        reports_dir = repo_state / "reports"
        dashboard_dir = repo_state / "dashboard"
        alc_agents_root = repo_state / "alc-agents"

        logger.info("state_handle_state_root_resolved", extra={"repo": str(repo), "tier": tier})

        return cls(
            repo=repo,
            state_root=state_root,
            repo_state_dir=repo_state,
            reports_dir=reports_dir,
            dashboard_dir=dashboard_dir,
            alc_agents_dirs={
                "dev": alc_agents_root / "dev",
                "test": alc_agents_root / "test",
                "evals": alc_agents_root / "evals",
                "personal": state_root / "alc-agents" / "personal",
            },
            alc_apply_log=repo_state / "apply-log.jsonl",
            outcomes_json=repo_state / "outcomes.json",
            events_jsonl=repo_state / "events.jsonl",
            events_sqlite=repo_state / "events.sqlite",
        )


def dashboard_url(repo: str | pathlib.Path) -> str:
    handle = StateHandle.for_repo(pathlib.Path(repo))
    marker = handle.dashboard_dir / "server.json"
    payload = _read_json_or_none(marker)
    if payload:
        url = payload.get("url")
        if isinstance(url, str) and url.startswith(("http://127.0.0.1:", "http://localhost:")):
            return url
    index = handle.dashboard_dir / "index.html"
    return index.resolve().as_uri() if index.exists() else handle.dashboard_dir.resolve().as_uri()


# --- module-level helpers ----------------------------------------------------
# Public re-exports of StateHandle's static methods so callers can write
# ``from state_handle import repo_state_dir`` without binding to the class.


def slugify(value: str, fallback: str = "repo") -> str:
    return _slugify(value, fallback)


def repo_id(repo: pathlib.Path) -> str:
    return _repo_id(repo)


def resolve_state_dir(
    state_dir: str | pathlib.Path | None = None,
    personal: str | pathlib.Path | None = None,
    repo: str | pathlib.Path | None = None,
    user: str | pathlib.Path | None = None,
) -> pathlib.Path:
    """Resolve the agent-learning state root using the documented precedence
    chain. See :func:`_resolve_state_root` for the tiers.

    The precedence is part of the public contract; tests in
    ``fixtures/tests/test_state_paths_precedence.py`` lock it in place.
    """
    return _resolve_state_root(state_dir, personal, repo, user)[0]


def repo_state_dir(
    repo: str | pathlib.Path,
    state_dir: str | pathlib.Path | None = None,
    personal: str | pathlib.Path | None = None,
    user: str | pathlib.Path | None = None,
) -> pathlib.Path:
    resolved, _ = _resolve_repo_state_dir(repo, state_dir, personal, user)
    return resolved


def validate_read_scope(scope: str) -> ReadScope:
    return StateHandle.validate_read_scope(scope)


def user_scope(user_root: str | pathlib.Path | None = None) -> UserScope:
    return StateHandle.user_scope(user_root)


def user_reports_dir(user_root: str | pathlib.Path | None = None) -> pathlib.Path:
    return StateHandle.user_reports_dir(user_root)


def event_write_target(
    *,
    repo: str | pathlib.Path | None = None,
    state: StateHandle | None = None,
    state_root: str | pathlib.Path | None = None,
    background_root: str | pathlib.Path | None = None,
) -> EventWriteTarget:
    return StateHandle.event_write_target(
        repo=repo,
        state=state,
        state_root=state_root,
        background_root=background_root,
    )


def project_state(
    repo: str | pathlib.Path,
    *,
    state_dir: str | pathlib.Path | None = None,
) -> StateHandle:
    return StateHandle.project_state(repo, state_dir=state_dir)


# --- durable-write primitives ------------------------------------------------
#
# Why a sidecar lockfile, not flock on the data file itself: the data file's
# inode lock does not survive its own os.replace. After one writer's atomic
# swap, a concurrent writer that opened the original inode before the swap
# still holds a lock on that orphaned inode and its own os.replace silently
# clobbers the first writer's change. The sidecar `<path>.lock` is never
# renamed, so its lock remains a valid mutex across replaces.
#
# Why pid-tagged tmp filenames: a shared `<path>.tmp` would be truncated by a
# concurrent writer's open("w"), and the loser's os.replace would then
# FileNotFoundError on a tmp the winner already consumed.


def _assert_regular_or_absent(path: pathlib.Path) -> None:
    """Reject targets that already exist as a symlink or non-regular file.
    Every atomic_* primitive enforces this check under its own lock, closing
    the TOCTOU where a caller checks once before the lock is acquired."""
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    if stat.S_ISLNK(mode):
        raise ValueError(f"refusing to write through symlink: {path}")
    if not stat.S_ISREG(mode):
        raise ValueError(f"refusing to write to non-regular file: {path}")


def _write_tmp_then_replace(path: pathlib.Path, text: str, mode: int) -> None:
    tmp = path.parent / f"{path.name}.{os.getpid()}.tmp"
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def atomic_write_text(path: pathlib.Path, text: str, *, mode: int = 0o644) -> None:
    """Write ``text`` to ``path`` atomically, serialized against other writers
    via ``<path>.lock``. Crash-atomic: a SIGKILL between open and os.replace
    leaves the file at its prior content -- never truncated.

    Refuses to write through a symlink or to a non-regular file at the
    destination, checked under the lock so a symlink swap between an
    earlier caller-side check and the actual write cannot slip through.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.parent / f"{path.name}.lock"
    lock_fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        _assert_regular_or_absent(path)
        _write_tmp_then_replace(path, text, mode)
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(lock_fd)


@contextlib.contextmanager
def atomic_rewrite(path: pathlib.Path, *, mode: int = 0o644):
    """Acquire the sidecar lock for ``path`` and yield ``(current_text,
    commit)``. The caller reads ``current_text``, computes the new content,
    and calls ``commit(new_text)`` to atomically replace the file. The lock
    is held across read+compute+commit, so concurrent writers serialize.

    Replaces the seek+truncate+write pattern that left the file empty on
    mid-write process death. Callers that decide not to write can simply
    not call ``commit`` -- the file is untouched on exit.

    Refuses to operate on a symlink or non-regular file at the destination
    (under the lock), closing the symlink-swap TOCTOU between an earlier
    caller-side validation and the read or write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.parent / f"{path.name}.lock"
    lock_fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        _assert_regular_or_absent(path)
        current = path.read_text(encoding="utf-8") if path.exists() else ""

        def commit(new_text: str) -> None:
            _write_tmp_then_replace(path, new_text, mode)

        yield current, commit
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(lock_fd)
