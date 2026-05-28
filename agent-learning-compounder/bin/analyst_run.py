#!/usr/bin/env python3
"""Suite-level orchestration for ALC analyst adapters."""

from __future__ import annotations

import argparse
import importlib
import pathlib
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from artifact_writer import write_artifact
from state_handle import StateHandle

Payload = dict[str, Any]
RunFunc = Callable[..., Payload]
FallbackFunc = Callable[..., Payload]
WriteFunc = Callable[[str, Any, Any], pathlib.Path]


@dataclass(frozen=True)
class AnalystAdapter:
    name: str
    artifact_id: str
    module_name: str | None = None
    run: RunFunc | None = None
    default_kwargs: Mapping[str, Any] = field(default_factory=dict)
    fallback: FallbackFunc | None = None

    def execute(self, state_handle: Any, **overrides: Any) -> Payload:
        runner = self.run
        if runner is None:
            if self.module_name is None:
                raise ValueError(f"analyst adapter '{self.name}' has no run target")
            runner = getattr(importlib.import_module(self.module_name), "run")

        kwargs = dict(self.default_kwargs)
        kwargs.update({key: value for key, value in overrides.items() if value is not None})
        try:
            return runner(state_handle, **kwargs)
        except FileNotFoundError as error:
            if self.fallback is None:
                raise
            return self.fallback(state_handle, error, **kwargs)


@dataclass(frozen=True)
class AnalystResult:
    name: str
    artifact_id: str
    payload: Payload
    path: pathlib.Path | None = None


DEFAULT_ANALYSTS: tuple[AnalystAdapter, ...] = (
    AnalystAdapter("patterns", "patterns", module_name="analyst_patterns"),
    AnalystAdapter(
        "anomalies",
        "anomalies",
        module_name="analyst_anomalies",
        default_kwargs={"min_n": 4, "z_threshold": 4.0},
    ),
    AnalystAdapter("correlations", "correlations", module_name="analyst_correlations"),
    AnalystAdapter("score", "recommendations", module_name="analyst_score", default_kwargs={"limit": 25}),
)


def resolve_state(repo: pathlib.Path | None = None, state: pathlib.Path | None = None) -> Any:
    if repo:
        return StateHandle.for_repo(repo)
    if not state:
        raise ValueError("either --repo or --state required")

    class _State:
        pass

    root = state.resolve()
    handle = _State()
    handle.repo_state_dir = root
    handle.events_sqlite = root / "events.sqlite"
    handle.outcomes_json = root / "outcomes.json"
    return handle


def adapter_by_name(name: str, adapters: Iterable[AnalystAdapter] = DEFAULT_ANALYSTS) -> AnalystAdapter:
    for adapter in adapters:
        if adapter.name == name:
            return adapter
    raise KeyError(f"unknown analyst adapter: {name}")


def _overrides_for(adapter: AnalystAdapter, overrides: Mapping[str, Mapping[str, Any]] | None) -> dict[str, Any]:
    if not overrides:
        return {}
    return dict(overrides.get(adapter.name, {}))


def run_suite(
    state_handle: Any,
    *,
    adapters: Iterable[AnalystAdapter] = DEFAULT_ANALYSTS,
    overrides: Mapping[str, Mapping[str, Any]] | None = None,
    write: WriteFunc | bool = write_artifact,
) -> list[AnalystResult]:
    results: list[AnalystResult] = []
    writer = write_artifact if write is True else write
    for adapter in adapters:
        payload = adapter.execute(state_handle, **_overrides_for(adapter, overrides))
        path = None
        if writer is not False:
            path = writer(adapter.artifact_id, payload, state_handle)
        results.append(AnalystResult(adapter.name, adapter.artifact_id, payload, path))
    return results


def run_registered(
    name: str,
    state_handle: Any,
    *,
    overrides: Mapping[str, Mapping[str, Any]] | None = None,
    write: WriteFunc | bool = write_artifact,
) -> AnalystResult:
    return run_suite(
        state_handle,
        adapters=(adapter_by_name(name),),
        overrides=overrides,
        write=write,
    )[0]


def _selected_adapters(names: list[str] | None) -> tuple[AnalystAdapter, ...]:
    if not names:
        return DEFAULT_ANALYSTS
    return tuple(adapter_by_name(name) for name in names)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=pathlib.Path)
    parser.add_argument("--state", "--state-dir", dest="state", type=pathlib.Path)
    parser.add_argument(
        "--analyst",
        dest="analysts",
        action="append",
        choices=[adapter.name for adapter in DEFAULT_ANALYSTS],
        help="run only this analyst; may be provided multiple times",
    )
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--min-n", type=int, default=4)
    parser.add_argument("--z-threshold", type=float, default=4.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        state_handle = resolve_state(args.repo, args.state)
        run_suite(
            state_handle,
            adapters=_selected_adapters(args.analysts),
            overrides={
                "score": {"limit": args.limit},
                "anomalies": {"min_n": args.min_n, "z_threshold": args.z_threshold},
            },
        )
    except Exception as exc:
        print(f"failed to run analyst suite: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
