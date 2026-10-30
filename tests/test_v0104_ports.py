"""Ports of TypeScript v1.0.3–v1.0.4 behavior."""

from pi_mono.ai.utils.estimate import CHARS_PER_TOKEN, estimate_text_tokens
from pi_mono.ai.utils.retry import is_retryable_assistant_error
from pi_mono.coding_agent.cli.args import parse_args
from pi_mono.coding_agent.cli.tool_flags import (
    apply_tool_modifiers,
    create_tool_name_matcher,
    get_tool_list_error,
)
from pi_mono.tui.keybindings import TUI_KEYBINDINGS


def test_context_estimate_uses_three_and_a_half_characters_per_token() -> None:
    # Issue #10497
    assert CHARS_PER_TOKEN == 3.5
    assert estimate_text_tokens("x" * 7) == 2


def test_server_busy_and_canceled_http2_stream_are_retryable() -> None:
    # Issues #10543 and #10379
    busy = {"stopReason": "error", "errorMessage": "servers are currently busy"}
    canceled = {
        "stopReason": "error",
        "errorMessage": "The pending stream has been canceled",
    }
    assert is_retryable_assistant_error(busy) is True
    assert is_retryable_assistant_error(canceled) is True


def test_mistral_finish_reason_error_is_retryable() -> None:
    # Issue #10487
    msg = {
        "stopReason": "error",
        "errorMessage": "Provider stopped with: error (server error)",
    }
    assert is_retryable_assistant_error(msg) is True


def test_home_and_end_stay_on_the_editor() -> None:
    # Issue #10314
    assert TUI_KEYBINDINGS["tui.editor.cursorLineStart"].default_keys[0] == "home"
    assert TUI_KEYBINDINGS["tui.altScreen.top"].default_keys == "ctrl+home"
    assert TUI_KEYBINDINGS["tui.altScreen.bottom"].default_keys == "ctrl+end"


def test_tool_modifiers_edit_the_defaults() -> None:
    assert apply_tool_modifiers(["read", "bash", "edit", "write"], ["+grep", "-bash"]) == [
        "read",
        "edit",
        "write",
        "grep",
    ]
    assert get_tool_list_error(["read", "+grep"]) == (
        "tool names cannot be mixed with +name or -name entries"
    )
    parsed = parse_args(["--tools", "+grep,-bash", "--no-mcp"])
    assert parsed.tools == ["+grep", "-bash"]
    assert parsed.no_mcp is True
    assert parsed.diagnostics == []


def test_tool_name_patterns() -> None:
    matches = create_tool_name_matcher(["read", "mcp__radius__*"])
    assert matches("read") is True
    assert matches("mcp__radius__search") is True
    assert matches("bash") is False
    error = parse_args(["--tools", "+mcp__*"])
    assert error.tools is None
    assert error.diagnostics[0]["type"] == "error"
