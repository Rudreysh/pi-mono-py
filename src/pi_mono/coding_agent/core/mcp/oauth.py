"""MCP OAuth sign-in cancel and authorization-server timeouts.

Matches the TypeScript rules: Esc or session shutdown aborts the sign-in, each
authorization-server request stops after 15 seconds, closing an HTTP session
does not ask the auth provider for a token, and an aborted refresh does not
start a new authorization.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from pi_mono.utils.abort_signals import AbortController, is_aborted

OAUTH_REQUEST_TIMEOUT_S = 15
_CLOSE_TIMEOUT_S = 1
_CANCEL_KEYS = {"escape", "esc"}

_active_sign_ins: list["McpSignIn"] = []


class McpSignInCancelledError(Exception):
    def __init__(self) -> None:
        super().__init__("Sign-in cancelled")


class McpOAuthServerError(Exception):
    """A refresh failed in a way that may start a new sign-in."""


async def await_auth_server(
    operation: Awaitable[Any],
    signal: Any | None = None,
    *,
    timeout_s: float = OAUTH_REQUEST_TIMEOUT_S,
) -> Any:
    """Wait for one authorization-server request, bounded by cancel and 15 seconds."""
    if is_aborted(signal):
        if asyncio.iscoroutine(operation):
            operation.close()
        raise McpSignInCancelledError()
    task = asyncio.ensure_future(operation)

    def on_abort() -> None:
        task.cancel()

    if signal is not None and hasattr(signal, "add_event_listener"):
        signal.add_event_listener("abort", on_abort)
    try:
        return await asyncio.wait_for(task, timeout_s)
    except TimeoutError:
        raise TimeoutError("Authorization server request timed out after 15 seconds") from None
    except asyncio.CancelledError:
        if is_aborted(signal):
            raise McpSignInCancelledError() from None
        raise
    finally:
        if signal is not None and hasattr(signal, "remove_event_listener"):
            signal.remove_event_listener("abort", on_abort)
        if not task.done():
            task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


async def refresh_or_authorize(
    refresh: Callable[[], Awaitable[Any]],
    begin_authorization: Callable[[], Awaitable[Any]],
    signal: Any | None = None,
) -> Any:
    """Refresh tokens. An abort is not turned into a new authorization."""
    if is_aborted(signal):
        raise McpSignInCancelledError()
    try:
        return await await_auth_server(refresh(), signal)
    except McpSignInCancelledError:
        raise
    except McpOAuthServerError as error:
        if is_aborted(signal):
            raise McpSignInCancelledError() from error
        return await begin_authorization()
    except Exception as error:
        if is_aborted(signal):
            raise McpSignInCancelledError() from error
        raise


class McpHttpSession:
    """Streamable HTTP session close that reuses the last token."""

    def __init__(self, url: str, fetch: Callable[..., Awaitable[Any]], auth_provider: Any = None) -> None:
        self.url = url
        self.fetch = fetch
        self.auth_provider = auth_provider
        self.last_token: str | None = None
        self.session_id: str | None = None
        self.started = False
        self.closed = False

    def note_token(self, token: str | None) -> None:
        self.last_token = token

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if not (self.started and self.session_id):
            return
        headers: dict[str, str] = {}
        if self.last_token:
            headers["Authorization"] = f"Bearer {self.last_token}"
        try:
            await asyncio.wait_for(
                self.fetch(self.url, method="DELETE", headers=headers),
                timeout=_CLOSE_TIMEOUT_S,
            )
        except Exception:
            return


class McpSignIn:
    """One sign-in. Esc and session shutdown both call cancel()."""

    def __init__(self) -> None:
        self._controller = AbortController()
        self._finished = False

    @property
    def signal(self) -> Any:
        return self._controller.signal

    def cancel(self) -> None:
        self._finished = True
        self._controller.abort()

    def handle_key(self, key: str) -> bool:
        if key.lower() in _CANCEL_KEYS:
            self.cancel()
            return True
        return False

    async def run(self, operation: Callable[[Any], Awaitable[Any]]) -> Any:
        if is_aborted(self.signal):
            raise McpSignInCancelledError()
        task = asyncio.ensure_future(operation(self.signal))
        self.signal.add_event_listener("abort", task.cancel)
        _active_sign_ins.append(self)
        try:
            return await task
        except asyncio.CancelledError:
            raise McpSignInCancelledError() from None
        except Exception as error:
            if is_aborted(self.signal):
                raise McpSignInCancelledError() from error
            raise
        finally:
            self.signal.remove_event_listener("abort", task.cancel)
            if self in _active_sign_ins:
                _active_sign_ins.remove(self)


def cancel_active_mcp_sign_ins() -> None:
    """Abort every sign-in still running. Session shutdown uses this."""
    for sign_in in list(_active_sign_ins):
        sign_in.cancel()
