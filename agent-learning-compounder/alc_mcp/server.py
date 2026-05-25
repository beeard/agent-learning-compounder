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
from collect_hook_event import (  # noqa: E402
    assert_regular_file_destination,
    bounded,
    load_telemetry_config,
    normalize_event,
)
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
_MAX_AGENT_FIELD_LEN = 128


def _append_jsonl_locked(path: Path, rendered: str) -> None:
    fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.write(rendered + "\n")


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
        "schema_version": 3,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": "tool_report_outcome",
        "correlation_id": correlation_id,
        "gate_loaded_ids": [gate_id],
        "outcome": outcome,
    }
    rendered = _reject_if_redacted(row, label="report_outcome event")
    _append_jsonl_locked(log, rendered)
    return {"recorded": True}


async def report_agent_event_handler(args: dict) -> dict:
    """Record bounded subagent/background-worker telemetry through ALC MCP."""
    repo = Path(args["repo"]).resolve()
    log = _hook_events_path(repo)
    assert_regular_file_destination(log, label="MCP report_agent_event target")

    event_name = bounded(args.get("event") or "AgentDispatchComplete", _MAX_AGENT_FIELD_LEN)
    if not event_name:
        raise ValueError("event rejected (empty after sanitization or contained secret-shaped content)")

    payload = dict(args)
    payload["event"] = event_name
    payload["runtime"] = args.get("runtime") or "alc-mcp"
    payload["repo"] = str(repo)
    row = normalize_event(payload, repo, load_telemetry_config(repo))
    rendered = _reject_if_redacted(row, label="report_agent_event row")
    _append_jsonl_locked(log, rendered)
    return {"recorded": True, "event": row.get("event"), "dispatch_id": row.get("dispatch_id")}


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


TOOL_SCHEMAS = [
    {
        "name": "get_gates",
        "description": "Return approved gates for a repo, optionally scoped.",
        "inputSchema": {
            "type": "object",
            "required": ["repo"],
            "properties": {"repo": {"type": "string"}, "scope": {"type": "string"}},
        },
    },
    {
        "name": "report_outcome",
        "description": "Record a gate outcome (loaded_helpful, loaded_unhelpful, skipped).",
        "inputSchema": {
            "type": "object",
            "required": ["repo", "gate_id", "outcome"],
            "properties": {
                "repo": {"type": "string"},
                "gate_id": {"type": "string"},
                "outcome": {"type": "string"},
                "correlation_id": {"type": "string"},
            },
        },
    },
    {
        "name": "report_agent_event",
        "description": "Record bounded agent dispatch telemetry without prompts or tool output.",
        "inputSchema": {
            "type": "object",
            "required": ["repo"],
            "properties": {
                "repo": {"type": "string"},
                "event": {"type": "string"},
                "runtime": {"type": "string"},
                "session_id": {"type": "string"},
                "correlation_id": {"type": "string"},
                "parent_correlation_id": {"type": "string"},
                "outcome": {"type": "string"},
                "label": {"type": "string"},
                "agent_role": {"type": "string"},
                "agent_backend": {"type": "string"},
                "agent_id": {"type": "string"},
                "dispatch_id": {"type": "string"},
                "agent_mode": {"type": "string"},
                "agent_model": {"type": "string"},
                "agent_effort": {"type": "string"},
                "agent_sandbox": {"type": "string"},
                "agent_write_scope": {"type": "array", "items": {"type": "string"}},
                "agent_worktree": {"type": "string"},
                "agent_branch": {"type": "string"},
            },
        },
    },
    {
        "name": "propose_gate",
        "description": "Append an operator-proposed gate to the review queue.",
        "inputSchema": {
            "type": "object",
            "required": ["repo", "domain", "category", "gate"],
            "properties": {
                "repo": {"type": "string"},
                "domain": {"type": "string"},
                "category": {"type": "string"},
                "gate": {"type": "string"},
                "evidence": {"type": "string"},
            },
        },
    },
    {
        "name": "get_skill_context",
        "description": "Return the latest skill-context markdown for the repo.",
        "inputSchema": {
            "type": "object",
            "required": ["repo"],
            "properties": {"repo": {"type": "string"}},
        },
    },
]

TOOL_HANDLERS = {
    "get_gates": get_gates_handler,
    "report_outcome": report_outcome_handler,
    "report_agent_event": report_agent_event_handler,
    "propose_gate": propose_gate_handler,
    "get_skill_context": get_skill_context_handler,
}


def build_server():
    """Build the MCP stdio server. Requires the mcp SDK."""
    from mcp.server import Server
    from mcp.types import Tool, TextContent

    server = Server("agent-learning-compounder")

    @server.list_tools()
    async def list_tools():
        return [Tool(**schema) for schema in TOOL_SCHEMAS]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        h = TOOL_HANDLERS.get(name)
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


def _jsonrpc_result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _jsonrpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _trace(event: str, **fields: Any) -> None:
    trace_path = os.environ.get("ALC_MCP_TRACE")
    if not trace_path:
        return
    row = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": event,
        **fields,
    }
    try:
        with open(trace_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    except OSError:
        pass


def _tool_content(result: Any, *, is_error: bool = False) -> dict[str, Any]:
    if isinstance(result, str):
        text = result
    else:
        text = json.dumps(result, indent=2)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


async def _raw_call_tool(params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        return _tool_content({"error": "arguments must be an object"}, is_error=True)
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return _tool_content({"error": f"unknown tool {name}"}, is_error=True)
    try:
        return _tool_content(await handler(arguments))
    except Exception as exc:
        return _tool_content({"error": str(exc)}, is_error=True)


async def _handle_raw_message(message: dict[str, Any]) -> dict[str, Any] | None:
    request_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}
    if "id" not in message:
        return None
    if method == "initialize":
        protocol_version = params.get("protocolVersion") or "2025-11-25"
        return _jsonrpc_result(
            request_id,
            {
                "protocolVersion": protocol_version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": "agent-learning-compounder",
                    "version": "3",
                },
            },
        )
    if method == "tools/list":
        return _jsonrpc_result(request_id, {"tools": TOOL_SCHEMAS})
    if method == "tools/call":
        return _jsonrpc_result(request_id, await _raw_call_tool(params))
    if method == "ping":
        return _jsonrpc_result(request_id, {})
    return _jsonrpc_error(request_id, -32601, f"method not found: {method}")


def _read_framed_stdin_message(first_line: str) -> tuple[str, str] | None:
    headers = [first_line]
    while True:
        line = sys.stdin.readline()
        if not line:
            return None
        if line in ("\n", "\r\n"):
            break
        headers.append(line)
    content_length = None
    for header in headers:
        name, sep, value = header.partition(":")
        if sep and name.lower() == "content-length":
            try:
                content_length = int(value.strip())
            except ValueError:
                return None
            break
    if content_length is None:
        return None
    return sys.stdin.read(content_length), "content-length"


def _read_stdin_message() -> tuple[str, str] | None:
    line = sys.stdin.readline()
    if not line:
        _trace("stdin_eof")
        return None
    if line.lower().startswith("content-length:"):
        _trace("frame_header", header="content-length")
        return _read_framed_stdin_message(line)
    _trace("frame_header", header="line", length=len(line))
    return line, "line"


def _write_stdout_message(response: dict[str, Any], framing: str) -> None:
    rendered = json.dumps(response, separators=(",", ":"))
    if framing == "content-length":
        encoded = rendered.encode("utf-8")
        sys.stdout.write(f"Content-Length: {len(encoded)}\r\n\r\n{rendered}")
    else:
        sys.stdout.write(rendered + "\n")
    sys.stdout.flush()


def raw_stdio_main() -> None:
    """Small dependency-light MCP stdio loop.

    The handler functions above are the security boundary. This loop only
    handles MCP JSON-RPC framing so user-level Codex/Claude configs do not
    depend on SDK transport behavior.
    """
    while True:
        framed = _read_stdin_message()
        if framed is None:
            break
        line, framing = framed
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            _trace("json_decode_error", framing=framing, length=len(line))
            response = _jsonrpc_error(None, -32700, "parse error")
        else:
            if not isinstance(message, dict):
                _trace("invalid_request", framing=framing, type=type(message).__name__)
                response = _jsonrpc_error(None, -32600, "invalid request")
            else:
                _trace(
                    "request",
                    framing=framing,
                    method=message.get("method"),
                    has_id="id" in message,
                )
                response = asyncio.run(_handle_raw_message(message))
        if response is None:
            continue
        _write_stdout_message(response, framing)


def sdk_main():
    """Entry point for the optional mcp SDK server."""
    from mcp.server.stdio import stdio_server
    server = build_server()

    async def _run():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(_run())


def main():
    """Entry point for stdio MCP clients."""
    raw_stdio_main()


if __name__ == "__main__":
    main()
