"""Ports after the v1.0.4 tool-selection pass."""

from __future__ import annotations

import asyncio
import time

import pytest

from pi_mono.agent.agent_loop import create_tool_result_message, execute_prepared_tool_call
from pi_mono.ai.providers.azure_openai_responses import (
    _normalize_azure_base_url,
    _prepare_azure_completions,
    stream_azure_openai_completions,
)
from pi_mono.ai.utils.event_stream import AssistantMessageEventStream
from pi_mono.ai.utils.oauth.anthropic import _open_callback_server
from pi_mono.coding_agent.core.system_prompt import build_system_prompt
from pi_mono.coding_agent.modes.interactive.components.bash_execution import format_duration
from pi_mono.coding_agent.modes.interactive.components.tool_execution import _shell_timing_label


def test_azure_foundry_host_and_deployment_name(monkeypatch) -> None:
    normalized = _normalize_azure_base_url("https://example.ai.azure.com/openai/v1/responses")
    assert normalized == "https://example.ai.azure.com/openai/v1"

    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_NAME_MAP", "deepseek-v4-pro=my-deploy")
    model = {
        "id": "deepseek-v4-pro",
        "provider": "azure",
        "api": "openai-completions",
        "baseUrl": "https://example.openai.azure.com",
    }
    resolved, options = _prepare_azure_completions(model, {})
    assert resolved["baseUrl"] == "https://example.openai.azure.com/openai/v1"
    payload = asyncio.run(options["onPayload"]({"model": model["id"]}, model))
    assert payload["model"] == "my-deploy"


def test_assistant_and_tool_duration() -> None:
    asyncio.set_event_loop(asyncio.new_event_loop())
    stream = AssistantMessageEventStream()
    message = {
        "role": "assistant",
        "timestamp": int(time.time() * 1000) + 1000,
        "content": [],
    }
    stream.push({"type": "done", "reason": "stop", "message": message})
    assert message["durationMs"] >= 0

    recorded = create_tool_result_message(
        {
            "toolCall": {"id": "call-1", "name": "bash"},
            "result": {"content": [{"type": "text", "text": "ok"}], "details": {}},
            "isError": False,
            "durationMs": 1500,
        }
    )
    skipped = create_tool_result_message(
        {
            "toolCall": {"id": "call-2", "name": "bash"},
            "result": {"content": [], "details": {}},
            "isError": True,
        }
    )
    assert recorded["durationMs"] == 1500
    assert "durationMs" not in skipped
    assert format_duration(1500) == "1.5s"
    assert format_duration(65_000) == "1m 5s"


def test_hidden_tools_leave_the_prompt() -> None:
    skill = {"name": "demo", "description": "Does demo", "filePath": "/tmp/SKILL.md"}
    prompt = build_system_prompt(
        selected_tools=["read", "bash", "run"],
        hidden_tools=["read", "bash"],
        tool_snippets={"read": "Read files", "bash": "Run commands", "run": "Run a task"},
        cwd="/tmp",
        skills=[skill],
    )
    assert "- run: Run a task" in prompt
    assert "- read: " not in prompt
    assert "Use bash for file operations" not in prompt
    assert "Load a skill's file when the task matches its description." in prompt

    named = build_system_prompt(
        selected_tools=["read", "bash"],
        hidden_tools=["read"],
        tool_snippets={"bash": "Run commands"},
        cwd="/tmp",
        skills=[skill],
    )
    assert "Use bash to load a skill's file" in named


def test_anthropic_login_uses_a_free_port(monkeypatch) -> None:
    calls: list[int] = []

    class FakeServer:
        def __init__(self, address: tuple[str, int], handler: object) -> None:
            del handler
            calls.append(address[1])
            if address[1] == 53692:
                raise OSError("address already in use")
            self.server_address = ("127.0.0.1", 41234)

    monkeypatch.setattr(
        "pi_mono.ai.utils.oauth.anthropic.HTTPServer",
        FakeServer,
    )
    _server, redirect_uri = _open_callback_server(object)  # type: ignore[arg-type]
    assert calls == [53692, 0]
    assert redirect_uri == "http://localhost:41234/callback"


def test_azure_url_and_empty_deployment_match_typescript(monkeypatch) -> None:
    with pytest.raises(ValueError, match="Invalid Azure OpenAI base URL"):
        _normalize_azure_base_url("not a url")
    assert (
        _normalize_azure_base_url("  https://example.openai.azure.com/openai/  ")
        == "https://example.openai.azure.com/openai/v1"
    )

    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_NAME_MAP", "deepseek-v4-pro=")
    model = {
        "id": "deepseek-v4-pro",
        "provider": "azure",
        "api": "openai-completions",
        "baseUrl": "https://example.openai.azure.com",
    }
    _resolved, options = _prepare_azure_completions(model, {})
    assert "onPayload" not in options


def test_missing_azure_endpoint_fails_on_the_stream() -> None:
    asyncio.set_event_loop(asyncio.new_event_loop())
    monkey_env = {
        "AZURE_OPENAI_BASE_URL": "",
        "AZURE_OPENAI_RESOURCE_NAME": "",
    }
    import os

    previous = {name: os.environ.get(name) for name in monkey_env}
    os.environ.update(monkey_env)
    try:
        stream = stream_azure_openai_completions(
            {"id": "gpt-5.4", "provider": "azure", "api": "openai-completions"},
            {"messages": []},
            {},
        )
        message = asyncio.get_event_loop().run_until_complete(stream.result())
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    assert message["stopReason"] == "error"
    assert "base URL is required" in message["errorMessage"]
    assert "durationMs" not in message


def test_thrown_tool_still_records_duration() -> None:
    asyncio.set_event_loop(asyncio.new_event_loop())

    class Tool:
        async def execute(self, _tool_call_id, _args, _signal, _on_update):
            raise RuntimeError("boom")

    outcome = asyncio.get_event_loop().run_until_complete(
        execute_prepared_tool_call(
            {
                "tool": Tool(),
                "toolCall": {"id": "call-1", "name": "bash", "arguments": {}},
                "args": {},
            },
            None,
            lambda _event: None,
        )
    )
    assert outcome["isError"] is True
    assert outcome["durationMs"] >= 0
    assert "boom" in outcome["result"]["content"][0]["text"]


def test_shell_took_prefers_recorded_duration() -> None:
    assert _shell_timing_label(1500, is_partial=False, started_at=0, ended_at=99_000) == "Took 1.5s"
    assert _shell_timing_label(None, is_partial=True, started_at=0, ended_at=None) is not None
    assert _shell_timing_label(None, is_partial=True, started_at=0, ended_at=None).startswith("Elapsed ")
    assert _shell_timing_label(None, is_partial=False, started_at=None, ended_at=None) is None


class _Timer:
    created: list["_Timer"] = []

    def __init__(self, interval: float, function) -> None:
        self.interval = interval
        self.function = function
        self.cancelled = False
        _Timer.created.append(self)

    def start(self) -> None:
        return None

    def cancel(self) -> None:
        self.cancelled = True


def test_elapsed_line_ticks_once_a_second(monkeypatch) -> None:
    from pi_mono.coding_agent.modes.interactive.components import tool_execution

    _Timer.created.clear()
    monkeypatch.setattr(tool_execution.threading, "Timer", _Timer)
    renders: list[int] = []
    component = tool_execution.ToolExecutionComponent("bash", "id", {"command": "ls"}, ui=None)
    component._ui = type("Ui", (), {"request_render": lambda _self: renders.append(1)})()
    component.mark_execution_started()
    assert _Timer.created[-1].interval == 1.0
    _Timer.created[-1].function()
    assert renders == [1]
    assert _Timer.created[-1].interval == 1.0
    component.update_result({"content": [], "isError": False, "durationMs": 10}, is_partial=False)
    assert component._elapsed_timer is None


def test_prepare_loadout_hides_declarations_and_keeps_them_callable() -> None:
    from pi_mono.coding_agent.core.tool_loadout import apply_prepare_loadout

    class Tool:
        def __init__(self, name: str) -> None:
            self.name = name
            self.description = name

    class Definition:
        name = "run"

        def prepare_loadout(self, loadout):
            assert loadout["get_prompt_guidelines"]("read") == ["Read files."]
            return {
                "hiddenDeclarations": ["read", "bash"],
                "descriptions": {"run": "Run the task"},
            }

    tools = [Tool("read"), Tool("bash"), Tool("run")]
    active, hidden = apply_prepare_loadout(tools, {"run": Definition()}, {"read": ["Read files."]})
    assert hidden == {"read", "bash"}
    assert [tool.name for tool in active] == ["read", "bash", "run"]
    assert active[0].hidden_declaration is True
    assert active[2].description == "Run the task"
    prompt = build_system_prompt(
        selected_tools=["read", "bash", "run"],
        hidden_tools=sorted(hidden),
        tool_snippets={"read": "Read files", "bash": "Run commands", "run": "Run a task"},
        cwd="/tmp",
        skills=[{"name": "docs", "description": "Docs", "filePath": "/tmp/SKILL.md"}],
        tool_guidelines={"read": ["Read files."], "run": ["Run carefully."]},
    )
    assert "- read:" not in prompt
    assert "- bash:" not in prompt
    assert "- run:" in prompt
    assert "Read files." not in prompt
    assert "Run carefully." in prompt
    assert "Load a skill's file when the task matches its description." in prompt


def test_mcp_sign_in_cancel_timeout_and_close_without_token() -> None:
    from pi_mono.coding_agent.core.mcp.oauth import (
        McpHttpSession,
        McpOAuthServerError,
        McpSignIn,
        McpSignInCancelledError,
        await_auth_server,
        cancel_active_mcp_sign_ins,
        refresh_or_authorize,
    )
    from pi_mono.utils.abort_signals import AbortController

    async def hang() -> None:
        await asyncio.sleep(30)

    async def scenario() -> None:
        with pytest.raises(TimeoutError, match="timed out after 15 seconds"):
            await await_auth_server(hang(), timeout_s=0.01)

        controller = AbortController()
        controller.abort()
        with pytest.raises(McpSignInCancelledError, match="Sign-in cancelled"):
            await await_auth_server(hang(), controller.signal, timeout_s=5)

        began: list[str] = []

        async def refresh() -> str:
            await asyncio.sleep(30)
            return "token"

        async def begin() -> str:
            began.append("auth")
            return "new"

        live = AbortController()

        async def abort_during_refresh() -> None:
            task = asyncio.create_task(refresh_or_authorize(refresh, begin, live.signal))
            await asyncio.sleep(0.01)
            live.abort()
            with pytest.raises(McpSignInCancelledError):
                await task

        await abort_during_refresh()
        assert began == []

        async def server_error() -> str:
            raise McpOAuthServerError("server_error")

        assert await refresh_or_authorize(server_error, begin, None) == "new"
        assert began == ["auth"]

        calls: list[tuple[str, dict]] = []

        async def fetch(url: str, method: str | None = None, headers: dict | None = None) -> None:
            calls.append((method or "", headers or {}))

        class Auth:
            called = False

            async def token(self) -> str:
                self.called = True
                return "rotated"

        auth = Auth()
        session = McpHttpSession("https://mcp.example/mcp", fetch, auth)
        session.started = True
        session.session_id = "session-1"
        session.note_token("last")
        await session.close()
        assert auth.called is False
        assert calls == [("DELETE", {"Authorization": "Bearer last"})]

        sign_in = McpSignIn()

        async def operation(signal) -> None:
            await await_auth_server(hang(), signal, timeout_s=5)

        async def press_escape() -> None:
            await asyncio.sleep(0.01)
            assert sign_in.handle_key("escape") is True

        with pytest.raises(McpSignInCancelledError):
            await asyncio.gather(sign_in.run(operation), press_escape())

        waiting = McpSignIn()

        async def parked(_signal) -> None:
            await asyncio.sleep(30)

        parked_task = asyncio.create_task(waiting.run(parked))
        await asyncio.sleep(0.01)
        cancel_active_mcp_sign_ins()
        with pytest.raises(McpSignInCancelledError):
            await parked_task

    asyncio.run(scenario())
