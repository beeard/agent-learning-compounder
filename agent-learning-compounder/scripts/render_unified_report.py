#!/usr/bin/env python3
"""Run the read-only ALC reporting pipeline and render the dashboard."""

from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import os
import pathlib
import subprocess
import sys
import webbrowser
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"
SERVER_PATH = ROOT / "skills" / "alc-dashboard" / "server.py"

if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

try:
    from state_handle import StateHandle
except ImportError:  # pragma: no cover
    from bin.state_handle import StateHandle


@dataclass
class CommandError(RuntimeError):
    command: list[str]
    code: int
    stdout: str
    stderr: str


def _load_dashboard_server():
    loader = importlib.machinery.SourceFileLoader("alc_dashboard_server", str(SERVER_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load dashboard server module from {SERVER_PATH}")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _run_command(cmd: list[str], *, cwd: pathlib.Path, env: dict[str, str] | None = None, step: str = ""):
    result = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise CommandError(command=cmd, code=result.returncode, stdout=result.stdout, stderr=result.stderr)
    return result


def _resolve_state(repo: pathlib.Path, state: pathlib.Path | None) -> tuple[StateHandle, pathlib.Path | None]:
    if state is not None:
        state_root = state
        if state.parent.name == "repos":
            state_root = state.parent.parent

        with _state_env(state_root):
            return StateHandle.for_repo(repo), state_root
    return StateHandle.for_repo(repo), None


def _state_env(state: pathlib.Path):
    class _Ctx:
        def __enter__(self_inner):
            self_inner.previous = os.environ.get("AGENT_LEARNING_STATE_DIR")
            os.environ["AGENT_LEARNING_STATE_DIR"] = str(state)

        def __exit__(self_inner, exc_type, exc, tb):
            previous = self_inner.previous
            if previous is None:
                os.environ.pop("AGENT_LEARNING_STATE_DIR", None)
            else:
                os.environ["AGENT_LEARNING_STATE_DIR"] = previous
    return _Ctx()


def _find_default_baseline(state: StateHandle) -> pathlib.Path:
    candidates = [
        state.repo_state_dir / "seed" / "baseline.json",
        state.repo_state_dir / "baseline.json",
        state.reports_dir / "baseline.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("baseline.json not found")


def _default_corpus() -> pathlib.Path:
    env_path = os.environ.get("ALC_CORPUS", os.environ.get("AGENT_LEARNING_CORPUS", ""))
    if env_path:
        return pathlib.Path(env_path).expanduser()
    return pathlib.Path.home() / ".claude" / "projects"


def _pipeline_commands(state: StateHandle, corpus: pathlib.Path, baseline: pathlib.Path, synth_source: str) -> list[list[str]]:
    state.reports_dir.mkdir(parents=True, exist_ok=True)
    latest_report = state.reports_dir / "latest-report.md"
    samples = state.reports_dir / "samples.json"

    # distill_learning expects --corpus to be a FILE (it calls Path.read_text).
    # If the caller passed a directory (the common case — ~/.claude/projects
    # transcripts), run extract_sessions first to produce a corpus text file;
    # otherwise pass the file through unchanged.
    commands: list[list[str]] = []
    if corpus.is_dir():
        corpus_file = state.reports_dir / "corpus.txt"
        commands.append([
            sys.executable,
            str(BIN / "extract_sessions"),
            "--path",
            str(corpus),
            "--output",
            str(corpus_file),
        ])
        distill_corpus = corpus_file
    else:
        distill_corpus = corpus

    # Thread the per-repo skill-{map,usage,impact}.json into distill_learning
    # so the skill_inventory / skill_usage / skill_compensation sections
    # surface the analyzers' real output. Without these, distill falls back
    # to a baseline-only skill view that reports `available_skills: 0` even
    # when the analyzers have produced rich data — the report looks broken
    # because the wrapper isn't passing the analyzer files it itself just
    # wrote (refresh_learning_state.py:545-547).
    skill_map_path = state.repo_state_dir / "skill-map.json"
    skill_usage_path = state.repo_state_dir / "skill-usage.json"
    skill_impact_path = state.repo_state_dir / "skill-impact.json"
    distill_cmd = [
        sys.executable,
        str(BIN / "distill_learning"),
        "--corpus",
        str(distill_corpus),
        "--baseline",
        str(baseline),
        "--output",
        str(latest_report),
        "--no-html",
    ]
    if skill_map_path.exists():
        distill_cmd.extend(["--skill-map", str(skill_map_path)])
    if skill_usage_path.exists():
        distill_cmd.extend(["--skill-usage", str(skill_usage_path)])
    if skill_impact_path.exists():
        distill_cmd.extend(["--skill-impact", str(skill_impact_path)])
    commands.extend([
        distill_cmd,
        [
            sys.executable,
            str(BIN / "synthesize_samples"),
            "--source",
            synth_source,
            "--output",
            str(samples),
            "--corpus",
            str(corpus),
        ],
        [sys.executable, str(BIN / "analyst_score"), "--state", str(state.repo_state_dir)],
        [
            sys.executable,
            str(BIN / "recommender_render"),
            "--state",
            str(state.repo_state_dir),
        ],
    ])
    return commands


def run_unified_report(
    *,
    repo: pathlib.Path,
    state: pathlib.Path | None = None,
    baseline: pathlib.Path | None = None,
    corpus: pathlib.Path | None = None,
    synth_source: str = "combined",
    host: str = "127.0.0.1",
    port: int = 0,
    open_browser: bool = True,
    serve: bool = True,
) -> int:
    repo = repo.resolve()
    corpus = corpus or _default_corpus()
    state_handle, explicit_state = _resolve_state(repo, state)
    baseline_path = baseline or _find_default_baseline(state_handle)
    command_env = os.environ.copy()
    if explicit_state is not None:
        command_env["AGENT_LEARNING_STATE_DIR"] = str(explicit_state)

    for command in _pipeline_commands(state_handle, corpus, baseline_path, synth_source):
        _run_command(command, cwd=repo, env=command_env)

    dashboard = _load_dashboard_server()
    httpd, selected = dashboard.create_server(
        repo=repo,
        state=explicit_state,
        host=host,
        port=port,
    )

    url = f"http://{host}:{selected}/"
    if open_browser:
        webbrowser.open(url, new=1)

    if not serve:
        httpd.server_close()
        return 0

    try:
        httpd.serve_forever()
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        httpd.server_close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=pathlib.Path, default=pathlib.Path.cwd())
    parser.add_argument("--state", "--state-dir", "--state_dir", dest="state", type=pathlib.Path)
    parser.add_argument("--baseline", type=pathlib.Path)
    parser.add_argument("--corpus", type=pathlib.Path)
    parser.add_argument("--synthesize-source", default="combined", choices=["combined", "hook-events", "claude-insights"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--no-serve", action="store_true", help="Run the pipeline and return after launch.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run_unified_report(
            repo=args.repo,
            state=args.state,
            baseline=args.baseline,
            corpus=args.corpus,
            synth_source=args.synthesize_source,
            host=args.host,
            port=args.port,
            open_browser=not args.no_open,
            serve=not args.no_serve,
        )
    except CommandError as error:
        message = error.stderr.strip() or error.stdout.strip() or f"command {error.command[1]} failed"
        print(message, file=sys.stderr)
        return error.code or 1
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
