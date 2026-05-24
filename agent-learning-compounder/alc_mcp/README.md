# agent-learning-compounder MCP server

Stdio MCP server exposing the durable state as queryable tools.

## Install

```bash
pip install mcp
```

(Or `pip install -r requirements-optional.txt` to install all P5 optional deps.)

## Run

From the installed skill root:

```bash
python3 -m alc_mcp.server
```

Or directly:

```bash
python3 alc_mcp/server.py
```

## Tools

- `get_gates(repo, scope=None) -> list[gate]`
- `report_outcome(repo, gate_id, outcome[, correlation_id]) -> {recorded: bool}`
- `propose_gate(repo, domain, category, gate, evidence?) -> {queue_id}`
- `get_skill_context(repo) -> str`

## Integration

For Claude Desktop / Cursor / other MCP clients, configure stdio with the
absolute path to this server entry point. Repo path is passed per call so a
single server instance can serve multiple repos.

The handler functions are import-safe even when the `mcp` SDK is missing —
they don't depend on it. Only the stdio entry point (`build_server`, `main`)
requires the SDK.
