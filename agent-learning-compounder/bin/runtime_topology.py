#!/usr/bin/env python3
"""Runtime topology helpers for repo-local vs user-runtime path selection.

This module owns runtime wiring in the source-first direction:
topology resolution, config targets, hook command rendering, and drift
candidate selection for each mode.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
import re
import shlex
import pathlib
import sys
from typing import Any, Iterable


SKILL_NAME = "agent-learning-compounder"


def _repo_root(repo: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(repo).expanduser().resolve()


def _dedupe(paths: list[pathlib.Path]) -> list[pathlib.Path]:
    seen: set[pathlib.Path] = set()
    out: list[pathlib.Path] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            out.append(path)
    return out


@dataclass(frozen=True)
class RuntimeTopology:
    repo: pathlib.Path
    source_skill_root: pathlib.Path
    dev_state_user_root: pathlib.Path
    dev_state_root: pathlib.Path
    repo_runtime_candidates: tuple[pathlib.Path, ...]
    user_runtime_candidates: tuple[pathlib.Path, ...]


@dataclass(frozen=True)
class DriftPlan:
    mode: str
    source_root: pathlib.Path
    read_targets: tuple[pathlib.Path, ...]
    write_target: pathlib.Path | None
    include_user_runtimes: bool


@dataclass(frozen=True)
class RuntimeInstallTarget:
    runtime: str
    root: pathlib.Path


@dataclass(frozen=True)
class RuntimeInstallPlan:
    runtime: str
    mode: str
    targets: tuple[RuntimeInstallTarget, ...]


def shell_env_command(env: dict[str, pathlib.Path], command: pathlib.Path) -> str:
    exports = " ".join(
        f"{key}={shlex.quote(str(value))}"
        for key, value in sorted(env.items())
    )
    return f"{exports} {shlex.quote(str(command))}"


def _runtime_config_target(repo: pathlib.Path, runtime: str, scope: str) -> pathlib.Path:
    home = pathlib.Path.home()
    normalized_runtime = runtime.strip().lower()
    if scope not in {"repo", "user"}:
        raise ValueError(f"unsupported scope: {scope}")
    if normalized_runtime == "codex":
        return repo / ".codex" / "hooks.json" if scope == "repo" else home / ".codex" / "hooks.json"
    if normalized_runtime == "claude":
        return (
            repo / ".claude" / "settings.local.json"
            if scope == "repo"
            else home / ".claude" / "settings.json"
        )
    raise ValueError(f"unsupported runtime: {runtime}")


def _adapter_command(repo: pathlib.Path, runtime: str, event: str) -> str:
    _normalize_runtime(runtime)
    script = pathlib.Path(__file__).resolve().parent / "install_runtime_hooks"
    parts = [
        sys.executable,
        str(script),
        "--adapter",
        "--repo",
        str(repo),
        "--runtime",
        runtime,
        "--event",
        event,
    ]
    return " ".join(shlex.quote(part) for part in parts)


def _warm_loop_command(repo: pathlib.Path) -> str:
    script = pathlib.Path(__file__).resolve().parent / "alc_bootstrap_pipeline"
    parts = [
        sys.executable,
        str(script),
        "--repo",
        str(repo),
        "--quiet",
    ]
    return " ".join(shlex.quote(part) for part in parts)


def _validate_runtime_scope(runtime: str, scope: str) -> None:
    normalized_runtime = runtime.strip().lower()
    if normalized_runtime not in {"codex", "claude"}:
        raise ValueError(f"unsupported runtime: {runtime}")
    if scope not in {"repo", "user"}:
        raise ValueError(f"unsupported scope: {scope}")


def _normalize_runtime(runtime: str) -> str:
    normalized = runtime.strip().lower()
    if normalized not in {"codex", "claude"}:
        raise ValueError(f"unsupported runtime: {runtime}")
    return normalized


def _normalize_install_runtime(runtime: str) -> str:
    normalized = runtime.strip().lower()
    if normalized not in {"codex", "claude", "all"}:
        raise ValueError(f"unsupported runtime: {runtime}")
    return normalized


def _home_from_env(env: dict[str, str]) -> pathlib.Path:
    return pathlib.Path(env.get("HOME", str(pathlib.Path.home()))).expanduser()


def _env_path(env: dict[str, str], name: str, fallback: pathlib.Path) -> pathlib.Path:
    value = env.get(name)
    return pathlib.Path(value).expanduser() if value else fallback


def runtime_hint_from_repo(repo: pathlib.Path) -> str | None:
    root = _repo_root(repo)
    pattern = re.compile(r"runtime\s*[:=]\s*(codex|claude|all)", re.IGNORECASE)
    for path in (root / "AGENTS.md", root / "CLAUDE.md", root / "GEMINI.md"):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            match = pattern.search(line)
            if match:
                return match.group(1).lower()
    return None


def resolve_install_runtime(
    request: str,
    *,
    repo: pathlib.Path | None = None,
    env: dict[str, str] | None = None,
) -> str:
    requested = request.strip().lower()
    if requested != "auto":
        return _normalize_install_runtime(requested)

    values = os.environ if env is None else env
    env_runtime = values.get("AGENT_LEARNING_RUNTIME", "").strip().lower()
    if env_runtime in {"codex", "claude", "all"}:
        return env_runtime

    if repo is not None:
        hint = runtime_hint_from_repo(repo)
        if hint:
            return hint

    return "codex"


def runtime_install_modes(runtime: str) -> tuple[str, ...]:
    normalized = _normalize_install_runtime(runtime)
    if normalized == "all":
        return ("codex", "claude")
    return (normalized,)


def user_global_install_root(runtime: str, *, env: dict[str, str] | None = None) -> pathlib.Path:
    normalized = _normalize_runtime(runtime)
    values = os.environ if env is None else env
    home = _home_from_env(values)
    if normalized == "codex":
        agents_home = _env_path(values, "AGENTS_HOME", home / ".agents")
        return _env_path(values, "AGENTS_SKILLS_DIR", agents_home / "skills")
    claude_home = _env_path(values, "CLAUDE_HOME", home / ".claude")
    return claude_home / "skills"


def codex_home_install_root(*, env: dict[str, str] | None = None) -> pathlib.Path:
    values = os.environ if env is None else env
    home = _home_from_env(values)
    return _env_path(values, "CODEX_HOME", home / ".codex") / "skills"


def plugin_install_root(*, env: dict[str, str] | None = None) -> pathlib.Path:
    values = os.environ if env is None else env
    home = _home_from_env(values)
    return _env_path(values, "CLAUDE_HOME", home / ".claude") / "plugins"


def bootstrap_install_root(repo: pathlib.Path, runtime: str) -> pathlib.Path:
    root = _repo_root(repo)
    normalized = _normalize_runtime(runtime)
    if normalized == "codex":
        return root / ".agents" / "skills"
    return root / ".claude" / "skills"


def build_runtime_install_plan(
    runtime: str,
    *,
    mode: str = "user",
    repo: pathlib.Path | None = None,
    target_root: pathlib.Path | None = None,
    env: dict[str, str] | None = None,
) -> RuntimeInstallPlan:
    normalized_runtime = _normalize_install_runtime(runtime)
    values = os.environ if env is None else env
    normalized_mode = mode.strip().lower()

    if normalized_mode == "explicit":
        if target_root is None:
            raise ValueError("explicit install target requires target_root")
        return RuntimeInstallPlan(
            runtime=normalized_runtime,
            mode=normalized_mode,
            targets=(RuntimeInstallTarget(normalized_runtime, pathlib.Path(target_root).expanduser()),),
        )

    if normalized_mode == "bootstrap":
        if repo is None:
            raise ValueError("bootstrap install target requires repo")
        return RuntimeInstallPlan(
            runtime=normalized_runtime,
            mode=normalized_mode,
            targets=tuple(
                RuntimeInstallTarget(runtime_name, bootstrap_install_root(repo, runtime_name))
                for runtime_name in runtime_install_modes(normalized_runtime)
            ),
        )

    if normalized_mode == "plugin":
        return RuntimeInstallPlan(
            runtime="claude",
            mode=normalized_mode,
            targets=(RuntimeInstallTarget("claude", plugin_install_root(env=values)),),
        )

    if normalized_mode == "codex-home":
        return RuntimeInstallPlan(
            runtime="codex",
            mode=normalized_mode,
            targets=(RuntimeInstallTarget("codex", codex_home_install_root(env=values)),),
        )

    if normalized_mode == "user":
        if normalized_runtime == "all":
            raise ValueError(
                "--runtime all requires --bootstrap-repo for explicit dual-runtime install; "
                "pass --runtime codex or --runtime claude"
            )
        return RuntimeInstallPlan(
            runtime=normalized_runtime,
            mode=normalized_mode,
            targets=(
                RuntimeInstallTarget(
                    normalized_runtime,
                    user_global_install_root(normalized_runtime, env=values),
                ),
            ),
        )

    raise ValueError(f"unsupported install target mode: {mode}")


def _dev_hook_specs(topology: RuntimeTopology) -> list[dict[str, Any]]:
    plugin = topology.source_skill_root
    return [
        {
            "event": "Stop",
            "label": "warm-loop (events.sqlite refresh)",
            "match": "alc_bootstrap_pipeline",
            "matcher": "",
            "command": (
                f"{sys.executable} {plugin}/bin/alc_bootstrap_pipeline "
                f"--repo {topology.repo} --quiet"
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
                f"{plugin}/bin/render_state_surface --repo {topology.repo} "
                "--format session-report"
            ),
        },
        {
            "event": "Stop",
            "label": "auto_distill_session (repo-source dogfood)",
            "match": "auto_distill_session",
            "matcher": "",
            "command": shell_env_command(
                {
                    "AGENT_LEARNING_PERSONAL": topology.dev_state_user_root,
                    "AGENT_LEARNING_SKILL_DIR": plugin,
                    "AGENT_LEARNING_STATE_DIR": topology.dev_state_root,
                    "AGENT_LEARNING_USER": topology.dev_state_user_root,
                },
                plugin / "bin" / "auto_distill_session",
            ),
        },
    ]


def _drift_plan(
    topology: RuntimeTopology,
    *,
    explicit_runtimes: Iterable[pathlib.Path] | None = None,
    include_user_runtimes: bool = False,
) -> DriftPlan:
    explicit = [
        pathlib.Path(path).expanduser() for path in explicit_runtimes or []
    ]

    mode = "repo-only"
    if explicit:
        candidates = explicit
        mode = "explicit"
    else:
        candidates = list(topology.repo_runtime_candidates)

    if include_user_runtimes:
        candidates.extend(topology.user_runtime_candidates)
        mode = "user-audit" if mode == "repo-only" else "explicit+user-audit"

    return DriftPlan(
        mode=mode,
        source_root=topology.repo,
        read_targets=tuple(_dedupe(candidates)),
        write_target=None,
        include_user_runtimes=include_user_runtimes,
    )


def _repo_runtime_candidates(repo: pathlib.Path) -> list[pathlib.Path]:
    return [
        repo / ".agents" / "skills" / SKILL_NAME,
        repo / ".claude" / "skills" / SKILL_NAME,
        repo / ".claude" / "plugins" / SKILL_NAME,
        repo / ".runtime" / "agents" / "skills" / SKILL_NAME,
        repo / ".runtime" / "claude" / "skills" / SKILL_NAME,
        repo / ".runtime" / "claude" / "plugins" / SKILL_NAME,
        repo / ".runtime" / "codex" / "skills" / SKILL_NAME,
    ]


def _user_runtime_candidates() -> list[pathlib.Path]:
    home = pathlib.Path.home()
    return [
        home / ".agents" / "skills" / SKILL_NAME,
        home / ".claude" / "skills" / SKILL_NAME,
        home / ".claude" / "plugins" / SKILL_NAME,
        home / ".codex" / "skills" / SKILL_NAME,
        home / ".agent-learning",
    ]


def build_runtime_topology(repo: pathlib.Path) -> RuntimeTopology:
    root = _repo_root(repo)
    return RuntimeTopology(
        repo=root,
        source_skill_root=root / "agent-learning-compounder",
        dev_state_user_root=root / ".runtime" / "agent-learning-user",
        dev_state_root=root / ".runtime" / "agent-learning-state",
        repo_runtime_candidates=tuple(_dedupe(_repo_runtime_candidates(root))),
        user_runtime_candidates=tuple(_dedupe(_user_runtime_candidates())),
    )


def build_runtime_drift_plan(
    repo: pathlib.Path,
    *,
    explicit_runtimes: list[pathlib.Path] | None = None,
    include_user_runtimes: bool = False,
) -> DriftPlan:
    """Return a mode-aware drift plan from source/topology settings."""
    topology = build_runtime_topology(repo)
    return _drift_plan(
        topology,
        explicit_runtimes=explicit_runtimes,
        include_user_runtimes=include_user_runtimes,
    )


def config_for_runtime(
    repo: pathlib.Path,
    runtime: str,
    scope: str = "repo",
) -> pathlib.Path:
    """Compatibility entry point for old callers."""
    _validate_runtime_scope(runtime, scope)
    return _runtime_config_target(_repo_root(repo), _normalize_runtime(runtime), scope)


def adapter_command(
    repo: pathlib.Path,
    runtime: str,
    event: str,
) -> str:
    """Compatibility entry point for old callers."""
    return _adapter_command(_repo_root(repo), _normalize_runtime(runtime), event)


def warm_loop_command(repo: pathlib.Path) -> str:
    """Compatibility entry point for old callers."""
    return _warm_loop_command(_repo_root(repo))


def dev_hook_specs(repo: pathlib.Path) -> list[dict[str, Any]]:
    return _dev_hook_specs(build_runtime_topology(repo))


def drift_selection(
    repo: pathlib.Path,
    explicit_runtimes: list[pathlib.Path] | None = None,
    include_user_runtimes: bool = False,
) -> DriftPlan:
    return build_runtime_drift_plan(
        repo,
        explicit_runtimes=explicit_runtimes,
        include_user_runtimes=include_user_runtimes,
    )


def _shell(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--shell",
        choices=[
            "resolve-install-runtime",
            "install-target-root",
            "install-targets",
            "install-runtimes",
        ],
    )
    parser.add_argument("--request", default="auto")
    parser.add_argument("--runtime", default="codex")
    parser.add_argument("--mode", default="user")
    parser.add_argument("--repo")
    parser.add_argument("--target-root")
    args = parser.parse_args(argv)

    try:
        if args.shell == "resolve-install-runtime":
            repo = pathlib.Path(args.repo) if args.repo else None
            print(resolve_install_runtime(args.request, repo=repo))
            return 0
        if args.shell == "install-runtimes":
            for runtime_name in runtime_install_modes(args.runtime):
                print(runtime_name)
            return 0
        if args.shell == "install-targets":
            repo = pathlib.Path(args.repo) if args.repo else None
            target_root = pathlib.Path(args.target_root) if args.target_root else None
            plan = build_runtime_install_plan(
                args.runtime,
                mode=args.mode,
                repo=repo,
                target_root=target_root,
            )
            for target in plan.targets:
                print(f"{target.runtime}\t{target.root}")
            return 0
        if args.shell == "install-target-root":
            repo = pathlib.Path(args.repo) if args.repo else None
            target_root = pathlib.Path(args.target_root) if args.target_root else None
            plan = build_runtime_install_plan(
                args.runtime,
                mode=args.mode,
                repo=repo,
                target_root=target_root,
            )
            if len(plan.targets) != 1:
                raise ValueError("install-target-root requires exactly one target")
            print(plan.targets[0].root)
            return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    parser.error("--shell is required")
    return 2


if __name__ == "__main__":
    raise SystemExit(_shell(sys.argv[1:]))
