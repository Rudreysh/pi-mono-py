"""Radius gateway OAuth flow.

Radius is a pi-messages gateway. OAuth client APIs live on the configured
gateway; only the interactive browser authorization endpoint is discovered.

Port of packages/ai/src/auth/oauth/radius.ts.
Stub: browser callback server is reduced to device-code flow only. Full
PKCE browser callback server can be added when needed.
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

TOKEN_EXPIRY_SKEW_MS = 60_000
OAUTH_CLIENT_ID = "pi-gateway"
OAUTH_SCOPE = "gateway offline_access"
OAUTH_DEVICE_CODE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"
REQUEST_TIMEOUT_SECONDS = 30


def _normalize_gateway_url(url: str) -> str:
    return url.rstrip("/")


async def _request_oauth_token(
    gateway: str,
    data: dict[str, str],
) -> OAuthCredentials:
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.post(
            f"{gateway}/v1/oauth/token",
            headers={"accept": "application/json", "content-type": "application/x-www-form-urlencoded"},
            data=data,
        )
    if not response.is_success:
        text = response.text
        error_detail = ""
        try:
            body = response.json()
            oauth_error = body.get("error") if isinstance(body.get("error"), str) else None
            desc = body.get("error_description") if isinstance(body.get("error_description"), str) else None
            error_detail = ": ".join(filter(None, [oauth_error, desc]))
        except Exception:
            error_detail = text
        raise RuntimeError(
            f"Radius OAuth token request failed: {error_detail or response.status_code}"
        )
    body = response.json()
    return {
        "access": body["access_token"],
        "refresh": body["refresh_token"],
        "expires": int(time.time() * 1000) + int(body["expires_in"] * 1000) - TOKEN_EXPIRY_SKEW_MS,
    }


async def _request_device_authorization(
    gateway: str,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.post(
            f"{gateway}/v1/oauth/device",
            headers={"accept": "application/json", "content-type": "application/x-www-form-urlencoded"},
            data={"client_id": OAUTH_CLIENT_ID, "scope": OAUTH_SCOPE},
        )
    if not response.is_success:
        text = response.text
        raise RuntimeError(f"Radius OAuth device authorization failed: {text or response.status_code}")
    data = response.json()
    if not data.get("device_code") or not data.get("user_code") or not data.get("verification_uri") or not data.get("expires_in"):
        raise RuntimeError("Radius OAuth device authorization response is missing required fields")
    return data


async def _login_with_device_code(
    gateway: str,
    callbacks: OAuthLoginCallbacks,
) -> OAuthCredentials:
    device = await _request_device_authorization(gateway)
    on_device_code = callbacks.get("onDeviceCode")
    if on_device_code:
        on_device_code({
            "userCode": device["user_code"],
            "verificationUri": device["verification_uri"],
            "intervalSeconds": device.get("interval"),
            "expiresInSeconds": device["expires_in"],
        })

    async def poll() -> dict[str, Any]:
        try:
            credentials = await _request_oauth_token(
                gateway,
                {
                    "grant_type": OAUTH_DEVICE_CODE_GRANT_TYPE,
                    "client_id": OAUTH_CLIENT_ID,
                    "device_code": device["device_code"],
                },
            )
            return {"status": "complete", "value": credentials}
        except RuntimeError as e:
            msg = str(e)
            if "authorization_pending" in msg:
                return {"status": "pending"}
            if "slow_down" in msg:
                return {"status": "slow_down"}
            if "expired_token" in msg:
                return {"status": "failed", "message": "Device authorization expired."}
            if "access_denied" in msg:
                return {"status": "failed", "message": "Device authorization was denied."}
            raise

    return await poll_oauth_device_code_flow(
        poll_fn=poll,
        interval_seconds=device.get("interval"),
        expires_in_seconds=device["expires_in"],
    )


def create_radius_oauth_provider(
    name: str,
    gateway: str,
) -> "RadiusOAuthProvider":
    return RadiusOAuthProvider(name=name, gateway=_normalize_gateway_url(gateway))


class RadiusOAuthProvider:
    uses_callback_server = False

    def __init__(self, name: str, gateway: str) -> None:
        self.id = "radius"
        self.name = name
        self._gateway = gateway

    def login(self, callbacks: OAuthLoginCallbacks) -> Any:
        return _login_with_device_code(self._gateway, callbacks)

    async def refresh_token(self, credentials: OAuthCredentials) -> OAuthCredentials:
        return await _request_oauth_token(
            self._gateway,
            {
                "grant_type": "refresh_token",
                "client_id": OAUTH_CLIENT_ID,
                "refresh_token": credentials.get("refresh", ""),
            },
        )

    def get_api_key(self, credentials: OAuthCredentials) -> str:
        return credentials.get("access", "")


radius_oauth_provider = create_radius_oauth_provider(
    name="Radius Gateway",
    gateway="https://gateway.radius.dev",
)
