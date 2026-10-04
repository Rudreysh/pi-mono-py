"""Ports of TypeScript v0.86–v1.0.2 behavior."""

from __future__ import annotations

from pi_mono.ai.providers.simple_options import resolve_sampling_params
from pi_mono.ai.utils.overflow import is_context_overflow
from pi_mono.ai.utils.retry import is_retryable_assistant_error
from pi_mono.coding_agent.cli.args import parse_args
from pi_mono.coding_agent.modes.interactive.components.settings_selector import (
    SettingsConfig,
    build_settings_items,
    handle_settings_change,
)
from pi_mono.core.settings_manager import SettingsManager


def test_models_flag_ignores_empty_entries() -> None:
    # Issue #10334
    parsed = parse_args(["--models", "gpt-4o, ,claude-sonnet,"])
    assert parsed.models == ["gpt-4o", "claude-sonnet"]


def test_zai_cn_prompt_exceeds_max_length_is_overflow() -> None:
    # Issue #10208
    msg = {
        "stopReason": "error",
        "errorMessage": '400 {"code":"1261","message":"Prompt exceeds max length"}',
    }
    assert is_context_overflow(msg) is True


def test_capacity_error_is_retryable() -> None:
    # Issue #10278
    msg = {
        "stopReason": "error",
        "errorMessage": "Selected model is at capacity. Please try again.",
    }
    assert is_retryable_assistant_error(msg) is True


def test_chatgpt_usage_limit_is_not_retryable() -> None:
    msg = {
        "stopReason": "error",
        "errorMessage": "subscription_sharing_usage_limit_exceeded",
    }
    assert is_retryable_assistant_error(msg) is False


def test_sampling_params_by_thinking_level_override_model_defaults() -> None:
    model = {
        "id": "custom",
        "name": "custom",
        "api": "openai-completions",
        "provider": "openai",
        "baseUrl": "https://api.openai.com/v1",
        "reasoning": True,
        "thinkingLevelMap": {"low": "low", "medium": "medium"},
        "samplingParams": {"temperature": 1, "top_p": 0.95},
        "samplingParamsByThinkingLevel": {"low": {"temperature": 0.6, "top_k": 64}},
        "input": ["text"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": 128000,
        "maxTokens": 16384,
    }
    params = resolve_sampling_params(model, "low", {"top_p": 0.5})
    assert params == {"temperature": 0.6, "top_p": 0.5, "top_k": 64}


def test_tui_mode_defaults_to_fullscreen() -> None:
    manager = SettingsManager.in_memory()
    assert manager.get_tui_mode() == "fullscreen"
    manager.set_tui_mode("regular")
    assert manager.get_tui_mode() == "regular"


def test_quiet_startup_header_roundtrip() -> None:
    manager = SettingsManager.in_memory()
    assert manager.get_quiet_startup() is False
    manager.set_quiet_startup("header")
    assert manager.get_quiet_startup() == "header"


def test_quiet_startup_setting_includes_header() -> None:
    config = SettingsConfig(
        auto_compact=True,
        show_images=True,
        steering_mode="all",
        follow_up_mode="one-at-a-time",
        thinking_level="medium",
        available_thinking_levels=["off", "medium"],
        current_theme="dark",
        available_themes=["dark"],
        quiet_startup="header",
    )
    items = {item.id: item for item in build_settings_items(config)}
    assert items["quiet-startup"].values == ["true", "header", "false"]
    assert items["quiet-startup"].current_value == "header"

    calls: dict[str, object] = {}

    class Callbacks:
        def on_quiet_startup_change(self, enabled: bool | str) -> None:
            calls["quiet"] = enabled

        def on_auto_compact_change(self, enabled: bool) -> None: ...
        def on_show_images_change(self, enabled: bool) -> None: ...
        def on_steering_mode_change(self, mode: str) -> None: ...
        def on_follow_up_mode_change(self, mode: str) -> None: ...
        def on_thinking_level_change(self, level: str) -> None: ...
        def on_theme_change(self, theme_name: str) -> None: ...
        def on_theme_preview(self, theme_name: str) -> None: ...
        def on_hide_thinking_block_change(self, hidden: bool) -> None: ...
        def on_show_cache_miss_notices_change(self, show: bool) -> None: ...
        def on_output_pad_change(self, padding: int) -> None: ...
        def on_collapse_changelog_change(self, collapsed: bool) -> None: ...
        def on_tree_filter_mode_change(self, mode: str) -> None: ...
        def on_tui_mode_change(self, mode: str) -> None: ...
        def on_fullscreen_exit_output_change(self, output: str) -> None: ...
        def on_fullscreen_scrollbar_change(self, mode: str) -> None: ...
        def on_fullscreen_copy_on_select_change(self, enabled: bool) -> None: ...
        def on_cancel(self) -> None: ...

    handle_settings_change("quiet-startup", "header", Callbacks())
    assert calls["quiet"] == "header"
