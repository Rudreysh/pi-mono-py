import io

import pytest

from pi_mono.utils import clipboard


def test_read_clipboard_text_uses_platform_command(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(command)

        class Result:
            stdout = "clipboard-text"

        return Result()

    monkeypatch.setattr(clipboard.subprocess, "run", fake_run)
    monkeypatch.setattr(clipboard.platform, "system", lambda: "Darwin")

    assert clipboard.read_clipboard_text() == "clipboard-text"
    assert calls == [["pbpaste"]]


def test_read_clipboard_text_xclip_fallback(monkeypatch):
    calls: list[list[str]] = []

    def fake_which(command: str) -> str | None:
        return "/usr/bin/xclip" if command == "xclip" else None

    def fake_run(command, **_kwargs):
        calls.append(command)

        class Result:
            stdout = "xclip-text"

        return Result()

    monkeypatch.setattr(clipboard.shutil, "which", fake_which)
    monkeypatch.setattr(clipboard.subprocess, "run", fake_run)
    monkeypatch.setattr(clipboard.platform, "system", lambda: "Linux")

    assert clipboard.read_clipboard_text() == "xclip-text"
    assert calls[0][:2] == ["xclip", "-selection"]


def test_write_clipboard_text_uses_osc52_in_displayless_linux(monkeypatch) -> None:
    output = io.StringIO()
    monkeypatch.setattr(clipboard.platform, "system", lambda: "Linux")
    monkeypatch.setattr(clipboard.shutil, "which", lambda _command: None)
    monkeypatch.setattr(clipboard.sys, "stdout", output)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("TERMUX_VERSION", raising=False)

    clipboard.write_clipboard_text("hello")
    assert output.getvalue() == "\x1b]52;c;aGVsbG8=\x07"


def test_write_clipboard_text_rejects_oversized_headless_osc52(monkeypatch) -> None:
    monkeypatch.setattr(clipboard.platform, "system", lambda: "Linux")
    monkeypatch.setattr(clipboard.shutil, "which", lambda _command: None)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("TERMUX_VERSION", raising=False)

    with pytest.raises(RuntimeError, match="OSC 52 size limit"):
        clipboard.write_clipboard_text("x" * 80_000)


def test_write_clipboard_text_prefers_wsl_interop_without_a_display(monkeypatch) -> None:
    monkeypatch.setattr(clipboard.platform, "system", lambda: "Linux")
    monkeypatch.setattr(clipboard.shutil, "which", lambda _command: None)
    monkeypatch.setattr(clipboard, "_copy_via_windows_clipboard", lambda text: text == "hello")
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    monkeypatch.delenv("WT_SESSION", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("TERMUX_VERSION", raising=False)

    clipboard.write_clipboard_text("hello")


@pytest.mark.skipif(
    not __import__("shutil").which("pbpaste") and not __import__("shutil").which("xclip"),
    reason="No system clipboard tool available",
)
def test_read_clipboard_text_integration():
    text = clipboard.read_clipboard_text()
    assert isinstance(text, str)
