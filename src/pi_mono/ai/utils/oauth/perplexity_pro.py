"""Perplexity Pro subscription auth via browser session token.

Perplexity does not ship an official CLI/OAuth flow for Pro. This login stores
the browser `__Secure-next-auth.session-token` cookie so the Python coding agent
can call Perplexity's web SSE backend with your subscription.

Unofficial / may break when Perplexity changes their web API. Personal use only.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from pi_mono.ai.types import Model
from pi_mono.ai.utils.oauth.types import OAuthCredentials, OAuthLoginCallbacks, OAuthPrompt

PERPLEXITY_PRO_PROVIDER_ID = "perplexity-pro"
PERPLEXITY_AUTH_SESSION_URL = "https://www.perplexity.ai/api/auth/session"
SESSION_COOKIE_NAME = "__Secure-next-auth.session-token"
# Browser cookies often expire sooner than a month; re-validate periodically.
SESSION_TTL_MS = 12 * 60 * 60 * 1000


def normalize_session_token(raw: str) -> str:
    """Normalize a pasted cookie value or Cookie/Set-Cookie fragment."""
    token = raw.strip().strip('"').strip("'")
    # Allow pasting a full Cookie header fragment.
    if SESSION_COOKIE_NAME in token or "next-auth.session-token=" in token:
        for part in token.split(";"):
            part = part.strip()
            if part.startswith(f"{SESSION_COOKIE_NAME}="):
                return part.split("=", 1)[1].strip().strip('"').strip("'")
            if part.startswith("next-auth.session-token="):
                return part.split("=", 1)[1].strip().strip('"').strip("'")
    if token.startswith(f"{SESSION_COOKIE_NAME}="):
        token = token.split("=", 1)[1].strip()
    # Strip trailing cookie attributes if value + Path/Secure was pasted.
    if ";" in token:
        token = token.split(";", 1)[0].strip()
    return token.strip().strip('"').strip("'")


# Back-compat alias used by tests / callers.
_normalize_session_token = normalize_session_token


async def validate_perplexity_session_token(session_token: str) -> dict[str, Any]:
    """Validate a session token against Perplexity's auth session endpoint."""
    token = normalize_session_token(session_token)
    if not token:
        raise RuntimeError("Empty Perplexity session token")

    headers = {
        "Accept": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        ),
        "Cookie": f"{SESSION_COOKIE_NAME}={token}",
    }
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        response = await client.get(PERPLEXITY_AUTH_SESSION_URL, headers=headers)
        if response.status_code in (401, 403):
            raise RuntimeError(
                "Perplexity rejected the session token (expired or invalid). "
                "Log in at https://www.perplexity.ai and copy a fresh "
                f"{SESSION_COOKIE_NAME} cookie."
            )
        if response.status_code != 200:
            raise RuntimeError(
                f"Perplexity session check failed with HTTP {response.status_code}: "
                f"{response.text[:200]}"
            )
        try:
            data = response.json()
        except Exception as error:
            raise RuntimeError("Perplexity session check returned non-JSON") from error
        if not isinstance(data, dict) or not data:
            raise RuntimeError(
                "Perplexity session is empty. Make sure you are logged into Pro in the browser "
                f"and pasted the {SESSION_COOKIE_NAME} cookie value."
            )
        user = data.get("user")
        if not isinstance(user, dict) or not (user.get("email") or user.get("id") or user.get("name")):
            raise RuntimeError(
                "Perplexity session has no user. Make sure you are logged in at "
                "https://www.perplexity.ai and pasted a fresh session cookie."
            )
        return data


def _credentials_from_token(token: str) -> OAuthCredentials:
    return {
        "access": token,
        "refresh": token,
        "expires": int(time.time() * 1000) + SESSION_TTL_MS,
    }


async def login_perplexity_pro(callbacks: OAuthLoginCallbacks) -> OAuthCredentials:
    on_auth = callbacks.on_auth if hasattr(callbacks, "on_auth") else callbacks.get("onAuth")
    on_prompt = (
        callbacks.on_prompt if hasattr(callbacks, "on_prompt") else callbacks.get("onPrompt")
    )
    on_progress = (
        callbacks.on_progress if hasattr(callbacks, "on_progress") else callbacks.get("onProgress")
    )

    if on_auth:
        on_auth(
            {
                "url": "https://www.perplexity.ai",
                "instructions": (
                    "Log in with your Perplexity Pro account in the browser, then paste the "
                    f"{SESSION_COOKIE_NAME} cookie value here.\n"
                    "Chrome/Edge: F12 → Application → Cookies → www.perplexity.ai → copy value.\n"
                    "Optional: pip install 'curl_cffi>=0.7' if Cloudflare blocks requests."
                ),
            }
        )

    if not on_prompt:
        raise RuntimeError("Perplexity Pro login requires an interactive prompt callback")

    prompt: OAuthPrompt = {
        "message": (
            f"Paste Perplexity {SESSION_COOKIE_NAME} cookie "
            "(from a logged-in Pro browser session):"
        ),
        "placeholder": "eyJ...",
        "allowEmpty": False,
    }
    raw = await on_prompt(prompt)
    token = normalize_session_token(str(raw or ""))
    if not token:
        raise RuntimeError("Login cancelled")

    if on_progress:
        on_progress("Validating Perplexity Pro session…")

    session = await validate_perplexity_session_token(token)
    email = ""
    user = session.get("user")
    if isinstance(user, dict):
        email = str(user.get("email") or user.get("name") or "")

    credentials = _credentials_from_token(token)
    if email and on_progress:
        on_progress(f"Logged in as {email}")
    return credentials


async def refresh_perplexity_pro_token(credentials: OAuthCredentials) -> OAuthCredentials:
    token = normalize_session_token(
        str(credentials.get("access") or credentials.get("refresh") or "")
    )
    if not token:
        raise RuntimeError(
            "Perplexity Pro session expired. Re-run /login and paste a fresh session cookie."
        )
    await validate_perplexity_session_token(token)
    return _credentials_from_token(token)


class PerplexityProOAuthProvider:
    id = PERPLEXITY_PRO_PROVIDER_ID
    name = "Perplexity Pro"
    uses_callback_server = False

    async def login(self, callbacks: OAuthLoginCallbacks) -> OAuthCredentials:
        return await login_perplexity_pro(callbacks)

    async def refresh_token(self, credentials: OAuthCredentials) -> OAuthCredentials:
        return await refresh_perplexity_pro_token(credentials)

    def get_api_key(self, credentials: OAuthCredentials) -> str:
        return normalize_session_token(
            str(credentials.get("access") or credentials.get("refresh") or "")
        )

    def modify_models(self, models: list[Model], credentials: OAuthCredentials) -> list[Model]:
        del credentials
        return models


perplexity_pro_oauth_provider = PerplexityProOAuthProvider()
