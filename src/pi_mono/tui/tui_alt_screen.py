"""Fullscreen alt-screen TUI.

Ported from TypeScript `packages/tui/src/tui-alt-screen.ts` as a working subset:
alt-screen buffer, viewport scrolling, jump-to-latest, and transcript search.
"""

from __future__ import annotations

import re
from typing import Any, Callable, List, Optional

from pi_mono.tui.keybindings import get_keybindings
from pi_mono.tui.keys import is_key_release, matches_key
from pi_mono.tui.tui import TUI, Terminal
from pi_mono.tui.utils import visible_width

ENTER_ALT_SCREEN = "\x1b[?1049h"
EXIT_ALT_SCREEN = "\x1b[?1049l"
DISABLE_AUTOWRAP = "\x1b[?7l"
ENABLE_AUTOWRAP = "\x1b[?7h"
ENABLE_BUTTON_MOTION_MOUSE = "\x1b[?1000h\x1b[?1002h\x1b[?1004h\x1b[?1006h"
DISABLE_MOUSE = "\x1b[?1006l\x1b[?1004l\x1b[?1003l\x1b[?1002l\x1b[?1000l"
PAGE_SCROLL_OVERLAP = 4
SGR_MOUSE = re.compile(r"\x1b\[<(\d+);(\d+);(\d+)([Mm])")


class TuiAltScreen(TUI):
    """Terminal-height viewport rendered in the alternate screen buffer."""

    def __init__(
        self,
        terminal: Terminal,
        show_hardware_cursor: Optional[bool] = None,
        log_directory: str | None = None,
        *,
        search_match_style: Callable[[str], str] | None = None,
        search_current_match_style: Callable[[str], str] | None = None,
        scroll_to_end_indicator: Callable[[], str] | None = None,
        copy_on_select: bool = True,
        copy_selection: Callable[[str], Any] | None = None,
        open_url: Callable[[str], Any] | None = None,
        on_right_click_paste: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(terminal, show_hardware_cursor)
        self.mode = "fullscreen"
        del log_directory
        self._alt_screen_active = False
        self._scroll_offset = 0
        self._document_lines: List[str] = []
        self._search_query = ""
        self._search_open = False
        self._search_index = 0
        self._copy_on_select = copy_on_select
        self._copy_selection = copy_selection
        self._open_url = open_url
        self._on_right_click_paste = on_right_click_paste
        self._exit_output = "transcript"
        self._scrollbar = "auto"
        self._search_match_style = search_match_style or (lambda text: text)
        self._search_current_match_style = search_current_match_style or (lambda text: text)
        self._scroll_to_end_indicator = scroll_to_end_indicator

    def set_copy_on_select(self, enabled: bool) -> None:
        self._copy_on_select = enabled

    def set_exit_output(self, output: str) -> None:
        self._exit_output = output

    def set_scrollbar(self, mode: str) -> None:
        self._scrollbar = mode

    def start(self) -> None:
        self.terminal.write(ENTER_ALT_SCREEN + DISABLE_AUTOWRAP + ENABLE_BUTTON_MOTION_MOUSE)
        self._alt_screen_active = True
        super().start()

    def stop(self, preserve_screen: bool = False) -> None:
        if self._alt_screen_active:
            self.terminal.write(DISABLE_MOUSE + ENABLE_AUTOWRAP + EXIT_ALT_SCREEN)
            self._alt_screen_active = False
        super().stop(preserve_screen=preserve_screen)

    def handle_input(self, data: str) -> None:
        if self._handle_mouse(data):
            return
        if is_key_release(data):
            super().handle_input(data)
            return
        keybindings = get_keybindings()
        if self._search_open:
            if keybindings.matches(data, "tui.altScreen.searchClose") or matches_key(data, "escape"):
                self._search_open = False
                self._search_query = ""
                self.request_render()
                return
            if keybindings.matches(data, "tui.altScreen.searchNext"):
                self._search_index += 1
                self.request_render()
                return
            if keybindings.matches(data, "tui.altScreen.searchPrevious"):
                self._search_index -= 1
                self.request_render()
                return
            if data in ("\x7f", "\b"):
                self._search_query = self._search_query[:-1]
                self.request_render()
                return
            if len(data) == 1 and data.isprintable():
                self._search_query += data
                self.request_render()
                return
        if keybindings.matches(data, "tui.altScreen.search"):
            self._search_open = True
            self._search_query = ""
            self._search_index = 0
            self.request_render()
            return
        if keybindings.matches(data, "tui.altScreen.pageUp"):
            self._scroll_by(self.terminal.rows - PAGE_SCROLL_OVERLAP)
            return
        if keybindings.matches(data, "tui.altScreen.pageDown"):
            self._scroll_by(-(self.terminal.rows - PAGE_SCROLL_OVERLAP))
            return
        if keybindings.matches(data, "tui.altScreen.halfPageUp"):
            self._scroll_by(max(1, self.terminal.rows // 2))
            return
        if keybindings.matches(data, "tui.altScreen.halfPageDown"):
            self._scroll_by(-max(1, self.terminal.rows // 2))
            return
        if keybindings.matches(data, "tui.altScreen.lineUp"):
            self._scroll_by(1)
            return
        if keybindings.matches(data, "tui.altScreen.lineDown"):
            self._scroll_by(-1)
            return
        if keybindings.matches(data, "tui.altScreen.top"):
            self._scroll_offset = max(0, len(self._document_lines) - self.terminal.rows)
            self.request_render()
            return
        if keybindings.matches(data, "tui.altScreen.bottom"):
            self._scroll_offset = 0
            self.request_render()
            return
        super().handle_input(data)

    def _handle_mouse(self, data: str) -> bool:
        match = SGR_MOUSE.search(data)
        if not match:
            return False
        button = int(match.group(1))
        if button == 64:
            self._scroll_by(3)
            return True
        if button == 65:
            self._scroll_by(-3)
            return True
        if button == 2 and match.group(4) == "M" and self._on_right_click_paste:
            self._on_right_click_paste()
            return True
        return False

    def _scroll_by(self, delta: int) -> None:
        max_scroll = max(0, len(self._document_lines) - self.terminal.rows)
        self._scroll_offset = min(max_scroll, max(0, self._scroll_offset + delta))
        self.request_render()

    def _apply_viewport(self, lines: List[str], width: int, height: int) -> List[str]:
        self._document_lines = list(lines)
        total = len(lines)
        max_scroll = max(0, total - height)
        self._scroll_offset = min(self._scroll_offset, max_scroll)
        start = max(0, total - height - self._scroll_offset)
        view = lines[start : start + height]
        if self._search_open and self._search_query:
            view = [self._highlight_search(line) for line in view]
        while len(view) < height:
            view.append("")
        if self._scroll_offset > 0:
            indicator = (
                self._scroll_to_end_indicator()
                if self._scroll_to_end_indicator
                else " ↓ Jump to latest message "
            )
            if visible_width(indicator) > width:
                indicator = indicator[:width]
            view[-1] = indicator
        if self._search_open:
            prompt = f"Search: {self._search_query}"
            view[0] = prompt[:width]
        return view[:height]

    def _highlight_search(self, line: str) -> str:
        query = self._search_query
        if not query:
            return line
        lowered = line.lower()
        needle = query.lower()
        index = lowered.find(needle)
        if index < 0:
            return line
        return (
            line[:index]
            + self._search_match_style(line[index : index + len(query)])
            + line[index + len(query) :]
        )
