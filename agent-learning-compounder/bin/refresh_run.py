#!/usr/bin/env python3
"""Refresh Run module boundary for warm and full ALC state refreshes."""

from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import pathlib
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Literal

import index_events
from build_repo_baseline import build as build_baseline
from collect_hook_event import assert_regular_file_destination
from evaluate_skill_impact import evaluate as evaluate_impact
from export_skill_context import write_context
from extract_skill_usage import build_usage, read_events
from map_active_skills import build_map
from replay_hook_events import replay_normalize
from state_handle import StateHandle, atomic_write_text, resolve_state_dir


RefreshProfile = Literal["warm", "full"]


@dataclass(frozen=True)
class RefreshContext:
    repo: pathlib.Path
    state: StateHandle
    state_dir: str | pathlib.Path | None = None
    personal: str | pathlib.Path | None = None

    @property
    def repo_state(self) -> pathlib.Path:
        return self.state.repo_state_dir

    @property
    def reports(self) -> pathlib.Path:
        return self.state.reports_dir


@dataclass
class StageResult:
    name: str
    counts: dict[str, int] = field(default_factory=dict)
    touched: list[pathlib.Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    status: str = "ok"

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "counts": dict(self.counts),
            "touched": [str(path) for path in self.touched],
            "warnings": list(self.warnings),
        }


_VALID_PROFILES = {"warm", "full"}


def _write_json(path: pathlib.Path, payload: dict[str, Any]) -> pathlib.Path:
    atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def _has_event_rows(path: pathlib.Path) -> bool:
    if not path.exists():
        return False
    return any(line.strip() for line in path.read_text(encoding="utf-8").splitlines())


def _emit_refresh_event(
    kind: str,
    repo: pathlib.Path,
    *,
    parent_event_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> str | None:
    try:
        from event_emit import event_emit as emit_background_event

        return emit_background_event(
            kind=kind,
            actor_name="refresh_run",
            actor_kind="background_agent",
            parent_event_id=parent_event_id,
            payload=payload,
            repo=repo,
        )
    except Exception:
        return None


def _read_replay_cursor(path: pathlib.Path) -> int:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if not isinstance(payload, dict):
        return 0
    offset = payload.get("offset")
    return offset if isinstance(offset, int) and offset >= 0 else 0


def _write_replay_cursor(path: pathlib.Path, offset: int, source_size: int) -> None:
    payload = {
        "offset": offset,
        "source_size": source_size,
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n", mode=0o600)


def _append_jsonl(path: pathlib.Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    assert_regular_file_destination(path, label="Events JSONL")
    lock_path = path.parent / ".events.lock"
    lock_fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        assert_regular_file_destination(path, label="Events JSONL")
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            with os.fdopen(fd, "a", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
    finally:
        os.close(lock_fd)


def _replay_hook_rows(
    hook_events: pathlib.Path,
    events_jsonl: pathlib.Path,
    cursor_path: pathlib.Path,
) -> StageResult:
    stage = StageResult(name="event_ingestion")
    if not hook_events.exists() or hook_events.stat().st_size == 0:
        return stage
    if not hook_events.is_file():
        stage.status = "warning"
        stage.warnings.append(f"hook event log is not a regular file: {hook_events}")
        return stage

    source_size = hook_events.stat().st_size
    start_offset = _read_replay_cursor(cursor_path)
    if source_size < start_offset:
        start_offset = 0

    rows: list[dict[str, Any]] = []
    skipped = 0
    cursor = start_offset
    with hook_events.open("rb") as handle:
        handle.seek(start_offset)
        for line in handle:
            cursor = handle.tell()
            text = line.strip()
            if not text:
                continue
            try:
                raw = json.loads(text.decode("utf-8"))
                if not isinstance(raw, dict):
                    raise ValueError("hook row is not a JSON object")
                rows.append(replay_normalize(raw))
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
                skipped += 1
                print(f"warn.refresh_run_hook_replay_skipped offset={cursor} reason={exc!s}", file=sys.stderr)

    _append_jsonl(events_jsonl, rows)
    _write_replay_cursor(cursor_path, cursor, source_size)
    stage.counts["hook_rows_appended"] = len(rows)
    stage.counts["hook_rows_skipped"] = skipped
    if rows:
        stage.touched.append(events_jsonl)
    stage.touched.append(cursor_path)
    if skipped:
        stage.status = "warning"
        stage.warnings.append(f"skipped {skipped} malformed hook row(s)")
    return stage


def _index_events(ctx: RefreshContext, stage: StageResult, *, fatal: bool) -> None:
    try:
        indexed_events = index_events.run(ctx.repo_state)
    except Exception as exc:  # noqa: BLE001
        if fatal:
            raise
        stage.status = "warning"
        stage.warnings.append(f"index_events skipped: {exc}")
        stage.counts["events_indexed"] = 0
        print(f"refresh: index_events skipped: {exc}", file=sys.stderr)
        return
    stage.counts["events_indexed"] = indexed_events
    stage.touched.extend(
        path
        for path in (ctx.state.events_jsonl, ctx.state.events_sqlite, ctx.repo_state / "events.sqlite.cursor")
        if path.exists()
    )


def _event_ingestion_stage(
    ctx: RefreshContext,
    *,
    skip_replay: bool = False,
    fatal_index_errors: bool = False,
) -> StageResult:
    hook_events = ctx.repo_state / "hook-events.jsonl"
    if skip_replay:
        stage = StageResult(name="event_ingestion")
    else:
        stage = _replay_hook_rows(
            hook_events,
            ctx.state.events_jsonl,
            ctx.repo_state / "hook-events.jsonl.replay.cursor.json",
        )
    _index_events(ctx, stage, fatal=fatal_index_errors)
    return stage


def _runtime_from_config(ctx: RefreshContext) -> str:
    runtime = "auto"
    try:
        state_root = resolve_state_dir(ctx.state_dir, ctx.personal, ctx.repo)
        config_path = state_root / "config.json"
        if config_path.exists():
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(cfg, dict) and isinstance(cfg.get("runtime"), str):
                runtime = cfg["runtime"]
    except (OSError, json.JSONDecodeError):
        runtime = "auto"
    return runtime


def _baseline_skill_export_stage(
    ctx: RefreshContext,
    *,
    events: pathlib.Path | None,
) -> tuple[StageResult, dict[str, Any]]:
    import refresh_learning_state as legacy

    runtime = _runtime_from_config(ctx)
    baseline = build_baseline(ctx.repo, runtime=runtime)
    skill_map = build_map(ctx.repo, runtime=runtime)
    event_log = events or ctx.repo_state / "hook-events.jsonl"
    event_log_present = _has_event_rows(event_log)
    if event_log_present:
        usage = build_usage(read_events(event_log), skill_map)
        impact = evaluate_impact(usage)
    else:
        usage = {}
        impact = {}
        print(
            "refresh: hook-events.jsonl is empty; skill-context will be empty",
            file=sys.stderr,
        )

    touched = [
        _write_json(ctx.repo_state / "baseline.json", baseline),
        _write_json(ctx.repo_state / "skill-map.json", skill_map),
        _write_json(ctx.repo_state / "skill-usage.json", usage),
        _write_json(ctx.repo_state / "skill-impact.json", impact),
        write_context(ctx.reports / "latest-skill-context.md", skill_map, usage, impact),
    ]
    stage = StageResult(
        name="baseline_skill_export",
        counts={
            "baseline_items": len(baseline) if isinstance(baseline, dict) else 0,
            "skills": len(skill_map.get("skills", [])) if isinstance(skill_map, dict) else 0,
        },
        touched=touched,
    )
    return stage, {
        "event_log": event_log,
        "event_log_present": event_log_present,
        "impact": impact,
        "legacy": legacy,
    }


def _queue_stage(
    ctx: RefreshContext,
    *,
    impact: dict[str, Any],
    event_log: pathlib.Path,
    queue: pathlib.Path | None,
    corpus: pathlib.Path | None,
    legacy: Any,
) -> StageResult:
    queue_path = queue or ctx.repo_state / "improvement-queue.jsonl"
    queue_stats = legacy.queue_candidate_adjustments(queue_path, impact)
    queue_path.touch(exist_ok=True)
    dedup_removed = legacy._post_dedup(queue_path)
    inherited_map = legacy._inherited_gates(ctx.reports / "latest-approved-gates.md")
    retirement_count, demote_count = legacy._queue_retirement_candidates(
        queue_path,
        event_log,
        inherited=inherited_map,
    )
    corpus_path = corpus or ctx.repo_state / "session-corpus.txt"
    domain_count = legacy._queue_domain_rule_candidates(queue_path, corpus_path)
    if retirement_count or demote_count or domain_count:
        dedup_removed += legacy._post_dedup(queue_path)

    queued = queue_stats["queued"]
    suppressed = queue_stats["suppressed_needs_review"]
    suppressed_redacted = queue_stats["suppressed_redacted"]
    if suppressed:
        print(f"refresh: suppressed {suppressed} needs_review rows", file=sys.stderr)
    if suppressed_redacted:
        print(
            f"refresh: suppressed {suppressed_redacted} rows containing secret-like content",
            file=sys.stderr,
        )
    if dedup_removed:
        print(f"refresh: dedup_removed={dedup_removed} near-duplicate rows", file=sys.stderr)
    if retirement_count:
        print(
            f"refresh: queued {retirement_count} gate_retirement_candidate row(s)",
            file=sys.stderr,
        )
    if demote_count:
        print(
            f"refresh: queued {demote_count} inherited_gate_demote_candidate row(s)",
            file=sys.stderr,
        )
    if domain_count:
        print(
            f"refresh: queued {domain_count} domain_rule_candidate row(s)",
            file=sys.stderr,
        )

    return StageResult(
        name="queue",
        counts={
            "queued_candidates": queued,
            "suppressed_needs_review": suppressed,
            "suppressed_redacted": suppressed_redacted,
            "dedup_removed": dedup_removed,
            "retirement_candidates_queued": retirement_count,
            "inherited_demote_candidates_queued": demote_count,
            "domain_rule_candidates_queued": domain_count,
        },
        touched=[queue_path],
    )


def _result_payload(
    ctx: RefreshContext,
    *,
    profile: RefreshProfile,
    stages: list[StageResult],
    event_log: pathlib.Path | None = None,
    event_log_present: bool | None = None,
) -> dict[str, Any]:
    counts: dict[str, int] = {}
    touched: list[pathlib.Path] = []
    for stage in stages:
        counts.update(stage.counts)
        touched.extend(stage.touched)

    event_log = event_log or ctx.repo_state / "hook-events.jsonl"
    payload: dict[str, Any] = {
        "profile": profile,
        "repo": str(ctx.repo),
        "repo_state_dir": str(ctx.repo_state),
        "event_log": str(event_log),
        "event_log_present": _has_event_rows(event_log) if event_log_present is None else event_log_present,
        "events_indexed": counts.get("events_indexed", 0),
        "hook_rows_appended": counts.get("hook_rows_appended", 0),
        "hook_rows_skipped": counts.get("hook_rows_skipped", 0),
        "queued_candidates": counts.get("queued_candidates", 0),
        "suppressed_needs_review": counts.get("suppressed_needs_review", 0),
        "suppressed_redacted": counts.get("suppressed_redacted", 0),
        "dedup_removed": counts.get("dedup_removed", 0),
        "retirement_candidates_queued": counts.get("retirement_candidates_queued", 0),
        "inherited_demote_candidates_queued": counts.get("inherited_demote_candidates_queued", 0),
        "domain_rule_candidates_queued": counts.get("domain_rule_candidates_queued", 0),
        "touched": [str(path) for path in dict.fromkeys(touched)],
        "stages": [stage.as_dict() for stage in stages],
    }
    return payload


def _context(
    repo: pathlib.Path,
    *,
    state_dir: str | pathlib.Path | None = None,
    personal: str | pathlib.Path | None = None,
) -> RefreshContext:
    resolved = pathlib.Path(repo).expanduser().resolve()
    state = StateHandle.project_state(resolved, state_dir=state_dir)
    return RefreshContext(repo=resolved, state=state, state_dir=state_dir, personal=personal)


def _locked_run(ctx: RefreshContext, fn) -> dict[str, Any]:
    ctx.repo_state.mkdir(parents=True, exist_ok=True)
    ctx.reports.mkdir(parents=True, exist_ok=True)
    refresh_lock_path = ctx.repo_state / ".refresh.lock"
    refresh_lock_fd = os.open(str(refresh_lock_path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(refresh_lock_fd, fcntl.LOCK_EX)
        try:
            return fn()
        finally:
            try:
                fcntl.flock(refresh_lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
    finally:
        os.close(refresh_lock_fd)


def run(
    repo: pathlib.Path,
    *,
    profile: str,
    state_dir: str | pathlib.Path | None = None,
    personal: str | pathlib.Path | None = None,
    events: pathlib.Path | None = None,
    queue: pathlib.Path | None = None,
    corpus: pathlib.Path | None = None,
    skip_replay: bool = False,
) -> dict[str, Any]:
    if profile not in _VALID_PROFILES:
        raise ValueError(f"profile must be one of {sorted(_VALID_PROFILES)}, got {profile!r}")
    if personal is not None:
        # Preserve the legacy repo_state_dir(..., personal=...) behavior for
        # callers still using --personal; StateHandle itself intentionally
        # models the new project-state root.
        ctx_repo = pathlib.Path(repo).expanduser().resolve()
        state_root = resolve_state_dir(state_dir, personal, ctx_repo)
        ctx = _context(ctx_repo, state_dir=state_root)
    else:
        ctx = _context(repo, state_dir=state_dir)

    start_event_id = _emit_refresh_event("refresh_start", ctx.repo) if profile == "full" else None
    started_at = time.time()

    def execute() -> dict[str, Any]:
        ingestion = _event_ingestion_stage(
            ctx,
            skip_replay=skip_replay,
            fatal_index_errors=profile == "warm",
        )
        if profile == "warm":
            return _result_payload(ctx, profile="warm", stages=[ingestion])

        baseline_stage, full_context = _baseline_skill_export_stage(ctx, events=events)
        queue_stage = _queue_stage(
            ctx,
            impact=full_context["impact"],
            event_log=full_context["event_log"],
            queue=queue,
            corpus=corpus,
            legacy=full_context["legacy"],
        )
        return _result_payload(
            ctx,
            profile="full",
            stages=[ingestion, baseline_stage, queue_stage],
            event_log=full_context["event_log"],
            event_log_present=full_context["event_log_present"],
        )

    result = _locked_run(ctx, execute)
    duration_ms = int((time.time() - started_at) * 1000)
    if profile == "full":
        _emit_refresh_event(
            "refresh_end",
            ctx.repo,
            parent_event_id=start_event_id,
            payload={"telemetry": {"duration_ms": duration_ms, "profile": profile}},
        )
    return result


def run_warm(
    repo: pathlib.Path,
    *,
    state_dir: str | pathlib.Path | None = None,
    personal: str | pathlib.Path | None = None,
    skip_replay: bool = False,
) -> dict[str, Any]:
    return run(
        repo,
        profile="warm",
        state_dir=state_dir,
        personal=personal,
        skip_replay=skip_replay,
    )


def run_full(
    repo: pathlib.Path,
    *,
    state_dir: str | pathlib.Path | None = None,
    personal: str | pathlib.Path | None = None,
    events: pathlib.Path | None = None,
    queue: pathlib.Path | None = None,
    corpus: pathlib.Path | None = None,
) -> dict[str, Any]:
    return run(
        repo,
        profile="full",
        state_dir=state_dir,
        personal=personal,
        events=events,
        queue=queue,
        corpus=corpus,
    )
