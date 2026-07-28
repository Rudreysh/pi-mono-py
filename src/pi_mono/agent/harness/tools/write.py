"""Write tool for the agent harness."""

from __future__ import annotations

from typing import Any

from pi_mono.agent.harness.types import get_or_throw
from pi_mono.agent.types import AgentToolResult, AgentToolUpdateCallback
from pi_mono.utils.abort_signals import AbortSignal

from .file_mutation_queue import with_file_mutation_queue
from .path_utils import resolve_tool_path
from .tool_context import ExecutionToolContext

WRITE_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Path to the file to write (relative or absolute)"},
        "content": {"type": "string", "description": "Content to write to the file"},
    },
    "required": ["path", "content"],
}


def create_write_tool() -> Any:
    """Create a write tool that writes files via context.env."""

    class WriteTool:
        name = "write"
        label = "write"
        description = (
            "Write content to a file. Creates the file if it doesn't exist, overwrites if it does. "
            "Automatically creates parent directories."
        )
        parameters = WRITE_PARAMETERS
        executionMode = None

        async def execute(
            self,
            tool_call_id: str,
            params: dict[str, Any],
            signal: AbortSignal | None = None,
            on_update: AgentToolUpdateCallback | None = None,
            context: ExecutionToolContext | None = None,
        ) -> AgentToolResult:
            if context is None:
                raise RuntimeError("WriteTool requires an ExecutionToolContext")
            env = context.env
            path = params["path"]
            content = params["content"]

            absolute_path = await resolve_tool_path(env, path, signal)

            async def run() -> AgentToolResult:
                if signal is not None and getattr(signal, "aborted", False):
                    raise RuntimeError("Operation aborted")
                get_or_throw(await env.writeFile(absolute_path, content, signal))
                if signal is not None and getattr(signal, "aborted", False):
                    raise RuntimeError("Operation aborted")
                return {
                    "content": [{"type": "text", "text": f"Successfully wrote {len(content)} bytes to {path}"}],
                    "details": None,
                }

            return await with_file_mutation_queue(env, absolute_path, run)

    return WriteTool()
