#!/usr/bin/env python3
"""Stop-hook entry point — replay hook events then advance the indexer.

Runs ``bin/alc_bootstrap_pipeline`` with the current working directory as
the repo so every session-end warms ``events.sqlite`` from any rows the
collector adapter just wrote into ``hook-events.jsonl``. Runs BEFORE
``refresh_dashboard.py`` in the Stop list so the dashboard re-render
reads a fresh sqlite.
"""

import os
import pathlib
import subprocess
import sys

PLUGIN_ROOT = pathlib.Path(
    os.environ.get("CLAUDE_PLUGIN_ROOT")
    or os.environ.get("ALC_PLUGIN_ROOT")
    or pathlib.Path(__file__).resolve().parents[1]
)
_script = PLUGIN_ROOT / "bin" / "alc_bootstrap_pipeline"
raise SystemExit(
    subprocess.run(
        [sys.executable, str(_script), "--repo", str(pathlib.Path.cwd()), "--quiet"],
    ).returncode
)
