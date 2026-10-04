"""Coverage for remaining TS 0.85 Python gaps."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pi_mono.coding_agent.cli.args import parse_args
from pi_mono.coding_agent.core.extensions.types import Extension
from pi_mono.coding_agent.core.source_info import create_synthetic_source_info
from pi_mono.coding_agent.core.tools import ALL_TOOL_NAMES, create_powershell_tool
from pi_mono.coding_agent.modes.interactive.components.markdown_transform import (
    apply_markdown_transformers,
)
from pi_mono.core.session_manager import SessionManager
from pi_mono.core.settings_manager import SettingsManager
from pi_mono.evals import EvalCase, EvalHarness
from pi_mono.protocol.cbor import decode_cbor, encode_cbor
from pi_mono.protocol.framing import FrameDecoder, encode_frame
from pi_mono.session_backends import SqliteSessionRepo
from pi_mono.tui.terminal_image import (
    detect_capabilities,
    get_capabilities,
    reset_capabilities_cache,
    set_capability_overrides,
)
from pi_mono.tui.tui_alt_screen import TuiAltScreen
from pi_mono.tui.tui import TUI
from pi_mono.utils.pi_user_agent import get_pi_user_agent
from pi_mono.utils.shell import POWERSHELL_ARGS, get_powershell_config


def test_powershell_is_a_builtin_tool():
    assert "powershell" in ALL_TOOL_NAMES
    tool = create_powershell_tool("/tmp")
    assert tool.name == "powershell"
    assert tool.parameters["required"] == ["command"]


def test_powershell_config_is_windows_only():
    if os.name == "nt":
        config = get_powershell_config()
        assert config["args"] == list(POWERSHELL_ARGS)
    else:
        with pytest.raises(RuntimeError, match="only available on Windows"):
            get_powershell_config()


def test_session_manager_in_memory_restores_entries(tmp_path: Path):
    header = {
        "type": "session",
        "version": 3,
        "id": "abc",
        "timestamp": "2026-01-01T00:00:00Z",
        "cwd": str(tmp_path),
    }
    message = {
        "type": "message",
        "id": "m1",
        "timestamp": "2026-01-01T00:00:01Z",
        "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]},
    }
    manager = SessionManager.in_memory(str(tmp_path), entries=[header, message])
    assert manager.sessionId == "abc"
    assert manager.persist is False
    assert any(entry.get("id") == "m1" for entry in manager.file_entries)


def test_markdown_transformers_applied_in_order():
    def prefix(markdown: str, context: dict) -> str:
        del context
        return f"A:{markdown}"

    def suffix(markdown: str, context: dict) -> str:
        del context
        return f"{markdown}:B"

    result = apply_markdown_transformers(
        "x",
        {"messageType": "assistant", "isStreaming": False, "availableWidth": 80},
        [prefix, suffix],
    )
    assert result == "A:x:B"


def test_parse_args_use_theme_and_tui_mode():
    parsed = parse_args(["--use-theme", "light", "--tui-mode", "fullscreen"])
    assert parsed.use_theme == "light"
    assert parsed.tui_mode == "fullscreen"

    missing = parse_args(["--use-theme"])
    assert any("--use-theme requires a theme name" in item["message"] for item in missing.diagnostics)

    invalid = parse_args(["--tui-mode", "other"])
    assert any("Invalid TUI mode" in item["message"] for item in invalid.diagnostics)


def test_settings_tui_mode_roundtrip():
    manager = SettingsManager.in_memory()
    assert manager.get_tui_mode() == "fullscreen"
    manager.set_tui_mode("regular")
    assert manager.get_tui_mode() == "regular"
    assert manager.get_fullscreen_copy_on_select() is True
    manager.set_fullscreen_copy_on_select(False)
    assert manager.get_fullscreen_copy_on_select() is False


def test_capability_env_overrides(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PI_HYPERLINKS", "1")
    monkeypatch.setenv("PI_TRUE_COLOR", "0")
    monkeypatch.setenv("PI_IMAGE_PROTOCOL", "none")
    monkeypatch.delenv("TMUX", raising=False)
    caps = detect_capabilities()
    assert caps.hyperlinks is True
    assert caps.true_color is False
    assert caps.images is None
    reset_capabilities_cache()
    set_capability_overrides(hyperlinks=False, true_color=True, images="kitty")
    overridden = get_capabilities()
    assert overridden.hyperlinks is False
    assert overridden.true_color is True
    assert overridden.images == "kitty"
    reset_capabilities_cache()
    set_capability_overrides()


def test_tui_alt_screen_viewport_clips_and_jumps():
    class FakeTerminal:
        columns = 20
        rows = 3

        def write(self, data: str) -> None:
            del data

        def start(self, on_input, on_resize) -> None:
            del on_input, on_resize

        def stop(self) -> None:
            return None

        def hideCursor(self) -> None:
            return None

        def showCursor(self) -> None:
            return None

    screen = TuiAltScreen(FakeTerminal())  # type: ignore[arg-type]
    clipped = screen._apply_viewport(["a", "b", "c", "d", "e"], 20, 3)
    assert len(clipped) == 3
    assert clipped[-1] in ("c", "d", "e") or "Jump" in clipped[-1]
    screen._scroll_by(10)
    jumped = screen._apply_viewport(["a", "b", "c", "d", "e"], 20, 3)
    assert any("Jump" in line or line == "a" for line in jumped)


def test_apply_tui_mode_reuses_terminal_and_rebinds_editor():
    from unittest.mock import MagicMock

    from pi_mono.coding_agent.modes.interactive.interactive_mode import InteractiveMode

    class FakeTerminal:
        columns = 80
        rows = 24

        def write(self, data: str) -> None:
            del data

        def start(self, on_input, on_resize) -> None:
            del on_input, on_resize

        def stop(self) -> None:
            return None

        def hideCursor(self) -> None:
            return None

        def showCursor(self) -> None:
            return None

    terminal = FakeTerminal()
    old = TUI(terminal)  # type: ignore[arg-type]
    child = MagicMock()
    child.render.return_value = ["ok"]
    child.invalidate = lambda: None
    old.add_child(child)

    mode = InteractiveMode.__new__(InteractiveMode)
    mode._ui = old
    mode._tui_mode = "regular"
    mode._editor = MagicMock()
    mode._theme_controller = MagicMock()
    mode._session = MagicMock()
    mode._session.settings_manager.get_show_hardware_cursor.return_value = True
    mode._session.settings_manager.get_fullscreen_copy_on_select.return_value = True
    mode._session.settings_manager.get_fullscreen_exit_output.return_value = "transcript"
    mode._session.settings_manager.get_fullscreen_scrollbar.return_value = "auto"
    mode._setup_input_handlers = lambda: None

    mode._apply_tui_mode("fullscreen")

    assert mode._ui.terminal is terminal
    assert isinstance(mode._ui, TuiAltScreen)
    assert mode._editor.tui is mode._ui
    mode._theme_controller.rebind_tui.assert_called_once_with(mode._ui)


def test_cbor_and_framing_roundtrip():
    payload = {"type": "hello", "protocolVersion": 8, "nested": [1, True, None]}
    assert decode_cbor(encode_cbor(payload)) == payload
    decoder = FrameDecoder()
    frames = decoder.feed(encode_frame(payload))
    assert frames == [payload]


def test_sqlite_session_repo(tmp_path: Path):
    repo = SqliteSessionRepo(str(tmp_path / "sessions.db"))
    repo.create_session({"id": "s1", "cwd": "/tmp", "timestamp": "t"})
    repo.append_entry("s1", {"id": "e1", "type": "message"})
    entries = repo.load_entries("s1")
    repo.close()
    assert entries[0]["id"] == "e1"


def test_unix_client_server_roundtrip():
    import asyncio
    import os

    from pi_mono.client import connect_unix
    from pi_mono.server import RemoteServer

    socket_path = os.path.join("/tmp", f"pi-proto-{os.getpid()}.sock")

    async def ping(method: str, params: object) -> object:
        del params
        return {"method": method, "ok": True}

    async def _run() -> None:
        if os.path.exists(socket_path):
            os.unlink(socket_path)
        server = RemoteServer(ping)
        await server.start_unix(socket_path)
        try:
            client = await connect_unix(socket_path)
            hello = await client.hello()
            result = await client.request("ping", {"n": 1})
            await client.close()
            assert hello["protocolVersion"] == 8
            assert result == {"method": "ping", "ok": True}
        finally:
            await server.close()
            if os.path.exists(socket_path):
                os.unlink(socket_path)

    asyncio.run(_run())


def test_chord_context_and_replicated_state():
    from pi_mono.chord import ChordContext, ReplicatedState

    ctx = ChordContext()
    ctx.provide("name", "pi")
    assert ctx.get("name") == "pi"
    seen: list[int] = []
    state = ReplicatedState({"n": 1})
    unsub = state.subscribe(lambda value, _ctx, _meta: seen.append(int(value["n"])))
    assert seen == [1]
    state.state["n"] = 2
    state.publish()
    unsub()
    state.state["n"] = 3
    state.publish()
    assert seen == [1, 2]


def test_eval_harness_runs_cases():
    import asyncio

    harness = EvalHarness()
    harness.add_case(EvalCase(name="ok", prompt="hi", expected="ok"))
    results = asyncio.run(harness.run(lambda case: "ok done"))
    assert results[0].passed is True


def test_mcp_stdio_list_tools(tmp_path: Path):
    import asyncio
    import sys

    from pi_mono.coding_agent.core.mcp import McpClient

    server = tmp_path / "mcp_server.py"
    server.write_text(
        "import json, sys\n"
        "for line in sys.stdin:\n"
        "    msg = json.loads(line)\n"
        "    method = msg.get('method')\n"
        "    if method == 'initialize':\n"
        "        print(json.dumps({'jsonrpc':'2.0','id':msg['id'],'result':{'protocolVersion':'2024-11-05'}}), flush=True)\n"
        "    elif method == 'tools/list':\n"
        "        print(json.dumps({'jsonrpc':'2.0','id':msg['id'],'result':{'tools':[{'name':'echo','description':'d','inputSchema':{}}]}}), flush=True)\n"
    )

    async def _run() -> None:
        client = McpClient()
        await client.connect({"command": sys.executable, "args": [str(server)]})
        tools = await client.list_tools()
        await client.disconnect()
        assert [tool.name for tool in tools] == ["echo"]

    asyncio.run(_run())


def test_pi_user_agent_default_matches_ts_shape():
    agent = get_pi_user_agent()
    assert agent.startswith("pi (")
    assert ";" in agent


def test_extension_markdown_transformer_field():
    extension = Extension(
        path="<tmp>",
        resolved_path="<tmp>",
        source_info=create_synthetic_source_info("<tmp>", source="test"),
    )
    assert extension.markdown_transformer is None
    extension.markdown_transformer = lambda markdown, context: markdown.upper()
    assert extension.markdown_transformer("hi", {}) == "HI"
