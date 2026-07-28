"""RuntimeCredentials - credential store overlay for non-persistent runtime API keys.

Port of packages/coding-agent/src/core/runtime-credentials.ts.
"""

from __future__ import annotations

from typing import Awaitable, Callable

from pi_mono.ai.credential_store import (
    Credential,
    CredentialInfo,
    CredentialStore,
)


class RuntimeCredentials:
    """Async credential store overlay for --api-key style overrides.

    Wraps a base CredentialStore and layers in-memory runtime overrides
    on top. Implements the CredentialStore protocol.
    """

    def __init__(self, store: CredentialStore) -> None:
        self._store = store
        self._overrides: dict[str, str] = {}

    def set_runtime_api_key(self, provider_id: str, api_key: str) -> None:
        self._overrides[provider_id] = api_key

    def remove_runtime_api_key(self, provider_id: str) -> None:
        self._overrides.pop(provider_id, None)

    def has_runtime_api_key(self, provider_id: str) -> bool:
        return provider_id in self._overrides

    async def read(self, provider_id: str) -> Credential | None:
        override = self._overrides.get(provider_id)
        if override is not None:
            return {"type": "api_key", "key": override}
        return await self._store.read(provider_id)

    async def list(self) -> list[CredentialInfo]:
        base_list = await self._store.list()
        entries: dict[str, CredentialInfo] = {
            entry["providerId"]: entry for entry in base_list
        }
        for provider_id in self._overrides:
            entries[provider_id] = CredentialInfo(providerId=provider_id, type="api_key")
        return list(entries.values())

    async def modify(
        self,
        provider_id: str,
        fn: Callable[[Credential | None], Awaitable[Credential | None]],
    ) -> Credential | None:
        return await self._store.modify(provider_id, fn)

    async def delete(self, provider_id: str) -> None:
        self._overrides.pop(provider_id, None)
        await self._store.delete(provider_id)
