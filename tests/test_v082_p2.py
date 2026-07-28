"""Smoke tests for v0.82 P2 Python ports."""

from __future__ import annotations

import pytest


class TestStreamOptionsFetch:
    def test_fetch_field_accepted(self) -> None:
        from pi_mono.ai.types import StreamOptions

        def custom_fetch(*args, **kwargs):
            pass

        opts: StreamOptions = {"fetch": custom_fetch}
        assert opts["fetch"] is custom_fetch

    def test_fetch_field_optional(self) -> None:
        from pi_mono.ai.types import StreamOptions

        opts: StreamOptions = {"temperature": 0.5}
        assert "fetch" not in opts

    def test_simple_stream_options_inherits_fetch(self) -> None:
        from pi_mono.ai.types import SimpleStreamOptions

        def custom_fetch(*args, **kwargs):
            pass

        opts: SimpleStreamOptions = {"fetch": custom_fetch, "reasoning": "high"}
        assert opts["fetch"] is custom_fetch


class TestResolveHttpxClient:
    def test_returns_default_when_no_options(self) -> None:
        from pi_mono.ai.utils.http_client import resolve_httpx_client

        sentinel = object()
        assert resolve_httpx_client(None, sentinel) is sentinel

    def test_returns_default_when_no_fetch(self) -> None:
        from pi_mono.ai.utils.http_client import resolve_httpx_client

        sentinel = object()
        assert resolve_httpx_client({}, sentinel) is sentinel

    def test_returns_default_for_non_httpx_callable(self) -> None:
        from pi_mono.ai.utils.http_client import resolve_httpx_client

        sentinel = object()
        result = resolve_httpx_client({"fetch": lambda: None}, sentinel)
        assert result is sentinel

    def test_returns_httpx_client(self) -> None:
        httpx = pytest.importorskip("httpx")
        from pi_mono.ai.utils.http_client import resolve_httpx_client

        client = httpx.AsyncClient()
        result = resolve_httpx_client({"fetch": client})
        assert result is client


class TestToolResultMessageUsage:
    def test_usage_field_optional(self) -> None:
        from pi_mono.ai.types import ToolResultMessage

        msg: ToolResultMessage = {
            "role": "toolResult",
            "toolCallId": "c1",
            "toolName": "t",
            "content": [],
        }
        assert "usage" not in msg

    def test_usage_field_present(self) -> None:
        from pi_mono.ai.types import ToolResultMessage, Usage

        usage: Usage = {
            "input": 10,
            "output": 5,
            "cacheRead": 0,
            "cacheWrite": 0,
            "totalTokens": 15,
            "cost": {
                "input": 0.001,
                "output": 0.0005,
                "cacheRead": 0.0,
                "cacheWrite": 0.0,
                "total": 0.0015,
            },
        }
        msg: ToolResultMessage = {
            "role": "toolResult",
            "toolCallId": "c1",
            "toolName": "t",
            "content": [],
            "usage": usage,
        }
        assert msg["usage"]["totalTokens"] == 15


class TestTuiLogDir:
    def test_get_agent_log_dir_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        from pi_mono.tui.tui import _get_agent_log_dir

        result = _get_agent_log_dir()
        assert str(result).endswith("agent")

    def test_get_agent_log_dir_env_override(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: object
    ) -> None:
        import pathlib

        monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path))
        from pi_mono.tui.tui import _get_agent_log_dir

        result = _get_agent_log_dir()
        assert result == pathlib.Path(str(tmp_path)).resolve()


class TestAppMessageCopyKeybinding:
    def test_keybinding_registered(self) -> None:
        from pi_mono.coding_agent.core.keybindings import APP_KEYBINDINGS

        assert "app.message.copy" in APP_KEYBINDINGS

    def test_keybinding_default_key(self) -> None:
        from pi_mono.coding_agent.core.keybindings import APP_KEYBINDINGS

        defn = APP_KEYBINDINGS["app.message.copy"]
        assert defn.default_keys == "ctrl+x"

    def test_in_default_app_keybindings(self) -> None:
        from pi_mono.coding_agent.core.keybindings import DEFAULT_APP_KEYBINDINGS

        assert "app.message.copy" in DEFAULT_APP_KEYBINDINGS


class TestEvalsStub:
    def test_eval_harness_import(self) -> None:
        from pi_mono.evals import EvalHarness

        harness = EvalHarness(name="test")
        assert harness.name == "test"

    def test_eval_harness_add_case(self) -> None:
        from pi_mono.evals import EvalCase, EvalHarness

        harness = EvalHarness()
        harness.add_case(EvalCase(name="c1", prompt="hello"))
        assert len(harness.cases) == 1
        assert harness.cases[0].name == "c1"

    @pytest.mark.anyio
    async def test_eval_harness_run_raises(self) -> None:
        from pi_mono.evals import EvalHarness

        harness = EvalHarness()
        with pytest.raises(NotImplementedError, match="placeholder"):
            await harness.run()


class TestNarrowTerminalScrollGuard:
    def test_select_list_render_zero_width(self) -> None:
        """Rendering a select list with width=0 should not crash."""
        from pi_mono.tui.components.select_list import SelectItem, SelectList, SelectListTheme

        stub_theme = SelectListTheme(
            selected_prefix=lambda t: t,
            selected_text=lambda t: t,
            description=lambda t: t,
            scroll_info=lambda t: t,
            no_match=lambda t: t,
        )
        items = [SelectItem(label=f"item{i}", value=str(i)) for i in range(20)]
        slist = SelectList(items=items, theme=stub_theme, max_visible=5)
        result = slist.render(0)
        assert isinstance(result, list)
