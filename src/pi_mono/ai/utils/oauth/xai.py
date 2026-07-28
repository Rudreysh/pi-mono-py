"""xAI OAuth device-code flow.

Port of packages/ai/src/auth/oauth/xai.ts.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from pi_mono.ai.utils.oauth.device_code import poll_oauth_device_code_flow
from pi_mono.ai.utils.oauth.types import (
    OAuthCredentials,
    OAuthLoginCallbacks,
)

XAI_CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
XAI_SCOPE = "openid profile email offline_access grok-cli:access api:access"
XAI_DEVICE_CODE_URL = "https://auth.x.ai/oauth2/device/code"
XAI_TOKEN_URL = "https://auth.x.ai/oauth2/token"
REFRESH_SKEW_MS = 5 * 60 * 1000
DEFAULT_TOKEN_LIFETIME_SECONDS = 3600
REQUEST_TIMEOUT_SECONDS = 30


def _required_string(body: dict[str, Any], field: str) -> str:
    value = body.get(field)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"Invalid xAI OAuth response field: {field}")
    return value


def _positive_number(body: dict[str, Any], field: str) -> int | float:
    value = body.get(field)
    if not isinstance(value, (int, float)) or value <= 0:
        raise RuntimeError(f"Invalid xAI OAuth response field: {field}")
    return value


def _validate_verification_uri(raw: str) -> str:
    from urllib.parse import urlparse

    try:
        parsed = urlparse(raw)
    except Exception:
        raise RuntimeError("Untrusted verification URI in xAI OAuth response")
    if parsed.scheme != "https":
        raise RuntimeError("Untrusted verification URI in xAI OAuth response")
    return raw


async def _post_form(url: str, fields: dict[str, str]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.post(
            url,
            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
            data=fields,
        )
    body: dict[str, Any] = {}
    try:
        parsed = response.json()
        if isinstance(parsed, dict):
            body = parsed
    except Exception:
        if not response.is_success:
            raise RuntimeError(f"xAI OAuth returned invalid JSON (HTTP {response.status_code})")
    return {"ok": response.is_success, "status": response.status_code, "body": body}


def _request_failure(action: str, resp: dict[str, Any]) -> RuntimeError:
    body = resp["body"]
    error = body.get("error") if isinstance(body.get("error"), str) else None
    desc = body.get("error_description") if isinstance(body.get("error_description"), str) else None
    detail = ": ".join(filter(None, [error, desc]))
    return RuntimeError(
        f"xAI OAuth {action} failed (HTTP {resp['status']})" + (f": {detail}" if detail else "")
    )


def _credentials_from_token_response(
    body: dict[str, Any], previous_refresh_token: str | None = None
) -> OAuthCredentials:
    access = _required_string(body, "access_token")
    if body.get("refresh_token") is None and previous_refresh_token:
        refresh = previous_refresh_token
    else:
        refresh = _required_string(body, "refresh_token")
    if body.get("expires_in") is None:
        expires_in_seconds = DEFAULT_TOKEN_LIFETIME_SECONDS
    else:
        expires_in_seconds = _positive_number(body, "expires_in")
    return {
        "access": access,
        "refresh": refresh,
        "expires": int(time.time() * 1000) + int(expires_in_seconds * 1000) - REFRESH_SKEW_MS,
    }


async def _request_device_code() -> dict[str, Any]:
    resp = await _post_form(
        XAI_DEVICE_CODE_URL,
        {"client_id": XAI_CLIENT_ID, "scope": XAI_SCOPE, "referrer": "pi"},
    )
    if not resp["ok"]:
        raise _request_failure("device authorization", resp)
    body = resp["body"]
    interval = body.get("interval")
    verification_uri_complete = body.get("verification_uri_complete")
    return {
        "deviceCode": _required_string(body, "device_code"),
        "userCode": _required_string(body, "user_code"),
        "verificationUri": _validate_verification_uri(_required_string(body, "verification_uri")),
        "verificationUriComplete": _validate_verification_uri(verification_uri_complete) if isinstance(verification_uri_complete, str) and verification_uri_complete else None,
        "intervalSeconds": interval if isinstance(interval, (int, float)) and interval > 0 else None,
        "expiresInSeconds": _positive_number(body, "expires_in"),
    }


async def _poll_for_tokens(device: dict[str, Any]) -> OAuthCredentials:
    async def poll() -> dict[str, Any]:
        resp = await _post_form(
            XAI_TOKEN_URL,
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": XAI_CLIENT_ID,
                "device_code": device["deviceCode"],
            },
        )
        if resp["ok"]:
            return {"status": "complete", "value": _credentials_from_token_response(resp["body"])}
        error = resp["body"].get("error")
        if error == "authorization_pending":
            return {"status": "pending"}
        if error == "slow_down":
            interval = resp["body"].get("interval")
            return {"status": "slow_down", "intervalSeconds": interval if isinstance(interval, (int, float)) else None}
        if error in ("access_denied", "authorization_denied"):
            return {"status": "failed", "message": "xAI device authorization was denied"}
        if error == "expired_token":
            return {"status": "failed", "message": "xAI device code expired"}
        return {"status": "failed", "message": _request_failure("device token polling", resp).args[0]}

    return await poll_oauth_device_code_flow(
        poll_fn=poll,
        interval_seconds=device.get("intervalSeconds"),
        expires_in_seconds=device["expiresInSeconds"],
        wait_before_first_poll=True,
    )


async def login_xai(callbacks: OAuthLoginCallbacks) -> OAuthCredentials:
    device = await _request_device_code()
    on_device_code = callbacks.get("onDeviceCode")
    if on_device_code:
        on_device_code({
            "userCode": device["userCode"],
            "verificationUri": device.get("verificationUriComplete") or device["verificationUri"],
            "intervalSeconds": device.get("intervalSeconds"),
            "expiresInSeconds": device["expiresInSeconds"],
        })
    return await _poll_for_tokens(device)


async def refresh_xai_token(credentials: OAuthCredentials) -> OAuthCredentials:
    resp = await _post_form(
        XAI_TOKEN_URL,
        {
            "grant_type": "refresh_token",
            "client_id": XAI_CLIENT_ID,
            "refresh_token": credentials.get("refresh", ""),
        },
    )
    if not resp["ok"]:
        raise _request_failure("token refresh", resp)
    return _credentials_from_token_response(resp["body"], credentials.get("refresh"))


class XaiOAuthProvider:
    id = "xai"
    name = "xAI (Grok/X subscription)"
    uses_callback_server = False

    def login(self, callbacks: OAuthLoginCallbacks) -> Any:
        return login_xai(callbacks)

    def refresh_token(self, credentials: OAuthCredentials) -> Any:
        return refresh_xai_token(credentials)

    def get_api_key(self, credentials: OAuthCredentials) -> str:
        return credentials.get("access", "")


xai_oauth_provider = XaiOAuthProvider()
