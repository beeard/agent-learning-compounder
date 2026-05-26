"""MCP server exposing agent-learning state as queryable tools."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import alc_propose  # noqa: E402
import alc_query  # noqa: E402
import exec_sandbox as sandbox  # noqa: E402
import state_handle  # noqa: E402
from alc_mcp.catalog import MCP_TOOLS  # noqa: E402


def _agent_kind(args: dict[str, Any]) -> str:
    value = args.get("kind") or args.get("event") or "complete"
    return "complete" if value == "AgentDispatchComplete" else str(value).replace("agent_dispatch_", "")


def _state(args: dict[str, Any]) -> state_handle.StateHandle:
    return state_handle.StateHandle.for_repo(Path(args["repo"]).resolve())


def _improvement_queue_path(repo: Path) -> Path:
    return state_handle.StateHandle.for_repo(repo).repo_state_dir / "improvement-queue.jsonl"


def _schema(name: str, description: str, input_schema: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "description": description, "inputSchema": input_schema}


async def get_gates_handler(args: dict[str, Any]) -> list[dict[str, Any]]:
    state = _state(args)
    return alc_query.get_gates(state, args.get("scope"))


async def get_skill_context_handler(args: dict[str, Any]) -> str:
    return alc_query.get_skill_context(_state(args))


async def get_recommendations_handler(args: dict[str, Any]) -> list[dict[str, Any]]:
    return alc_query.get_recommendations(_state(args))


async def list_pending_patches_handler(args: dict[str, Any]) -> list[dict[str, Any]]:
    return alc_query.get_pending_patches(_state(args))


async def get_dashboard_url_handler(args: dict[str, Any]) -> str:
    return state_handle.dashboard_url(args["repo"])


async def propose_apply_handler(args: dict[str, Any]) -> dict[str, str]:
    return alc_propose.propose_apply(_state(args), args["patch_id"])


async def propose_gate_handler(args: dict[str, Any]) -> dict[str, str]:
    return alc_propose.propose_gate(_state(args), args["domain"], args["category"], args["gate"], args.get("evidence"))


async def report_outcome_handler(args: dict[str, Any]) -> dict[str, Any]:
    event_id = alc_propose.report_outcome(_state(args), args.get("recommendation_id") or args["gate_id"], args.get("verdict") or args["outcome"], args.get("reason") or args.get("correlation_id") or "reported via mcp")
    return {"recorded": True, "event_id": event_id}


async def report_agent_event_handler(args: dict[str, Any]) -> dict[str, Any]:
    kind = _agent_kind(args)
    event_id = alc_propose.report_agent_event(_state(args), kind, args.get("actor_name") or args.get("agent_role") or "mcp_caller", args.get("telemetry") or {k: v for k, v in args.items() if k not in {"repo", "kind", "event", "actor_name"}})
    return {"recorded": True, "event_id": event_id, "event": f"agent_dispatch_{kind}"}


async def exec_sandbox_handler(args: dict[str, Any]) -> dict[str, Any]:
    result = sandbox.run(scope=args["scope"], command=args["command"], repo=Path(args["repo"]), base_ref=args.get("base_ref"), timeout_s=args.get("timeout_s"), actor=args.get("actor") or {"kind": "mcp_server", "name": "alc_mcp"})
    return {"exit_code": result.exit_code, "stdout": str(result.stdout_path), "stderr": str(result.stderr_path), "event_id": result.event_id, "run_id": result.run_id}


async def list_capabilities_handler(args: dict[str, Any]) -> list[dict[str, Any]]:
    return [spec.to_dict() for spec in MCP_TOOLS.values()]


TOOL_HANDLERS = {
    "get_gates": get_gates_handler,
    "get_skill_context": get_skill_context_handler,
    "get_recommendations": get_recommendations_handler,
    "list_pending_patches": list_pending_patches_handler,
    "get_dashboard_url": get_dashboard_url_handler,
    "propose_apply": propose_apply_handler,
    "propose_gate": propose_gate_handler,
    "report_outcome": report_outcome_handler,
    "report_agent_event": report_agent_event_handler,
    "exec_sandbox": exec_sandbox_handler,
    "list_capabilities": list_capabilities_handler,
}


TOOL_SCHEMAS = [
    _schema(name, spec.summary, spec.parameters_schema)
    for name, spec in MCP_TOOLS.items()
] + [
    _schema(
        "list_capabilities",
        "Return M1-M10 MCP capability metadata.",
        {"type": "object", "required": ["repo"], "properties": {"repo": {"type": "string"}}},
    )
]


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
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "event": event, **fields}
    try:
        with open(trace_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    except OSError:
        pass


def _tool_content(result: Any, *, is_error: bool = False) -> dict[str, Any]:
    text = result if isinstance(result, str) else json.dumps(result, indent=2)
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
        return _jsonrpc_result(request_id, {"protocolVersion": protocol_version, "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": "agent-learning-compounder", "version": "3"}})
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
    """Small dependency-light MCP stdio loop."""
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
                _trace("request", framing=framing, method=message.get("method"), has_id="id" in message)
                response = asyncio.run(_handle_raw_message(message))
        if response is None:
            continue
        _write_stdout_message(response, framing)


def main() -> None:
    raw_stdio_main()


if __name__ == "__main__":
    main()
