"""Clipboard text helpers.

Read path mirrors packages/coding-agent clipboard tool fallbacks (pbpaste/xclip).
"""

from __future__ import annotations

import base64
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import uuid

MAX_OSC52_ENCODED_LENGTH = 100_000


def _is_remote_session(env: dict[str, str]) -> bool:
    return bool(env.get("SSH_CONNECTION") or env.get("SSH_CLIENT") or env.get("MOSH_CONNECTION"))


def _is_wsl(env: dict[str, str]) -> bool:
    if env.get("WSL_DISTRO_NAME") or env.get("WSLENV"):
        return True
    try:
        with open("/proc/version", encoding="utf-8") as handle:
            release = handle.read().lower()
            return "microsoft" in release or "wsl" in release
    except OSError:
        return False


def _emit_osc52(text: str) -> bool:
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    if len(encoded) > MAX_OSC52_ENCODED_LENGTH:
        return False
    sys.stdout.write(f"\x1b]52;c;{encoded}\x07")
    sys.stdout.flush()
    return True


def _copy_via_windows_clipboard(text: str) -> bool:
    """Use WSL interop for display-less sessions where Windows owns the clipboard."""
    temp_path = os.path.join(tempfile.gettempdir(), f"pi-wsl-clip-{uuid.uuid4()}.txt")
    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            handle.write(text)
        win_path_result = subprocess.run(
            ["wslpath", "-w", temp_path],
            capture_output=True,
            text=True,
            check=False,
            timeout=1,
        )
        if win_path_result.returncode != 0:
            return False
        win_path = win_path_result.stdout.strip()
        if not win_path:
            return False
        escaped_path = win_path.replace("'", "''")
        script = (
            "Set-Clipboard -Value ([System.IO.File]::ReadAllText(" f"'{escaped_path}', "
            "[System.Text.Encoding]::UTF8))"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", script],
            capture_output=True,
            check=False,
            timeout=5,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


def read_clipboard_text() -> str:
    """Read plain text from the system clipboard."""
    system = platform.system().lower()

    if system == "darwin":
        return _run_capture(["pbpaste"])

    if system == "windows":
        return _run_capture(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-Clipboard -Raw",
            ]
        )

    if shutil.which("xclip"):
        return _run_capture(["xclip", "-selection", "clipboard", "-o"])

    if shutil.which("xsel"):
        return _run_capture(["xsel", "--clipboard", "--output"])

    raise RuntimeError("No clipboard reader available (expected pbpaste, xclip, or xsel)")


def _run_capture(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except FileNotFoundError as error:
        raise RuntimeError(f"Clipboard command not found: {command[0]}") from error
    except subprocess.CalledProcessError as error:
        stderr = (error.stderr or "").strip()
        message = stderr or f"command failed with exit code {error.returncode}"
        raise RuntimeError(message) from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"Clipboard command timed out: {command[0]}") from error

    if result.stdout is None:
        return ""
    return result.stdout


def write_clipboard_text(text: str) -> None:
    """Write plain text to the system clipboard."""
    system = platform.system().lower()
    env = dict(os.environ)

    if system == "darwin":
        subprocess.run(["pbcopy"], input=text, text=True, check=True, timeout=5)
        return

    if system == "windows":
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value $input"],
            input=text,
            text=True,
            check=True,
            timeout=5,
        )
        return

    if shutil.which("xclip"):
        try:
            subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=text,
                text=True,
                check=True,
                timeout=5,
            )
            return
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass

    if shutil.which("xsel"):
        try:
            subprocess.run(
                ["xsel", "--clipboard", "--input"],
                input=text,
                text=True,
                check=True,
                timeout=5,
            )
            return
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass

    if system == "linux" and _is_wsl(env):
        if env.get("WT_SESSION") and _emit_osc52(text):
            return
        if _copy_via_windows_clipboard(text):
            return

    headless_linux = (
        system == "linux"
        and not env.get("DISPLAY")
        and not env.get("WAYLAND_DISPLAY")
        and not env.get("TERMUX_VERSION")
    )
    if _is_remote_session(env) or headless_linux:
        if _emit_osc52(text):
            return
        raise RuntimeError("Clipboard unavailable: text exceeds the OSC 52 size limit")

    raise RuntimeError("No clipboard writer available (expected pbcopy, xclip, or xsel)")
