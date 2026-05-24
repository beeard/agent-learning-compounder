"""MCP server exposing agent-learning state as queryable tools.

Tools:
- get_gates(repo, scope=None) -> list[dict]
- report_outcome(repo, gate_id, outcome[, correlation_id]) -> dict
- propose_gate(repo, domain, category, gate, evidence?) -> dict
- get_skill_context(repo) -> str

The mcp SDK is an optional dependency. The handler functions (used by tests)
do not require it; only the stdio server entry point does.
"""
from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

# Reuse helpers from the collector and the state-paths module. Path-insert
# keeps imports valid whether the server is invoked as `python3 -m alc_mcp.server`
# from the package root or run directly from the alc_mcp/ directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from collect_hook_event import assert_regular_file_destination, bounded  # noqa: E402
from scrub_secrets import scrub  # noqa: E402
from state_paths import repo_state_dir  # noqa: E402


# Bounds for handler-side string fields. The collector caps free-form text at
# 160 chars via `bounded()`; we match that for outcome/evidence/gate text so a
# tool caller can't bloat a JSONL row beyond the line-per-event invariant.
_MAX_GATE_ID_LEN = 64
_MAX_OUTCOME_LEN = 64
_MAX_DOMAIN_LEN = 80
_MAX_CATEGORY_LEN = 80
_MAX_GATE_TEXT_LEN = 200
_MAX_EVIDENCE_LEN = 500
_MAX_CORRELATION_ID_LEN = 128


def _latest_gates_path(repo: Path) -> Path:
    payload = repo / ".agent-learning.json"
    if payload.is_file():
        data = json.loads(payload.read_text(encoding="utf-8"))
        p = data.get("latest_approved_gates")
        if p:
            return Path(p)
    raise FileNotFoundError("latest_approved_gates pointer missing from .agent-learning.json")


def _latest_skill_context_path(repo: Path) -> Path:
    payload = repo / ".agent-learning.json"
    if payload.is_file():
        data = json.loads(payload.read_text(encoding="utf-8"))
        p = data.get("latest_skill_context")
        if p:
            return Path(p)
    raise FileNotFoundError("latest_skill_context pointer missing from .agent-learning.json")


def _improvement_queue_path(repo: Path) -> Path:
    # Route through state_paths.repo_state_dir so multi-repo state roots (and
    # --state-dir / AGENT_LEARNING_STATE_DIR overrides) select the correct
    # subdirectory rather than picking the first one found via rglob().
    path = repo_state_dir(repo) / "improvement-queue.jsonl"
    if not path.is_file():
        raise FileNotFoundError(
            "improvement queue missing; run init_learning_system first"
        )
    return path


def _hook_events_path(repo: Path) -> Path:
    # Same multi-repo correctness reason as _improvement_queue_path. The hook
    # events log is created on first write, so we don't pre-check existence —
    # the dir is what must exist.
    state_dir = repo_state_dir(repo)
    if not state_dir.is_dir():
        raise FileNotFoundError(
            "hook events directory missing; run init_learning_system first"
        )
    return state_dir / "hook-events.jsonl"


def _require_bounded(value: Any, limit: int, field: str) -> str:
    """Run a user-supplied string through the collector's bounded() helper.

    Returns the sanitized text. Raises ValueError if the result is empty (the
    input was missing, all whitespace, or contained secret-shaped content that
    bounded() refused to keep).
    """
    if value is None or value == "":
        raise ValueError(f"{field} is required")
    text = bounded(value, limit)
    if not text:
        raise ValueError(f"{field} rejected (empty after sanitization or contained secret-shaped content)")
    return text


def _reject_if_redacted(row: dict, *, label: str) -> str:
    """Render row to JSON, run secret scrubber, reject on [REDACTED marker.

    Mirrors collect_hook_event.main()'s post-normalize guard so the MCP path
    cannot persist secret-shaped values that slipped past the per-field cap.
    """
    rendered = scrub(json.dumps(row, sort_keys=True, separators=(",", ":")))
    if "[REDACTED" in rendered:
        raise ValueError(f"{label} contains secret-like content after scrubbing")
    return rendered


async def get_gates_handler(args: dict) -> list[dict]:
    repo = Path(args["repo"]).resolve()
    md = _latest_gates_path(repo).read_text(encoding="utf-8")
    out = []
    blocks = md.split("\n- domain:")
    current_domain = None
    for i, block in enumerate(blocks):
        if i == 0:
            continue  # header
        # block starts with the domain value on the first line, then field lines
        lines = block.splitlines()
        if not lines:
            continue
        current_domain = lines[0].strip()
        gate_id, category, gate_text = None, None, None
        for line in lines[1:]:
            stripped = line.strip()
            if stripped.startswith("gate_id:"):
                gate_id = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("gate_category:"):
                category = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("gate:"):
                gate_text = stripped.split(":", 1)[1].strip()
        if gate_id and category and gate_text:
            out.append({
                "domain": current_domain,
                "gate_id": gate_id,
                "category": category,
                "gate": gate_text,
            })
    scope = args.get("scope")
    if scope:
        out = [g for g in out if g["domain"] == scope]
    return out


async def get_skill_context_handler(args: dict) -> str:
    repo = Path(args["repo"]).resolve()
    return _latest_skill_context_path(repo).read_text(encoding="utf-8")


async def report_outcome_handler(args: dict) -> dict:
    repo = Path(args["repo"]).resolve()
    log = _hook_events_path(repo)
    # Refuse to follow a symlink at the destination — matches the defense
    # pattern in collect_hook_event for adversarial telemetry redirection.
    assert_regular_file_destination(log, label="MCP report_outcome target")

    # Run user-supplied fields through the collector's bounded() helper so a
    # newline can't break the line-per-event invariant and oversize/secret-
    # shaped values are dropped before assembly.
    gate_id = _require_bounded(args.get("gate_id"), _MAX_GATE_ID_LEN, "gate_id")
    outcome = _require_bounded(args.get("outcome"), _MAX_OUTCOME_LEN, "outcome")
    correlation_raw = args.get("correlation_id", "")
    correlation_id = bounded(correlation_raw, _MAX_CORRELATION_ID_LEN) if correlation_raw else ""
    if correlation_raw and not correlation_id:
        raise ValueError("correlation_id rejected (empty after sanitization or contained secret-shaped content)")

    row = {
        "schema_version": 2,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": "tool_report_outcome",
        "correlation_id": correlation_id,
        "gate_loaded_ids": [gate_id],
        "outcome": outcome,
    }
    rendered = _reject_if_redacted(row, label="report_outcome event")
    fd = os.open(str(log), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.write(rendered + "\n")
    return {"recorded": True}


async def propose_gate_handler(args: dict) -> dict:
    repo = Path(args["repo"]).resolve()
    queue = _improvement_queue_path(repo)
    assert_regular_file_destination(queue, label="MCP propose_gate target")

    # All user-supplied fields go through bounded() to strip newlines, cap
    # length, and reject secret-shaped values — matching the collector's
    # contract so JSONL stays parseable line-by-line.
    domain = _require_bounded(args.get("domain"), _MAX_DOMAIN_LEN, "domain")
    category = _require_bounded(args.get("category"), _MAX_CATEGORY_LEN, "category")
    gate_text = _require_bounded(args.get("gate"), _MAX_GATE_TEXT_LEN, "gate")
    evidence_raw = args.get("evidence", "")
    evidence = bounded(evidence_raw, _MAX_EVIDENCE_LEN) if evidence_raw else ""
    if evidence_raw and not evidence:
        raise ValueError("evidence rejected (empty after sanitization or contained secret-shaped content)")

    h = hashlib.sha256(
        f"{domain}|{category}|{gate_text}".encode("utf-8")
    ).hexdigest()[:12]
    queue_id = f"proposed-{h}-{int(time.time())}"
    row = {
        "id": queue_id,
        "kind": "operator_proposed_gate",
        "domain": domain,
        "category": category,
        "text": gate_text,
        "evidence": evidence,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    rendered = _reject_if_redacted(row, label="propose_gate row")
    with queue.open("a", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.write(rendered + "\n")
    return {"queue_id": queue_id}


def build_server():
    """Build the MCP stdio server. Requires the mcp SDK."""
    from mcp.server import Server
    from mcp.types import Tool, TextContent

    server = Server("agent-learning-compounder")

    @server.list_tools()
    async def list_tools():
        return [
            Tool(name="get_gates",
                 description="Return approved gates for a repo, optionally scoped.",
                 inputSchema={"type": "object", "required": ["repo"],
                              "properties": {"repo": {"type": "string"},
                                             "scope": {"type": "string"}}}),
            Tool(name="report_outcome",
                 description="Record a gate outcome (loaded_helpful, loaded_unhelpful, skipped).",
                 inputSchema={"type": "object", "required": ["repo", "gate_id", "outcome"],
                              "properties": {"repo": {"type": "string"},
                                             "gate_id": {"type": "string"},
                                             "outcome": {"type": "string"},
                                             "correlation_id": {"type": "string"}}}),
            Tool(name="propose_gate",
                 description="Append an operator-proposed gate to the review queue.",
                 inputSchema={"type": "object",
                              "required": ["repo", "domain", "category", "gate"],
                              "properties": {"repo": {"type": "string"},
                                             "domain": {"type": "string"},
                                             "category": {"type": "string"},
                                             "gate": {"type": "string"},
                                             "evidence": {"type": "string"}}}),
            Tool(name="get_skill_context",
                 description="Return the latest skill-context markdown for the repo.",
                 inputSchema={"type": "object", "required": ["repo"],
                              "properties": {"repo": {"type": "string"}}}),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        handlers = {
            "get_gates": get_gates_handler,
            "report_outcome": report_outcome_handler,
            "propose_gate": propose_gate_handler,
            "get_skill_context": get_skill_context_handler,
        }
        h = handlers.get(name)
        if not h:
            return [TextContent(type="text", text=json.dumps({"error": f"unknown tool {name}"}))]
        try:
            result = await h(arguments)
        except Exception as exc:
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]
        if isinstance(result, str):
            return [TextContent(type="text", text=result)]
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    return server


def main():
    """Entry point for stdio MCP server. Requires mcp SDK."""
    from mcp.server.stdio import stdio_server
    server = build_server()
    asyncio.run(stdio_server(server))


if __name__ == "__main__":
    main()
