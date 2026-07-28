"""Unit tests for ModelRuntime, RuntimeCredentials, and supporting stores."""

from __future__ import annotations

import asyncio
import pytest

from pi_mono.ai.credential_store import (
    Credential,
    CredentialInfo,
    InMemoryCredentialStore,
)
from pi_mono.ai.models_store import InMemoryModelsStore, ModelsStoreEntry
from pi_mono.coding_agent.core.model_runtime import (
    AuthStorageCredentialAdapter,
    ModelRuntime,
    CreateModelRuntimeOptions,
)
from pi_mono.coding_agent.core.runtime_credentials import RuntimeCredentials
from pi_mono.core.auth_storage import AuthStorage


@pytest.fixture
def auth_storage() -> AuthStorage:
    storage = AuthStorage.in_memory({"anthropic": {"type": "api_key", "key": "sk-test-123"}})
    return storage


@pytest.fixture
def model_runtime(auth_storage: AuthStorage) -> ModelRuntime:
    from pi_mono.core.model_registry import ModelRegistry

    registry = ModelRegistry.in_memory(auth_storage)
    adapter = AuthStorageCredentialAdapter(auth_storage)
    credentials = RuntimeCredentials(adapter)
    models_store = InMemoryModelsStore()
    return ModelRuntime(auth_storage, registry, credentials, models_store)


class TestInMemoryCredentialStore:
    def test_read_missing_returns_none(self) -> None:
        store = InMemoryCredentialStore()
        result = asyncio.get_event_loop().run_until_complete(store.read("nonexistent"))
        assert result is None

    def test_modify_stores_credential(self) -> None:
        store = InMemoryCredentialStore()

        async def run() -> None:
            cred: Credential = {"type": "api_key", "key": "sk-abc"}

            async def set_cred(current: Credential | None) -> Credential | None:
                return cred

            result = await store.modify("openai", set_cred)
            assert result is not None
            assert result["key"] == "sk-abc"

            read_back = await store.read("openai")
            assert read_back is not None
            assert read_back["key"] == "sk-abc"

        asyncio.get_event_loop().run_until_complete(run())

    def test_list_returns_stored_entries(self) -> None:
        store = InMemoryCredentialStore()

        async def run() -> None:
            async def set_cred(current: Credential | None) -> Credential | None:
                return {"type": "api_key", "key": "k"}

            await store.modify("openai", set_cred)
            await store.modify("anthropic", set_cred)

            entries = await store.list()
            provider_ids = {e["providerId"] for e in entries}
            assert provider_ids == {"openai", "anthropic"}

        asyncio.get_event_loop().run_until_complete(run())

    def test_delete_removes_credential(self) -> None:
        store = InMemoryCredentialStore()

        async def run() -> None:
            async def set_cred(current: Credential | None) -> Credential | None:
                return {"type": "api_key", "key": "k"}

            await store.modify("openai", set_cred)
            await store.delete("openai")
            result = await store.read("openai")
            assert result is None

        asyncio.get_event_loop().run_until_complete(run())


class TestInMemoryModelsStore:
    def test_read_write_delete(self) -> None:
        store = InMemoryModelsStore()

        async def run() -> None:
            entry: ModelsStoreEntry = {
                "models": [{"id": "gpt-4", "provider": "openai"}],  # type: ignore[typeddict-item]
                "checkedAt": 1000,
            }
            await store.write("openai", entry)
            result = await store.read("openai")
            assert result is not None
            assert result["checkedAt"] == 1000
            assert len(result["models"]) == 1

            await store.delete("openai")
            assert await store.read("openai") is None

        asyncio.get_event_loop().run_until_complete(run())


class TestRuntimeCredentials:
    def test_override_takes_precedence(self) -> None:
        base = InMemoryCredentialStore()

        async def run() -> None:
            async def set_cred(current: Credential | None) -> Credential | None:
                return {"type": "api_key", "key": "base-key"}

            await base.modify("openai", set_cred)

            rc = RuntimeCredentials(base)
            rc.set_runtime_api_key("openai", "override-key")

            cred = await rc.read("openai")
            assert cred is not None
            assert cred["key"] == "override-key"
            assert cred["type"] == "api_key"

        asyncio.get_event_loop().run_until_complete(run())

    def test_list_includes_overrides(self) -> None:
        base = InMemoryCredentialStore()

        async def run() -> None:
            rc = RuntimeCredentials(base)
            rc.set_runtime_api_key("newprovider", "key123")

            entries = await rc.list()
            provider_ids = {e["providerId"] for e in entries}
            assert "newprovider" in provider_ids

        asyncio.get_event_loop().run_until_complete(run())

    def test_remove_clears_override(self) -> None:
        base = InMemoryCredentialStore()

        async def run() -> None:
            rc = RuntimeCredentials(base)
            rc.set_runtime_api_key("openai", "tmp")
            rc.remove_runtime_api_key("openai")

            assert not rc.has_runtime_api_key("openai")
            cred = await rc.read("openai")
            assert cred is None

        asyncio.get_event_loop().run_until_complete(run())


class TestModelRuntime:
    def test_get_models_returns_list(self, model_runtime: ModelRuntime) -> None:
        models = model_runtime.get_models()
        assert isinstance(models, list)

    def test_get_providers_returns_list(self, model_runtime: ModelRuntime) -> None:
        providers = model_runtime.get_providers()
        assert isinstance(providers, list)

    def test_set_runtime_api_key(self, model_runtime: ModelRuntime) -> None:
        async def run() -> None:
            await model_runtime.set_runtime_api_key("openai", "sk-runtime")
            assert model_runtime.credentials.has_runtime_api_key("openai")

            cred = await model_runtime.credentials.read("openai")
            assert cred is not None
            assert cred["key"] == "sk-runtime"

        asyncio.get_event_loop().run_until_complete(run())

    def test_remove_runtime_api_key(self, model_runtime: ModelRuntime) -> None:
        async def run() -> None:
            await model_runtime.set_runtime_api_key("openai", "sk-runtime")
            await model_runtime.remove_runtime_api_key("openai")
            assert not model_runtime.credentials.has_runtime_api_key("openai")

        asyncio.get_event_loop().run_until_complete(run())

    def test_list_credentials(self, model_runtime: ModelRuntime) -> None:
        async def run() -> list[CredentialInfo]:
            return await model_runtime.list_credentials()

        entries = asyncio.get_event_loop().run_until_complete(run())
        assert isinstance(entries, list)
        provider_ids = {e["providerId"] for e in entries}
        assert "anthropic" in provider_ids

    def test_get_available_snapshot(self, model_runtime: ModelRuntime) -> None:
        snapshot = model_runtime.get_available_snapshot()
        assert isinstance(snapshot, list)

    def test_refresh_returns_result(self, model_runtime: ModelRuntime) -> None:
        async def run() -> None:
            result = await model_runtime.refresh()
            assert result.aborted is False

        asyncio.get_event_loop().run_until_complete(run())
