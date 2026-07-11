import asyncio
from unittest.mock import MagicMock

import pytest

from pi_mono.ai.providers.faux import faux_assistant_message, faux_tool_call, register_faux_provider
from pi_mono.coding_agent.core.agent_session import AgentSessionRuntime, PromptOptions
from pi_mono.coding_agent.core.sdk import CreateAgentSessionOptions, create_agent_session
from pi_mono.core.auth_storage import AuthStorage
from pi_mono.core.model_registry import ModelRegistry
from pi_mono.core.session_manager import SessionManager
from pi_mono.coding_agent.modes.interactive.interactive_mode import (
    InteractiveMode,
    InteractiveModeOptions,
)
from pi_mono.tui.tui import Container


@pytest.mark.anyio
async def test_interactive_mode_instantiation(tmp_path):
    result = await create_agent_session(
        CreateAgentSessionOptions(
            cwd=str(tmp_path),
            session_manager=SessionManager.in_memory(str(tmp_path)),
        )
    )
    session = result.session
    runtime = AgentSessionRuntime(session=session, services={}, diagnostics=[])
    mode = InteractiveMode(
        runtime,
        InteractiveModeOptions(theme_name="dark", verbose=False),
    )

    assert mode.session is runtime.session
    assert mode._ui is None
    assert not mode._is_initialized


@pytest.mark.anyio
async def test_interactive_mode_tool_loop_with_faux(tmp_path):
    faux = register_faux_provider({"provider": "faux", "api": "faux"})
    try:
        (tmp_path / "pyproject.toml").write_text('name = "pi-mono-python"\n', encoding="utf-8")
        faux.set_responses(
            [
                faux_assistant_message(
                    faux_tool_call("read", {"path": "pyproject.toml"}),
                    options={"stopReason": "toolUse"},
                ),
                faux_assistant_message("The project name is pi-mono-python"),
            ]
        )
        model = faux.get_model()
        assert model is not None

        auth_storage = AuthStorage.create()
        auth_storage.set_runtime_api_key("faux", "test-key")
        model_registry = ModelRegistry.create(auth_storage)

        result = await create_agent_session(
            CreateAgentSessionOptions(
                cwd=str(tmp_path),
                session_manager=SessionManager.in_memory(str(tmp_path)),
                model=model,
                auth_storage=auth_storage,
                model_registry=model_registry,
                no_extensions=True,
            )
        )
        runtime = AgentSessionRuntime(session=result.session, services={}, diagnostics=[])
        mode = InteractiveMode(runtime, InteractiveModeOptions(theme_name="dark", verbose=False))
        mode._chat_container = Container()
        mode._status_container = Container()
        mode._ui = MagicMock()
        events: list[str] = []
        original_handler = mode._handle_session_event

        def capture_events(event):
            events.append(event["type"])
            original_handler(event)

        mode._handle_session_event = capture_events  # type: ignore[method-assign]
        mode._session.subscribe(mode._handle_session_event)

        await mode._session.prompt(
            "Read pyproject.toml and report the name field",
            PromptOptions(),
        )
        while mode.session.is_streaming:
            await asyncio.sleep(0.01)

        assistant_texts = [
            block.get("text", "")
            for message in mode.session.agent.state.messages
            if message.get("role") == "assistant"
            for block in message.get("content", [])
            if block.get("type") == "text"
        ]
        tool_results = [
            message
            for message in mode.session.agent.state.messages
            if message.get("role") == "toolResult"
        ]

        assert "tool_execution_start" in events
        assert len(tool_results) == 1
        assert any("pi-mono-python" in text for text in assistant_texts)
    finally:
        faux.unregister()


@pytest.mark.anyio
async def test_handle_prompt_records_editor_history(tmp_path):
    result = await create_agent_session(
        CreateAgentSessionOptions(
            cwd=str(tmp_path),
            session_manager=SessionManager.in_memory(str(tmp_path)),
            no_extensions=True,
        )
    )
    runtime = AgentSessionRuntime(session=result.session, services={}, diagnostics=[])
    mode = InteractiveMode(runtime, InteractiveModeOptions(theme_name="dark", verbose=False))

    class _FakeTheme:
        border_color = staticmethod(lambda text: text)

    class _FakeTui:
        class terminal:
            rows = 24

        def request_render(self) -> None:
            return None

    from pi_mono.tui.components.editor import Editor, EditorOptions

    editor = Editor(_FakeTui(), _FakeTheme(), EditorOptions())
    editor.focused = True
    mode._editor = editor  # type: ignore[assignment]

    mode._session.prompt = lambda text, options=None: asyncio.sleep(0)  # type: ignore[method-assign,assignment]

    await mode._handle_prompt("first prompt")
    await mode._handle_prompt("second prompt")

    editor.handle_input("\x1b[A")
    assert editor.get_text() == "second prompt"
    editor.handle_input("\x1b[A")
    assert editor.get_text() == "first prompt"
    editor.handle_input("\x1b[B")
    assert editor.get_text() == "second prompt"
