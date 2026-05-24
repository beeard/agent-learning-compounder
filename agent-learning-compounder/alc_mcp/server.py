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
import time
from pathlib import Path
from typing import Any


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
    return next((repo / ".agent-learning" / "repos").rglob("improvement-queue.jsonl"))


def _hook_events_path(repo: Path) -> Path:
    repos_dir = repo / ".agent-learning" / "repos"
    # find or create the events log
    rids = list(repos_dir.iterdir())
    if not rids:
        raise FileNotFoundError(".agent-learning/repos has no repo-id subdir")
    return rids[0] / "hook-events.jsonl"


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
    row = {
        "schema_version": 2,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": "tool_report_outcome",
        "correlation_id": args.get("correlation_id", ""),
        "gate_loaded_ids": [args["gate_id"]],
        "outcome": args["outcome"],
    }
    fd = os.open(str(log), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.write(json.dumps(row, sort_keys=True) + "\n")
    return {"recorded": True}


async def propose_gate_handler(args: dict) -> dict:
    repo = Path(args["repo"]).resolve()
    queue = _improvement_queue_path(repo)
    h = hashlib.sha256(
        f"{args['domain']}|{args['category']}|{args['gate']}".encode("utf-8")
    ).hexdigest()[:12]
    queue_id = f"proposed-{h}-{int(time.time())}"
    row = {
        "id": queue_id,
        "kind": "operator_proposed_gate",
        "domain": args["domain"],
        "category": args["category"],
        "text": args["gate"],
        "evidence": args.get("evidence", ""),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with queue.open("a", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.write(json.dumps(row, sort_keys=True) + "\n")
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
