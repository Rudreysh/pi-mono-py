"""Kimi Code (subscription) OAuth flow.

RFC 8628 device authorization grant against https://auth.kimi.com.
The access token authenticates requests to https://api.kimi.com/coding
as an Authorization: Bearer header.

Port of packages/ai/src/auth/oauth/kimi-coding.ts.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from pi_mono.ai.utils.oauth.device_code import poll_oauth_device_code_flow
from pi_mono.ai.utils.oauth.types import (
    OAuthCredentials,
    OAuthLoginCallbacks,
)
from pi_mono.ai.utils.provider_env import get_provider_env_value

CLIENT_ID = "17e5f671-d194-4dfb-9706-5516cb48c098"
DEFAULT_OAUTH_HOST = "https://auth.kimi.com"
DEVICE_CODE_TIMEOUT_SECONDS = 15 * 60
DEFAULT_POLL_INTERVAL_SECONDS = 5
REQUEST_TIMEOUT_MS = 30_000
REFRESH_MAX_RETRIES = 3


def _get_oauth_host() -> str:
    override = get_provider_env_value("KIMI_CODE_OAUTH_HOST") or get_provider_env_value(
        "KIMI_OAUTH_HOST"
    )
    return (override or DEFAULT_OAUTH_HOST).rstrip("/")


def _trusted_http_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    from urllib.parse import urlparse

    try:
        parsed = urlparse(value)
        if parsed.scheme not in ("https", "http"):
            return None
        return value
    except Exception:
        return None


async def _start_device_authorization(
    oauth_host: str,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_MS / 1000) as client:
        response = await client.post(
            f"{oauth_host}/api/oauth/device_authorization",
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            data={"client_id": CLIENT_ID},
        )
    if not response.is_success:
        text = response.text
        raise RuntimeError(
            f"Kimi Code device authorization failed with status {response.status_code}"
            + (f": {text}" if text else "")
        )
    json_data = response.json()
    device_code = json_data.get("device_code")
    user_code = json_data.get("user_code")
    verification_uri = json_data.get("verification_uri")
    verification_uri_complete = json_data.get("verification_uri_complete")
    if (
        not isinstance(device_code, str)
        or not isinstance(user_code, str)
        or not isinstance(verification_uri, str)
        or not isinstance(verification_uri_complete, str)
        or not _trusted_http_url(verification_uri_complete)
        or not _trusted_http_url(verification_uri)
    ):
        raise RuntimeError(f"Invalid Kimi Code device authorization response: {json_data}")
    interval = json_data.get("interval")
    expires_in = json_data.get("expires_in")
    return {
        "deviceCode": device_code,
        "userCode": user_code,
        "verificationUri": verification_uri,
        "verificationUriComplete": verification_uri_complete,
        "intervalSeconds": interval if isinstance(interval, (int, float)) and interval > 0 else DEFAULT_POLL_INTERVAL_SECONDS,
        "expiresInSeconds": expires_in if isinstance(expires_in, (int, float)) and expires_in > 0 else DEVICE_CODE_TIMEOUT_SECONDS,
    }


def _parse_token_response(json_data: dict[str, Any] | None, operation: str) -> dict[str, Any]:
    if not json_data:
        raise RuntimeError(f"Kimi Code token {operation} response missing fields: {json_data}")
    access_token = json_data.get("access_token")
    refresh_token = json_data.get("refresh_token")
    expires_in = json_data.get("expires_in")
    if (
        not isinstance(access_token, str)
        or not access_token
        or not isinstance(refresh_token, str)
        or not refresh_token
        or not isinstance(expires_in, (int, float))
        or expires_in <= 0
    ):
        raise RuntimeError(f"Kimi Code token {operation} response missing fields: {json_data}")
    return {
        "access": access_token,
        "refresh": refresh_token,
        "expires": int(time.time() * 1000) + int(expires_in * 1000),
    }


async def _poll_for_token(
    oauth_host: str,
    device: dict[str, Any],
) -> dict[str, Any]:
    async def poll() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_MS / 1000) as client:
            response = await client.post(
                f"{oauth_host}/api/oauth/token",
                headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
                data={
                    "client_id": CLIENT_ID,
                    "device_code": device["deviceCode"],
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
            )
        if response.status_code >= 500:
            text = response.text
            return {
                "status": "failed",
                "message": f"Kimi Code device token request failed with status {response.status_code}"
                + (f": {text}" if text else ""),
            }
        try:
            json_data = response.json()
        except Exception:
            json_data = {}
        if response.is_success and isinstance(json_data.get("access_token"), str):
            try:
                return {"status": "complete", "value": _parse_token_response(json_data, "poll")}
            except Exception as e:
                return {"status": "failed", "message": str(e)}
        error = json_data.get("error")
        if error == "authorization_pending":
            return {"status": "pending"}
        if error == "slow_down":
            interval = json_data.get("interval")
            return {"status": "slow_down", "intervalSeconds": interval if isinstance(interval, (int, float)) and interval > 0 else None}
        if error == "expired_token":
            return {"status": "failed", "message": "Kimi Code device authorization expired. Please restart login."}
        if error == "access_denied":
            return {"status": "failed", "message": "Kimi Code login was denied."}
        desc = f": {json_data.get('error_description')}" if isinstance(json_data.get("error_description"), str) else ""
        return {
            "status": "failed",
            "message": f"Kimi Code device token request failed (status {response.status_code})"
            + (f": {error}{desc}" if isinstance(error, str) else ""),
        }

    return await poll_oauth_device_code_flow(
        poll_fn=poll,
        interval_seconds=device["intervalSeconds"],
        expires_in_seconds=device["expiresInSeconds"],
        wait_before_first_poll=True,
    )


async def _refresh_token(
    oauth_host: str,
    refresh_token_value: str,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(REFRESH_MAX_RETRIES + 1):
        if attempt > 0:
            await asyncio.sleep(1.0 * 2 ** (attempt - 1))
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_MS / 1000) as client:
                response = await client.post(
                    f"{oauth_host}/api/oauth/token",
                    headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
                    data={
                        "client_id": CLIENT_ID,
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token_value,
                    },
                )
        except Exception as e:
            last_error = e
            continue
        json_data: dict[str, Any] = {}
        try:
            json_data = response.json()
        except Exception:
            pass
        if response.is_success:
            return _parse_token_response(json_data, "refresh")
        if response.status_code in (401, 403) or json_data.get("error") == "invalid_grant":
            desc = f": {json_data.get('error_description')}" if isinstance(json_data.get("error_description"), str) else ""
            raise RuntimeError(f"Kimi Code token refresh unauthorized (status {response.status_code}){desc}")
        if (response.status_code == 429 or response.status_code >= 500) and attempt < REFRESH_MAX_RETRIES:
            last_error = RuntimeError(f"Kimi Code token refresh failed with status {response.status_code}")
            continue
        raise RuntimeError(f"Kimi Code token refresh failed with status {response.status_code}: {json_data}")
    raise last_error or RuntimeError("Kimi Code token refresh failed")


async def login_kimi_coding(callbacks: OAuthLoginCallbacks) -> OAuthCredentials:
    oauth_host = _get_oauth_host()
    device = await _start_device_authorization(oauth_host)
    on_device_code = callbacks.get("onDeviceCode")
    if on_device_code:
        on_device_code({
            "userCode": device["userCode"],
            "verificationUri": device["verificationUriComplete"],
            "intervalSeconds": device["intervalSeconds"],
            "expiresInSeconds": device["expiresInSeconds"],
        })
    token = await _poll_for_token(oauth_host, device)
    return {"access": token["access"], "refresh": token["refresh"], "expires": token["expires"]}


async def refresh_kimi_coding_token(credentials: OAuthCredentials) -> OAuthCredentials:
    token = await _refresh_token(_get_oauth_host(), credentials.get("refresh", ""))
    return {"access": token["access"], "refresh": token["refresh"], "expires": token["expires"]}


class KimiCodingOAuthProvider:
    id = "kimi-coding"
    name = "Kimi Code (subscription)"
    uses_callback_server = False

    def login(self, callbacks: OAuthLoginCallbacks) -> Any:
        return login_kimi_coding(callbacks)

    def refresh_token(self, credentials: OAuthCredentials) -> Any:
        return refresh_kimi_coding_token(credentials)

    def get_api_key(self, credentials: OAuthCredentials) -> str:
        return credentials.get("access", "")


kimi_coding_oauth_provider = KimiCodingOAuthProvider()
