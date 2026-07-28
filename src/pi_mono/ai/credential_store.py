"""CredentialStore protocol and InMemoryCredentialStore implementation.

Port of packages/ai/src/auth/credential-store.ts and packages/ai/src/auth/types.ts.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Protocol, TypedDict, Union, runtime_checkable


class ApiKeyCredential(TypedDict, total=False):
    type: str  # "api_key"
    key: str
    env: dict[str, str]


class OAuthCredential(TypedDict, total=False):
    type: str  # "oauth"
    refresh: str
    access: str
    expires: int


Credential = Union[ApiKeyCredential, OAuthCredential]


class CredentialInfo(TypedDict):
    providerId: str
    type: str


@runtime_checkable
class CredentialStore(Protocol):
    async def read(self, provider_id: str) -> Credential | None: ...

    async def list(self) -> list[CredentialInfo]: ...

    async def modify(
        self,
        provider_id: str,
        fn: Callable[[Credential | None], Awaitable[Credential | None]],
    ) -> Credential | None: ...

    async def delete(self, provider_id: str) -> None: ...


class InMemoryCredentialStore:
    """Default in-memory credential store. Apps inject persistent stores."""

    def __init__(self) -> None:
        self._credentials: dict[str, Credential] = {}
        self._chains: dict[str, asyncio.Lock] = {}

    def _lock_for(self, provider_id: str) -> asyncio.Lock:
        lock = self._chains.get(provider_id)
        if lock is None:
            lock = asyncio.Lock()
            self._chains[provider_id] = lock
        return lock

    async def read(self, provider_id: str) -> Credential | None:
        return self._credentials.get(provider_id)

    async def list(self) -> list[CredentialInfo]:
        return [
            CredentialInfo(providerId=pid, type=cred.get("type", "api_key"))
            for pid, cred in self._credentials.items()
        ]

    async def modify(
        self,
        provider_id: str,
        fn: Callable[[Credential | None], Awaitable[Credential | None]],
    ) -> Credential | None:
        async with self._lock_for(provider_id):
            current = self._credentials.get(provider_id)
            result = await fn(current)
            if result is not None:
                self._credentials[provider_id] = result
            return result if result is not None else current

    async def delete(self, provider_id: str) -> None:
        async with self._lock_for(provider_id):
            self._credentials.pop(provider_id, None)
