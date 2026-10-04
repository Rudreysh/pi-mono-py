"""PowerShell tool (Windows)."""

from __future__ import annotations

from typing import Any

from pi_mono.agent.types import AgentTool, AgentToolResult
from pi_mono.coding_agent.core.tools.bash import BashToolOptions, LocalBashOperations, execute_bash
from pi_mono.coding_agent.core.tools.path_utils import resolve_execution_cwd
from pi_mono.coding_agent.core.tools.truncate import DEFAULT_MAX_BYTES
from pi_mono.utils.shell import get_powershell_config

UTF8_OUTPUT_PREFIX = "try { [Console]::OutputEncoding=[System.Text.Encoding]::UTF8 } catch {}\n"

POWERSHELL_TOOL_SYSTEM_PROMPT_CONTRIBUTION = {
    "snippet": "Execute PowerShell commands",
    "guidelines": [
        "You can inspect PI_* environment variables for current model and session details."
    ],
}


def create_local_powershell_operations() -> LocalBashOperations:
    return LocalBashOperations(config_factory=get_powershell_config)


class PowerShellToolOptions(BashToolOptions):
    pass


def create_powershell_tool(cwd: str, options: PowerShellToolOptions | None = None) -> AgentTool:
    opts = options or PowerShellToolOptions()
    if opts.operations is None:
        opts = PowerShellToolOptions(
            operations=create_local_powershell_operations(),
            command_prefix=UTF8_OUTPUT_PREFIX.rstrip("\n"),
        )
    elif opts.command_prefix is None:
        opts = PowerShellToolOptions(
            operations=opts.operations,
            command_prefix=UTF8_OUTPUT_PREFIX.rstrip("\n"),
        )

    class PowerShellTool:
        name = "powershell"
        label = "powershell"
        description = (
            "Execute a PowerShell command in the current working directory. "
            "Returns stdout and stderr. "
            f"Output is truncated to last lines or {DEFAULT_MAX_BYTES // 1024}KB "
            "(whichever is hit first). If truncated, full output is saved to a temp file."
        )
        parameters = {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "PowerShell command to execute"},
                "timeout": {"type": "number", "description": "Timeout in seconds (optional)"},
            },
            "required": ["command"],
        }
        executionMode = None
        prompt_snippet = POWERSHELL_TOOL_SYSTEM_PROMPT_CONTRIBUTION["snippet"]
        prompt_guidelines = POWERSHELL_TOOL_SYSTEM_PROMPT_CONTRIBUTION["guidelines"]

        async def execute(
            self,
            tool_call_id: str,
            params: dict[str, Any],
            signal: Any = None,
            on_update: Any = None,
            ctx: Any = None,
        ) -> AgentToolResult:
            del tool_call_id, on_update
            return await execute_bash(
                resolve_execution_cwd(cwd, ctx),
                params["command"],
                timeout=params.get("timeout"),
                options=opts,
                signal=signal,
            )

    return PowerShellTool()  # type: ignore[return-value]
