"""Bash tool for the agent harness."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Coroutine

from pi_mono.agent.harness.types import ExecutionEnv, get_or_throw
from pi_mono.agent.harness.utils.shell_output import executeShellWithCapture
from pi_mono.agent.harness.utils.truncate import DEFAULT_MAX_BYTES, DEFAULT_MAX_LINES, formatSize
from pi_mono.agent.types import AgentToolResult, AgentToolUpdateCallback
from pi_mono.utils.abort_signals import AbortSignal

from .tool_context import ExecutionToolContext

MAX_TIMEOUT_SECONDS = 2_147_483_647 / 1000

BASH_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "Bash command to execute"},
        "timeout": {"type": "number", "description": "Timeout in seconds (optional, no default timeout)"},
    },
    "required": ["command"],
}


@dataclass
class BashToolDetails:
    truncation: dict[str, Any] | None = None
    full_output_path: str | None = None


@dataclass
class BashExecution:
    command: str
    cwd: str
    env: dict[str, str]
    inherit_env: bool


BashPrepare = Callable[
    ["BashExecution", ExecutionToolContext, AbortSignal | None],
    Coroutine[Any, Any, None] | None,
]


@dataclass
class BashToolOptions:
    command_prefix: str | None = None
    prepare: BashPrepare | None = None


def _validate_timeout(timeout: float | None) -> None:
    if timeout is None:
        return
    if not isinstance(timeout, (int, float)) or timeout != timeout or timeout <= 0:
        raise ValueError("Invalid timeout: must be a finite number of seconds")
    if timeout > MAX_TIMEOUT_SECONDS:
        raise ValueError(f"Invalid timeout: maximum is {MAX_TIMEOUT_SECONDS} seconds")


def create_bash_tool(options: BashToolOptions | None = None) -> Any:
    """Create a bash tool that executes commands via context.env."""
    opts = options or BashToolOptions()

    class BashTool:
        name = "bash"
        label = "bash"
        description = (
            f"Execute a bash command in the current working directory. Returns stdout and stderr. "
            f"Output is truncated to last {DEFAULT_MAX_LINES} lines or "
            f"{DEFAULT_MAX_BYTES // 1024}KB (whichever is hit first). "
            f"If truncated, full output is saved to a temp file. "
            f"Optionally provide a timeout in seconds."
        )
        parameters = BASH_PARAMETERS
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
                raise RuntimeError("BashTool requires an ExecutionToolContext")
            command = params["command"]
            timeout = params.get("timeout")
            _validate_timeout(timeout)

            env = context.env
            execution = BashExecution(
                command=f"{opts.command_prefix}\n{command}" if opts.command_prefix else command,
                cwd=env.cwd,
                env={},
                inherit_env=True,
            )

            if opts.prepare is not None:
                result = opts.prepare(execution, context, signal)
                if result is not None:
                    await result

            if on_update is not None:
                on_update({"content": []})

            capture_options: dict[str, Any] = {
                "cwd": execution.cwd,
            }
            if execution.env:
                capture_options["env"] = execution.env
            if timeout is not None:
                capture_options["timeout"] = timeout
            if signal is not None:
                capture_options["abortSignal"] = signal

            result = get_or_throw(
                await executeShellWithCapture(env, execution.command, capture_options)
            )

            output_text = result.get("output", "") or "(no output)"
            details: dict[str, Any] | None = None

            if result.get("truncated"):
                full_output_path = result.get("fullOutputPath")
                details = {"truncation": True, "fullOutputPath": full_output_path}
                if full_output_path:
                    output_text += f"\n\n[Output truncated. Full output: {full_output_path}]"

            def append_status(status: str) -> str:
                return f"{output_text}\n\n{status}" if output_text else status

            if result.get("cancelled"):
                raise RuntimeError(append_status("Command aborted"))

            exit_code = result.get("exitCode")
            if exit_code is not None and exit_code != 0:
                raise RuntimeError(append_status(f"Command exited with code {exit_code}"))

            return {"content": [{"type": "text", "text": output_text}], "details": details}

    return BashTool()
