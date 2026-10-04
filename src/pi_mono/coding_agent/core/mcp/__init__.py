"""In-process MCP host over stdio JSON-RPC 2.0."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class McpToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    server_name: str = ""


class McpClient:
    """Stdio MCP client.

    Speaks JSON-RPC 2.0 newline-delimited messages with a child process, matching
    the TypeScript in-process host's stdio transport at a usable subset.
    """

    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._next_id = 1
        self._reader_task: asyncio.Task[None] | None = None
        self._server_name = ""

    @property
    def is_connected(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def connect(self, config: dict[str, Any]) -> None:
        command = config.get("command")
        if not command:
            raise ValueError("MCP config requires a command")
        args = list(config.get("args") or [])
        self._server_name = str(config.get("name") or command)
        self._process = await asyncio.create_subprocess_exec(
            command,
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self._reader_task = asyncio.create_task(self._read_loop())
        await self._rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}})
        await self._notify("notifications/initialized", {})

    async def disconnect(self) -> None:
        if self._process is None:
            return
        if self._process.stdin:
            self._process.stdin.close()
        try:
            await asyncio.wait_for(self._process.wait(), timeout=2)
        except TimeoutError:
            self._process.kill()
            await self._process.wait()
        self._process = None
        if self._reader_task is not None:
            self._reader_task.cancel()
            self._reader_task = None

    async def list_tools(self) -> list[McpToolDefinition]:
        result = await self._rpc("tools/list", {})
        tools = result.get("tools") if isinstance(result, dict) else None
        if not isinstance(tools, list):
            return []
        definitions: list[McpToolDefinition] = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            definitions.append(
                McpToolDefinition(
                    name=str(tool.get("name") or ""),
                    description=str(tool.get("description") or ""),
                    parameters=tool.get("inputSchema") or {},
                    server_name=self._server_name,
                )
            )
        return definitions

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        return await self._rpc("tools/call", {"name": name, "arguments": arguments})

    async def _rpc(self, method: str, params: dict[str, Any]) -> Any:
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("MCP client is not connected")
        request_id = self._next_id
        self._next_id += 1
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        self._process.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
        await self._process.stdin.drain()
        return await future

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        if self._process is None or self._process.stdin is None:
            return
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        self._process.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
        await self._process.stdin.drain()

    async def _read_loop(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        while True:
            line = await self._process.stdout.readline()
            if not line:
                return
            try:
                message = json.loads(line.decode("utf-8"))
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict) or "id" not in message:
                continue
            pending = self._pending.pop(int(message["id"]), None)
            if pending is None:
                continue
            if "error" in message:
                pending.set_exception(RuntimeError(str(message["error"])))
            else:
                pending.set_result(message.get("result"))


class McpManager:
    def __init__(self) -> None:
        self._clients: dict[str, McpClient] = {}

    async def add(self, name: str, config: dict[str, Any]) -> McpClient:
        client = McpClient()
        await client.connect({**config, "name": name})
        self._clients[name] = client
        return client

    async def close(self) -> None:
        for client in self._clients.values():
            await client.disconnect()
        self._clients.clear()

    def clients(self) -> list[McpClient]:
        return list(self._clients.values())
