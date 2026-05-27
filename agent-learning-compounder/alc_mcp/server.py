"""MCP server exposing agent-learning state as queryable tools."""

from __future__ import annotations

import asyncio
import importlib
import inspect
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
from alc_mcp.catalog import MCP_TOOLS, MCPToolSpec  # noqa: E402


def _agent_kind(args: dict[str, Any]) -> str:
    value = args.get("kind") or args.get("event") or "complete"
    return "complete" if value == "AgentDispatchComplete" else str(value).replace("agent_dispatch_", "")


def _state(args: dict[str, Any]) -> state_handle.StateHandle:
    return state_handle.StateHandle.for_repo(Path(args["repo"]).resolve())


def _improvement_queue_path(repo: Path) -> Path:
    return state_handle.StateHandle.for_repo(repo).repo_state_dir / "improvement-queue.jsonl"


def _schema(name: str, description: str, input_schema: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "description": description, "inputSchema": input_schema}


# ---------------------------------------------------------------------------
# Handler factory — resolves spec.backing at import time, builds async closure
# ---------------------------------------------------------------------------

def _make_handler(spec: MCPToolSpec):
    """Return an async handler closure for the given MCP tool spec.

    Imports the backing module once at registry-build time (startup cost paid
    once; the module reference is cached in the closure).  The function is
    looked up via ``getattr(module, func_name)`` on every call so that test
    mocks applied to the module attribute are honoured.

    Calling convention is determined from the backing function's static
    signature (inspected at factory time, not per-call):

    * First param named ``state`` → construct a StateHandle from ``args["repo"]``
      and pass it as the first positional argument, then fill remaining params by
      name from *args*.
    * Otherwise (e.g. ``dashboard_url(repo)`` or keyword-only signatures) →
      pass all args by name directly from *args*.  The caller is responsible for
      any type coercions via an explicit override (see TOOL_HANDLERS below).
    """
    module_name, func_name = spec.backing.rsplit(".", 1)
    mod = importlib.import_module(module_name)
    # Inspect the signature once to determine calling convention.
    params = list(inspect.signature(getattr(mod, func_name)).parameters.values())
    uses_state = bool(params) and params[0].name == "state"

    if uses_state:
        rest_params = params[1:]

        async def _state_handler(args: dict[str, Any]) -> Any:
            fn = getattr(mod, func_name)
            st = _state(args)
            kwargs = {p.name: args[p.name] for p in rest_params if p.name in args}
            return fn(st, **kwargs)

        return _state_handler
    else:
        async def _direct_handler(args: dict[str, Any]) -> Any:
            fn = getattr(mod, func_name)
            kwargs = {p.name: args[p.name] for p in params if p.name in args}
            return fn(**kwargs)

        return _direct_handler


# Build handlers for all catalog entries.  Explicit overrides follow.
TOOL_HANDLERS: dict[str, Any] = {
    name: _make_handler(spec) for name, spec in MCP_TOOLS.items()
}

# ---------------------------------------------------------------------------
# Explicit overrides
# ---------------------------------------------------------------------------

# report_outcome: alias args (recommendation_id/gate_id, verdict/outcome, reason/correlation_id)
# and wrap the bare event_id return value.
async def _report_outcome_handler(args: dict[str, Any]) -> dict[str, Any]:
    event_id = alc_propose.report_outcome(
        _state(args),
        args.get("recommendation_id") or args["gate_id"],
        args.get("verdict") or args["outcome"],
        args.get("reason") or args.get("correlation_id") or "reported via mcp",
    )
    return {"recorded": True, "event_id": event_id}


TOOL_HANDLERS["report_outcome"] = _report_outcome_handler

# report_agent_event: normalise kind via _agent_kind, resolve actor alias, wrap return.
_auto_report_agent_event = TOOL_HANDLERS["report_agent_event"]


async def _report_agent_event_handler(args: dict[str, Any]) -> dict[str, Any]:
    kind = _agent_kind(args)
    normalised = dict(args)
    normalised["kind"] = kind
    normalised.setdefault("actor_name", args.get("agent_role") or "mcp_caller")
    if "telemetry" not in normalised:
        normalised["telemetry"] = {
            k: v for k, v in args.items() if k not in {"repo", "kind", "event", "actor_name"}
        }
    event_id = await _auto_report_agent_event(normalised)
    return {"recorded": True, "event_id": event_id, "event": f"agent_dispatch_{kind}"}


TOOL_HANDLERS["report_agent_event"] = _report_agent_event_handler

# exec_sandbox: coerce repo to Path, inject default actor, transform ExecResult.
async def _exec_sandbox_handler(args: dict[str, Any]) -> dict[str, Any]:
    result = sandbox.run(
        scope=args["scope"],
        command=args["command"],
        repo=Path(args["repo"]),
        base_ref=args.get("base_ref"),
        timeout_s=args.get("timeout_s"),
        actor=args.get("actor") or {"kind": "mcp_server", "name": "alc_mcp"},
    )
    return {
        "exit_code": result.exit_code,
        "stdout": str(result.stdout_path),
        "stderr": str(result.stderr_path),
        "event_id": result.event_id,
        "run_id": result.run_id,
    }


TOOL_HANDLERS["exec_sandbox"] = _exec_sandbox_handler

# list_capabilities: not in MCP_TOOLS catalog; returns catalog metadata itself.
async def _list_capabilities_handler(args: dict[str, Any]) -> list[dict[str, Any]]:
    return [spec.to_dict() for spec in MCP_TOOLS.values()]


TOOL_HANDLERS["list_capabilities"] = _list_capabilities_handler


TOOL_SCHEMAS = [
    _schema(name, spec.summary, spec.parameters_schema)
    for name, spec in MCP_TOOLS.items()
] + [
    _schema(
        "list_capabilities",
        "Return live MCP capability metadata for all catalog entries.",
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
