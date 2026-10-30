"""Tool execution display for interactive mode."""

from __future__ import annotations

import threading
import time
from typing import Any

from pi_mono.coding_agent.core.tools.tool_renderers import render_tool_call, render_tool_result
from pi_mono.coding_agent.modes.interactive.components.bash_execution import format_duration
from pi_mono.coding_agent.modes.interactive.theme.theme import theme
from pi_mono.tui.components.box import Box
from pi_mono.tui.components.spacer import Spacer
from pi_mono.tui.components.text import Text
from pi_mono.tui.tui import Container, TUI


def _shell_timing_label(
    duration_ms: object,
    *,
    is_partial: bool,
    started_at: int | None,
    ended_at: int | None,
) -> str | None:
    """Recorded execution time wins. The component clock is only a fallback."""
    if not is_partial and isinstance(duration_ms, (int, float)) and not isinstance(duration_ms, bool):
        return f"Took {format_duration(round(duration_ms))}"
    if started_at is None:
        return None
    end_time = ended_at if ended_at is not None else int(time.time() * 1000)
    label = "Elapsed" if is_partial else "Took"
    return f"{label} {format_duration(max(0, end_time - started_at))}"


class ToolExecutionComponent(Container):
    def __init__(
        self,
        tool_name: str,
        tool_call_id: str,
        args: Any,
        *,
        ui: TUI | None = None,
        cwd: str | None = None,
        show_images: bool = True,
        output_pad: int = 1,
    ) -> None:
        super().__init__()
        self._ui = ui
        self._output_pad = output_pad
        self._elapsed_timer: threading.Timer | None = None
        self._tool_name = tool_name
        self._tool_call_id = tool_call_id
        self._args = args
        self._cwd = cwd or "."
        self._show_images = show_images
        self._expanded = False
        self._is_partial = True
        self._is_error = False
        self._result: dict[str, Any] | None = None
        self._started_at: int | None = None
        self._ended_at: int | None = None
        self._content_box = Box(output_pad, 1, theme.bg_fn("toolPendingBg"))
        self.add_child(Spacer(1))
        self.add_child(self._content_box)
        self._update_display()

    @property
    def tool_call_id(self) -> str:
        return self._tool_call_id

    def update_args(self, args: Any) -> None:
        self._args = args
        self._update_display()

    def mark_execution_started(self) -> None:
        if self._started_at is None:
            self._started_at = int(time.time() * 1000)
            self._ended_at = None
        self._update_display()
        self._sync_elapsed_timer()

    def set_args_complete(self) -> None:
        self._update_display()

    def update_result(self, result: dict[str, Any], is_partial: bool = False) -> None:
        self._result = result
        self._is_partial = is_partial
        self._is_error = bool(result.get("isError"))
        if not is_partial and self._started_at is not None and self._ended_at is None:
            self._ended_at = int(time.time() * 1000)
        self._update_display()
        self._sync_elapsed_timer()

    def set_output_pad(self, padding: int) -> None:
        self._output_pad = padding
        self._content_box.padding_x = padding
        self._update_display()

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self._update_display()

    def _sync_elapsed_timer(self) -> None:
        ticking = (
            self._tool_name in ("bash", "powershell")
            and self._is_partial
            and self._started_at is not None
        )
        if ticking:
            if self._elapsed_timer is None:
                timer = threading.Timer(1.0, self._on_elapsed_tick)
                timer.daemon = True
                self._elapsed_timer = timer
                timer.start()
            return
        if self._elapsed_timer is not None:
            self._elapsed_timer.cancel()
            self._elapsed_timer = None

    def _on_elapsed_tick(self) -> None:
        self._elapsed_timer = None
        if not (self._is_partial and self._started_at is not None):
            return
        self.invalidate()
        if self._ui is not None:
            self._ui.request_render()
        self._sync_elapsed_timer()

    def invalidate(self) -> None:
        super().invalidate()
        self._update_display()

    def _update_display(self) -> None:
        if self._is_partial:
            bg_fn = theme.bg_fn("toolPendingBg")
        elif self._is_error:
            bg_fn = theme.bg_fn("toolErrorBg")
        else:
            bg_fn = theme.bg_fn("toolSuccessBg")
        self._content_box.set_bg_fn(bg_fn)
        self._content_box.clear()

        call_text = render_tool_call(
            self._tool_name,
            self._args,
            self._cwd,
            expanded=self._expanded,
        )
        self._content_box.add_child(Text(call_text, padding_x=0, padding_y=0))

        if self._result is not None:
            result_text = render_tool_result(
                self._tool_name,
                self._args,
                self._result,
                self._cwd,
                expanded=self._expanded,
                is_error=self._is_error,
                show_images=self._show_images,
            )
            if result_text:
                self._content_box.add_child(Text(result_text, padding_x=0, padding_y=0))
        if self._tool_name in ("bash", "powershell"):
            timing = _shell_timing_label(
                None if self._result is None else self._result.get("durationMs"),
                is_partial=self._is_partial,
                started_at=self._started_at,
                ended_at=self._ended_at,
            )
            if timing:
                self._content_box.add_child(Text(theme.fg("muted", timing), 0, 0))
