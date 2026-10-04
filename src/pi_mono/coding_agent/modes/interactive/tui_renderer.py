"""Composition root for interactive TUI renderers."""

from __future__ import annotations

from typing import Callable, Union

from pi_mono.tui.terminal import ProcessTerminal
from pi_mono.tui.tui import TUI, Terminal
from pi_mono.tui.tui_alt_screen import TuiAltScreen


class InteractiveTuiOptions:
    def __init__(
        self,
        *,
        tui_mode: str = "regular",
        show_hardware_cursor: bool = True,
        log_directory: str | None = None,
        terminal: Terminal | None = None,
        on_right_click_paste: Callable[[], None] | None = None,
        fullscreen_copy_on_select: bool = True,
        scroll_to_end_indicator: Callable[[], str] | None = None,
    ) -> None:
        self.tui_mode = tui_mode
        self.show_hardware_cursor = show_hardware_cursor
        self.log_directory = log_directory
        self.terminal = terminal
        self.on_right_click_paste = on_right_click_paste
        self.fullscreen_copy_on_select = fullscreen_copy_on_select
        self.scroll_to_end_indicator = scroll_to_end_indicator


def create_interactive_tui(options: InteractiveTuiOptions) -> TUI:
    terminal = options.terminal or ProcessTerminal()
    if options.tui_mode == "fullscreen":
        return TuiAltScreen(
            terminal,
            options.show_hardware_cursor,
            options.log_directory,
            copy_on_select=options.fullscreen_copy_on_select,
            on_right_click_paste=options.on_right_click_paste,
            scroll_to_end_indicator=options.scroll_to_end_indicator,
        )
    return TUI(terminal, show_hardware_cursor=options.show_hardware_cursor)


def create_interactive_tui_reference(get_tui: Callable[[], TUI]) -> TUI:
    class _TuiProxy:
        def __getattr__(self, name: str) -> object:
            return getattr(get_tui(), name)

        def __setattr__(self, name: str, value: object) -> None:
            if name.startswith("_"):
                object.__setattr__(self, name, value)
                return
            setattr(get_tui(), name, value)

    return _TuiProxy()  # type: ignore[return-value]


TuiRenderer = Union[TUI, TuiAltScreen]
