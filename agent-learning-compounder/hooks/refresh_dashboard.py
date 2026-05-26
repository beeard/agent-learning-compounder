#!/usr/bin/env python3
"""Refresh static ALC dashboard artifacts — thin wrapper over render_state_surface."""

import os, pathlib, subprocess, sys

PLUGIN_ROOT = pathlib.Path(
    os.environ.get("CLAUDE_PLUGIN_ROOT")
    or os.environ.get("ALC_PLUGIN_ROOT")
    or pathlib.Path(__file__).resolve().parents[1]
)
_script = PLUGIN_ROOT / "bin" / "render_state_surface"
raise SystemExit(subprocess.run([sys.executable, str(_script), "--repo", str(pathlib.Path.cwd()), "--format", "html"]).returncode)
