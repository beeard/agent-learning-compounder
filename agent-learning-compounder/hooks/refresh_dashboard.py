#!/usr/bin/env python3
"""Refresh static ALC dashboard artifacts for the current repo state."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from importlib.machinery import SourceFileLoader


PLUGIN_ROOT = pathlib.Path(os.environ.get("ALC_PLUGIN_ROOT", pathlib.Path(__file__).resolve().parents[1]))
SERVER_SRC = PLUGIN_ROOT / "skills" / "alc-dashboard" / "server.py"


def _load_dashboard_server():
    loader = SourceFileLoader("alc_dashboard_server_hook", str(SERVER_SRC))
    return loader.load_module()


def refresh(repo: pathlib.Path, state: pathlib.Path | None = None) -> pathlib.Path:
    if str(PLUGIN_ROOT / "bin") not in sys.path:
        sys.path.insert(0, str(PLUGIN_ROOT / "bin"))
    server = _load_dashboard_server()
    handle = server._resolve_state(repo=repo, state=state)
    handle.dashboard_dir.mkdir(parents=True, exist_ok=True)

    payload = server.build_data_blob(handle)
    (handle.dashboard_dir / "data.json").write_text(
        json.dumps(payload, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    html = server._inject_payload(server._read_template(), payload)
    (handle.dashboard_dir / "dashboard.html").write_text(html, encoding="utf-8")
    return handle.dashboard_dir


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=pathlib.Path, default=pathlib.Path.cwd())
    parser.add_argument("--state", "--state-dir", dest="state", type=pathlib.Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        refresh(args.repo.expanduser().resolve(), args.state.expanduser().resolve() if args.state else None)
    except Exception as error:
        print(f"refresh_dashboard: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
