"""Regression test: the alc-dashboard skill server must run standalone.

Bug history: skills/alc-dashboard/server.py used to do `from state_handle import
StateHandle` without bootstrapping sys.path. When the Claude Code plugin
invoked it directly (cwd elsewhere, PYTHONPATH empty), it crashed with
ModuleNotFoundError before it could even print --help. Fixed by adding a
sys.path insert at the top, mirroring the pattern in bin/alc_init,
bin/render_state_surface, and alc_mcp/server.py.

This test guards against the same regression in any of those scripts —
each must run --help from a fresh `python3 path/to/file.py` invocation
with no PYTHONPATH and no cwd help.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

# Scripts that must work when invoked directly without PYTHONPATH.
# Each is `(path, why_it_matters)`.
DIRECT_INVOCATION_ENTRY_POINTS = [
    (REPO_ROOT / "skills" / "alc-dashboard" / "server.py",
     "Claude Code plugin launches it directly via SKILL.md command"),
    (REPO_ROOT / "alc_mcp" / "server.py",
     "MCP stdio server — launched by Claude Code's mcpServer config"),
    (REPO_ROOT / "bin" / "alc_init",
     "Invoked as the first-run profiler from install.sh and from npx"),
    (REPO_ROOT / "bin" / "render_state_surface",
     "Invoked by hooks/session-start and hooks/refresh_dashboard.py wrappers"),
]


class StandaloneInvocationTests(unittest.TestCase):
    """Each entry point must succeed on a cold-environment direct invoke."""

    def _run_isolated(self, path: pathlib.Path, args: list[str]) -> subprocess.CompletedProcess:
        # Isolated: no PYTHONPATH, cwd unrelated to the script.
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        return subprocess.run(
            [sys.executable, str(path), *args],
            cwd="/tmp",
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=15,
        )

    def test_each_entry_point_runs_isolated_help(self) -> None:
        failures = []
        for path, why in DIRECT_INVOCATION_ENTRY_POINTS:
            with self.subTest(entry=path.relative_to(REPO_ROOT)):
                self.assertTrue(path.exists(), f"missing: {path}")
                # Pick the right "help-ish" flag per entry point.
                # alc_mcp/server.py is stdio — doesn't have --help; we send
                # an initialize request via stdin instead.
                if path.name == "server.py" and path.parent.name == "alc_mcp":
                    result = subprocess.run(
                        [sys.executable, str(path)],
                        input='{"jsonrpc":"2.0","id":1,"method":"initialize",'
                              '"params":{"protocolVersion":"2024-11-05",'
                              '"capabilities":{},"clientInfo":'
                              '{"name":"test","version":"1.0"}}}\n',
                        cwd="/tmp",
                        env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
                        text=True,
                        capture_output=True,
                        check=False,
                        timeout=15,
                    )
                    if result.returncode != 0 and "ModuleNotFoundError" in result.stderr:
                        failures.append(f"{path}: {result.stderr[:200]} ({why})")
                else:
                    result = self._run_isolated(path, ["--help"])
                    if "ModuleNotFoundError" in result.stderr:
                        failures.append(f"{path}: {result.stderr.splitlines()[-1]} ({why})")

        if failures:
            self.fail(
                "Entry points crashed on isolated direct invocation:\n  "
                + "\n  ".join(failures)
            )


if __name__ == "__main__":
    unittest.main()
