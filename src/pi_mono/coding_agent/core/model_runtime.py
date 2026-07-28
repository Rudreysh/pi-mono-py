"""ModelRuntime - compatibility facade wrapping AuthStorage + ModelRegistry.

Port of packages/coding-agent/src/core/model-runtime.ts.
Exposes the new-style API while delegating to existing implementations.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pi_mono.ai.credential_store import Credential, CredentialInfo, CredentialStore
from pi_mono.ai.models_store import ModelsStore
from pi_mono.ai.types import Model
from pi_mono.coding_agent.core.models_store import FileModelsStore, InMemoryCodingAgentModelsStore
from pi_mono.coding_agent.core.runtime_credentials import RuntimeCredentials
from pi_mono.config import get_agent_dir
from pi_mono.core.auth_storage import AuthStorage
from pi_mono.core.model_registry import ModelRegistry


class AuthStorageCredentialAdapter:
    """Adapts the existing AuthStorage to the CredentialStore protocol."""

    def __init__(self, auth_storage: AuthStorage) -> None:
        self._auth = auth_storage

    async def read(self, provider_id: str) -> Credential | None:
        data = self._auth.get(provider_id)
        if data is None:
            return None
        cred_type = data.get("type", "api_key")
        if cred_type == "api_key":
            result: Credential = {"type": "api_key"}
            if data.get("key"):
                result["key"] = data["key"]
            if data.get("env"):
                result["env"] = data["env"]
            return result
        return {"type": "oauth", "refresh": data.get("refresh", ""), "access": data.get("access", ""), "expires": data.get("expires", 0)}

    async def list(self) -> list[CredentialInfo]:
        return [
            CredentialInfo(providerId=pid, type=self._auth.data.get(pid, {}).get("type", "api_key"))
            for pid in self._auth.list()
        ]

    async def modify(self, provider_id: str, fn) -> Credential | None:
        current = await self.read(provider_id)
        result = await fn(current)
        if result is not None:
            self._auth.set(provider_id, dict(result))
        return result if result is not None else current

    async def delete(self, provider_id: str) -> None:
        self._auth.remove(provider_id)


class AuthStatusResult:
    __slots__ = ("configured", "source", "label")

    def __init__(self, configured: bool, source: str = "", label: str = "") -> None:
        self.configured = configured
        self.source = source
        self.label = label

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {"configured": self.configured}
        if self.source:
            d["source"] = self.source
        if self.label:
            d["label"] = self.label
        return d


@dataclass
class ModelsRefreshResult:
    aborted: bool = False
    errors: dict[str, str] = field(default_factory=dict)


@dataclass
class CreateModelRuntimeOptions:
    credentials: Optional[CredentialStore] = None
    auth_path: Optional[str] = None
    models_path: Optional[str] = None
    models_store: Optional[ModelsStore] = None
    models_store_path: Optional[str] = None
    allow_model_network: bool = False


class ModelRuntime:
    """Configured model collection used by coding-agent and SDK consumers.

    Wraps the existing AuthStorage and ModelRegistry implementations,
    exposing the same surface as the TS ModelRuntime.
    """

    def __init__(
        self,
        auth_storage: AuthStorage,
        model_registry: ModelRegistry,
        credentials: RuntimeCredentials,
        models_store: ModelsStore,
    ) -> None:
        self._auth_storage = auth_storage
        self._registry = model_registry
        self._credentials = credentials
        self._models_store = models_store

    @classmethod
    async def create(cls, options: Optional[CreateModelRuntimeOptions] = None) -> "ModelRuntime":
        opts = options or CreateModelRuntimeOptions()
        agent_dir = str(get_agent_dir())

        auth_path = opts.auth_path
        auth_storage = AuthStorage.create(auth_path)

        models_path = opts.models_path
        if models_path is None:
            models_path = os.path.join(agent_dir, "models.json")

        model_registry = ModelRegistry.create(auth_storage, models_path)

        if opts.credentials is not None:
            credential_store = opts.credentials
        else:
            credential_store = AuthStorageCredentialAdapter(auth_storage)

        credentials = RuntimeCredentials(credential_store)

        if opts.models_store is not None:
            models_store = opts.models_store
        elif models_path:
            store_path = opts.models_store_path or str(
                Path(models_path).parent / "models-store.json"
            )
            models_store = FileModelsStore(store_path)
        else:
            models_store = InMemoryCodingAgentModelsStore()

        runtime = cls(auth_storage, model_registry, credentials, models_store)
        # TODO: remote ETag-based catalog refresh (allowNetwork)
        return runtime

    def get_providers(self) -> list[str]:
        providers: set[str] = set()
        for m in self._registry.get_all():
            p = m.get("provider")
            if p:
                providers.add(p)
        return sorted(providers)

    def get_models(self, provider_id: Optional[str] = None) -> list[Model]:
        all_models = self._registry.get_all()
        if provider_id is None:
            return list(all_models)
        return [m for m in all_models if m.get("provider") == provider_id]

    def get_model(self, provider_id: str, model_id: str) -> Optional[Model]:
        return self._registry.find(provider_id, model_id)

    async def get_available(self, provider_id: Optional[str] = None) -> list[Model]:
        available = self._registry.get_available()
        if provider_id is None:
            return available
        return [m for m in available if m.get("provider") == provider_id]

    def get_available_snapshot(self) -> list[Model]:
        return self._registry.get_available()

    def has_configured_auth(self, provider_id: str) -> bool:
        return self._auth_storage.has_auth(provider_id)

    def is_using_oauth(self, provider_id: str) -> bool:
        cred = self._auth_storage.get(provider_id)
        return cred is not None and cred.get("type") == "oauth"

    async def get_api_key_and_headers(self, model: Model) -> dict:
        return await self._registry.get_api_key_and_headers(model)

    def get_provider_auth_status(self, provider_id: str) -> dict:
        return self._registry.get_provider_auth_status(provider_id)

    async def set_runtime_api_key(self, provider_id: str, api_key: str) -> None:
        self._credentials.set_runtime_api_key(provider_id, api_key)
        self._auth_storage.set_runtime_api_key(provider_id, api_key)

    async def remove_runtime_api_key(self, provider_id: str) -> None:
        self._credentials.remove_runtime_api_key(provider_id)
        self._auth_storage.remove_runtime_api_key(provider_id)

    async def list_credentials(self) -> list[CredentialInfo]:
        return await self._credentials.list()

    async def refresh(self, *, allow_network: bool = False, signal: object = None) -> ModelsRefreshResult:
        """Reload model config and refresh availability.

        TODO: remote ETag-based catalog refresh when allow_network is True.
        """
        self._registry.refresh()
        return ModelsRefreshResult()

    def get_error(self) -> Optional[str]:
        return self._registry.get_error()

    @property
    def auth_storage(self) -> AuthStorage:
        return self._auth_storage

    @property
    def model_registry(self) -> ModelRegistry:
        return self._registry

    @property
    def credentials(self) -> RuntimeCredentials:
        return self._credentials
