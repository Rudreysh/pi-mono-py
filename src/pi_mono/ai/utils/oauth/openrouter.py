"""OpenRouter OAuth PKCE flow.

OpenRouter exchanges an authorization code for a permanent, user-controlled
API key rather than an expiring access/refresh token pair. The callback is
handled by a one-shot loopback server on an ephemeral port, raced against a
manual prompt so remote/headless sessions can paste the redirect URL when
the browser cannot reach the loopback server.

Port of packages/ai/src/auth/oauth/openrouter.ts.
"""

from __future__ import annotations

import asyncio
import http.server
import threading
import uuid
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from pi_mono.ai.utils.oauth.pkce import generate_pkce
from pi_mono.ai.utils.oauth.types import (
    OAuthCredentials,
    OAuthLoginCallbacks,
    OAuthProviderInterface,
)
from pi_mono.ai.utils.provider_env import get_provider_env_value

AUTHORIZE_URL = "https://openrouter.ai/auth"
TOKEN_URL = "https://openrouter.ai/api/v1/auth/keys"
LOGIN_TIMEOUT_MS = 5 * 60 * 1000
TOKEN_EXCHANGE_TIMEOUT_MS = 30_000


def _get_callback_host() -> str:
    return get_provider_env_value("PI_OAUTH_CALLBACK_HOST") or "127.0.0.1"


def _parse_authorization_input(value: str) -> str | None:
    trimmed = value.strip()
    if not trimmed:
        return None
    try:
        parsed = urlparse(trimmed)
        if parsed.query:
            qs = parse_qs(parsed.query)
            codes = qs.get("code")
            if codes:
                return codes[0]
    except Exception:
        pass
    if "code=" in trimmed:
        qs = parse_qs(trimmed)
        codes = qs.get("code")
        if codes:
            return codes[0]
    return trimmed


def _error_detail(body: dict[str, Any]) -> str | None:
    if isinstance(body.get("error_description"), str):
        return body["error_description"]
    if isinstance(body.get("message"), str):
        return body["message"]
    if isinstance(body.get("error"), str):
        return body["error"]
    err = body.get("error")
    if isinstance(err, dict) and isinstance(err.get("message"), str):
        return err["message"]
    return None


async def _exchange_authorization_code(code: str, verifier: str) -> OAuthCredentials:
    async with httpx.AsyncClient(timeout=TOKEN_EXCHANGE_TIMEOUT_MS / 1000) as client:
        response = await client.post(
            TOKEN_URL,
            headers={"accept": "application/json", "content-type": "application/json"},
            json={"code": code, "code_verifier": verifier, "code_challenge_method": "S256"},
        )
    body: dict[str, Any] = {}
    try:
        body = response.json()
    except Exception:
        if response.is_success:
            raise RuntimeError("OpenRouter OAuth returned invalid JSON")

    if not response.is_success:
        detail = _error_detail(body)
        raise RuntimeError(
            f"OpenRouter OAuth key exchange failed (HTTP {response.status_code})"
            + (f": {detail}" if detail else "")
        )
    key = body.get("key")
    if not isinstance(key, str) or not key:
        raise RuntimeError('OpenRouter OAuth response carries no "key"')
    return {"access": key, "refresh": "", "expires": 2**53 - 1}


async def login_openrouter(callbacks: OAuthLoginCallbacks) -> OAuthCredentials:
    pkce = await generate_pkce()
    verifier = pkce["verifier"]
    challenge = pkce["challenge"]
    callback_host = _get_callback_host()
    callback_path = f"/oauth/callback/{uuid.uuid4()}"

    credential_future: asyncio.Future[OAuthCredentials | None] = asyncio.get_event_loop().create_future()
    server_ref: list[http.server.HTTPServer] = []

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != callback_path:
                self.send_response(404)
                self.end_headers()
                return
            qs = parse_qs(parsed.query)
            code_list = qs.get("code")
            if not code_list:
                self.send_response(400)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body>Signed in to OpenRouter. You may close this page.</body></html>")
            loop = asyncio.get_event_loop()
            loop.call_soon_threadsafe(_set_code, code_list[0])

        def log_message(self, *_args: Any) -> None:
            pass

    def _set_code(code: str) -> None:
        if not credential_future.done():
            asyncio.ensure_future(_do_exchange(code))

    async def _do_exchange(code: str) -> None:
        try:
            cred = await _exchange_authorization_code(code, verifier)
            if not credential_future.done():
                credential_future.set_result(cred)
        except Exception as exc:
            if not credential_future.done():
                credential_future.set_exception(exc)

    try:
        server = http.server.HTTPServer((callback_host, 0), _Handler)
        server_ref.append(server)
        port = server.server_address[1]
        callback_url = f"http://{callback_host}:{port}{callback_path}"
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        authorize_url = f"{AUTHORIZE_URL}?{urlencode({'callback_url': callback_url, 'code_challenge': challenge, 'code_challenge_method': 'S256'})}"

        on_progress = callbacks.get("onProgress")
        if on_progress:
            on_progress(f"Listening for OpenRouter OAuth callback on {callback_url}")
        on_auth = callbacks.get("onAuth")
        if on_auth:
            on_auth({
                "url": authorize_url,
                "instructions": "Complete sign-in in your browser. If the browser is on another machine, paste the final redirect URL here.",
            })

        on_manual = callbacks.get("onManualCodeInput")
        if on_manual:
            manual_task = asyncio.ensure_future(_prompt_manual(on_manual, credential_future, verifier))
        else:
            manual_task = None

        cred = await asyncio.wait_for(credential_future, timeout=LOGIN_TIMEOUT_MS / 1000)
        if cred is None:
            raise RuntimeError("OpenRouter OAuth login cancelled")
        return cred
    finally:
        if server_ref:
            server_ref[0].shutdown()
        if manual_task and not manual_task.done():
            manual_task.cancel()


async def _prompt_manual(
    on_manual: Any,
    credential_future: asyncio.Future[OAuthCredentials | None],
    verifier: str,
) -> None:
    try:
        raw = await on_manual()
        if credential_future.done():
            return
        code = _parse_authorization_input(raw) if raw else None
        if not code:
            if not credential_future.done():
                credential_future.set_exception(RuntimeError("Missing authorization code"))
            return
        cred = await _exchange_authorization_code(code, verifier)
        if not credential_future.done():
            credential_future.set_result(cred)
    except Exception as exc:
        if not credential_future.done():
            credential_future.set_exception(exc)


async def refresh_openrouter_token(credentials: OAuthCredentials) -> OAuthCredentials:
    return credentials


class OpenRouterOAuthProvider:
    id = "openrouter"
    name = "OpenRouter OAuth"
    uses_callback_server = True

    def login(self, callbacks: OAuthLoginCallbacks) -> Any:
        return login_openrouter(callbacks)

    def refresh_token(self, credentials: OAuthCredentials) -> OAuthCredentials:
        return credentials

    def get_api_key(self, credentials: OAuthCredentials) -> str:
        return credentials.get("access", "")


openrouter_oauth_provider = OpenRouterOAuthProvider()
