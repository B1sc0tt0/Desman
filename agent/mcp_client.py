"""
MCP client layer — uses FastMCP's own client to connect to FastMCP 3.x servers.
Each server is spawned as a subprocess over stdio and kept alive for the session.
Credentials are loaded from each server's .env file.

FastMCP 3.x prints a startup banner to stdout before entering the MCP protocol loop.
We suppress it by setting FASTMCP_BANNER=0 in the subprocess environment.
If that doesn't work, we use a wrapper script approach.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import PythonStdioTransport


def _load_env(env_file: str | None) -> dict:
    env = os.environ.copy()
    # Suppress FastMCP's stdout banner — it corrupts the stdio MCP protocol
    env["FASTMCP_SHOW_SERVER_BANNER"] = "false"
    env["FASTMCP_LOG_LEVEL"] = "WARNING"
    # Redirect FastMCP's rich console output to stderr
    env["FASTMCP_RICH_TRACEBACKS"] = "0"
    # AnyIO/uvicorn quiet mode
    env["PYTHONUTF8"] = "1"

    if not env_file:
        return env
    path = Path(env_file)
    if not path.exists():
        print(f"[MCP] WARNING: env_file not found: {path}")
        return env
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def _mcp_tool_to_ollama(tool, server_name: str = "") -> dict:
    schema = {}
    if hasattr(tool, "parameters") and tool.parameters:
        schema = tool.parameters if isinstance(tool.parameters, dict) else {}
    elif hasattr(tool, "inputSchema") and tool.inputSchema:
        schema = tool.inputSchema if isinstance(tool.inputSchema, dict) else {}
    prefixed_name = f"{server_name}_{tool.name}" if server_name else tool.name
    label = f"[{server_name.upper()} ONLY] " if server_name else ""
    description = f"{label}{tool.description or ''}"
    return {
        "type": "function",
        "function": {
            "name": prefixed_name,
            "description": description,
            "parameters": schema,
        },
    }


@dataclass
class MCPConnection:
    name: str
    client: Client
    tools: list[dict]


@dataclass
class MCPRegistry:
    connections: dict[str, MCPConnection] = field(default_factory=dict)
    tool_index: dict[str, str] = field(default_factory=dict)

    def all_tools(self) -> list[dict]:
        tools = []
        for conn in self.connections.values():
            tools.extend(conn.tools)
        return tools

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        server_name = self.tool_index.get(tool_name)
        if not server_name:
            return json.dumps({"success": False, "message": f"Unknown tool: {tool_name}"})
        conn = self.connections[server_name]
        # Strip the server prefix to get the name the MCP server actually registered
        prefix = f"{server_name}_"
        actual_tool_name = tool_name[len(prefix):] if tool_name.startswith(prefix) else tool_name
        try:
            result = await conn.client.call_tool(actual_tool_name, arguments)
            # FastMCP 3.x returns a CallToolResult object with a .content list
            parts = []
            content = result.content if hasattr(result, "content") else result
            if hasattr(content, "__iter__") and not isinstance(content, str):
                for block in content:
                    if hasattr(block, "text"):
                        parts.append(block.text)
                    elif isinstance(block, str):
                        parts.append(block)
            elif isinstance(content, str):
                parts.append(content)
            elif hasattr(result, "text"):
                parts.append(result.text)
            return "\n".join(parts) if parts else json.dumps({"success": True})
        except Exception as e:
            return json.dumps({"success": False, "message": str(e)})


class _ServerHandle:
    def __init__(self):
        self.ready = asyncio.Event()
        self.name: str = ""
        self.client: Client | None = None
        self.tools: list[dict] = []


async def _run_server(cfg_entry: dict, handle: _ServerHandle) -> None:
    name = cfg_entry["name"]
    handle.name = name
    command = cfg_entry["command"]
    args = cfg_entry.get("args", [])
    env = _load_env(cfg_entry.get("env_file"))

    try:
        transport = PythonStdioTransport(
            script_path=args[0],
            python_cmd=command,
            env=env,
        )
        client = Client(transport)

        async with client:
            tools_result = await asyncio.wait_for(client.list_tools(), timeout=30.0)
            handle.tools = [_mcp_tool_to_ollama(t, name) for t in tools_result]
            handle.client = client
            handle.ready.set()
            print(f"[MCP:{name}] Connected. {len(handle.tools)} tools loaded.")
            await asyncio.get_event_loop().create_future()

    except asyncio.TimeoutError:
        print(f"[MCP:{name}] ERROR: Timed out listing tools.")
        handle.ready.set()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[MCP:{name}] ERROR: {type(e).__name__}: {e}")
        handle.ready.set()


async def build_registry(mcp_server_configs: list[dict]) -> MCPRegistry:
    registry = MCPRegistry()
    handles: list[_ServerHandle] = []

    for entry in mcp_server_configs:
        handle = _ServerHandle()
        handles.append(handle)
        asyncio.create_task(_run_server(entry, handle))

    for handle in handles:
        try:
            await asyncio.wait_for(handle.ready.wait(), timeout=45.0)
        except asyncio.TimeoutError:
            print(f"[MCP:{handle.name}] ERROR: Startup timed out.")

    for handle in handles:
        if handle.client is not None:
            conn = MCPConnection(
                name=handle.name,
                client=handle.client,
                tools=handle.tools,
            )
            registry.connections[handle.name] = conn
            for tool in handle.tools:
                registry.tool_index[tool["function"]["name"]] = handle.name

    total = sum(len(c.tools) for c in registry.connections.values())
    if registry.connections:
        print(f"[MCP] Registry ready: {len(registry.connections)} server(s), {total} tools total.")
    else:
        print("[MCP] WARNING: No MCP servers connected. Running in plain chat mode.")

    return registry


class SessionManager:
    def __init__(self):
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self.registry: MCPRegistry | None = None

    def start(self, mcp_server_configs: list[dict]) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        future = asyncio.run_coroutine_threadsafe(
            build_registry(mcp_server_configs), self._loop
        )
        self.registry = future.result(timeout=90)

    def _run_loop(self):
        self._loop.run_forever()

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        if not self.registry:
            return json.dumps({"success": False, "message": "MCP registry not initialised"})
        future = asyncio.run_coroutine_threadsafe(
            self.registry.call_tool(tool_name, arguments), self._loop
        )
        return future.result(timeout=30)

    def all_tools(self) -> list[dict]:
        if not self.registry:
            return []
        return self.registry.all_tools()
