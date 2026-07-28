"""Remote catalog provider with ETag-aware refresh.

Port of the remote model catalog refresh pattern from
packages/coding-agent/src/core/models-store.ts and remote-catalog-provider.ts.

Stub implementation: the actual HTTP catalog endpoint is provider-specific.
This module provides the ETag-aware refresh skeleton that callers can integrate.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from pi_mono.ai.models_store import ModelsStoreEntry
from pi_mono.ai.types import Model


class RemoteCatalogProvider:
    """Fetches a remote model catalog with ETag-based conditional refresh.

    Uses If-None-Match / ETag headers so unchanged catalogs return 304 and
    skip JSON parsing + model store writes.
    """

    def __init__(
        self,
        provider_id: str,
        catalog_url: str,
        *,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._provider_id = provider_id
        self._catalog_url = catalog_url
        self._timeout = timeout_seconds
        self._last_etag: str | None = None
        self._last_models: list[Model] | None = None

    async def refresh(self, current_entry: ModelsStoreEntry | None = None) -> ModelsStoreEntry | None:
        """Fetch the catalog. Returns None when the remote catalog is unchanged (304)."""
        etag = current_entry.get("etag") if current_entry else self._last_etag
        headers: dict[str, str] = {"accept": "application/json"}
        if etag:
            headers["if-none-match"] = etag

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(self._catalog_url, headers=headers)
        except Exception:
            return None

        if response.status_code == 304:
            return None

        if not response.is_success:
            return None

        new_etag = response.headers.get("etag")
        try:
            data = response.json()
        except Exception:
            return None

        models = self._parse_models(data)
        if models is None:
            return None

        self._last_etag = new_etag
        self._last_models = models
        entry: ModelsStoreEntry = {
            "models": models,
            "lastModified": int(time.time() * 1000),
            "checkedAt": int(time.time() * 1000),
        }
        if new_etag:
            entry["etag"] = new_etag
        return entry

    def _parse_models(self, data: Any) -> list[Model] | None:
        """Parse provider-specific catalog JSON into Model list.

        Override in subclasses for provider-specific formats. Default expects
        a JSON array of model objects with at least ``id`` and ``provider`` fields.
        """
        if isinstance(data, list):
            return [
                m
                for m in data
                if isinstance(m, dict) and "id" in m
            ]
        if isinstance(data, dict) and "models" in data:
            models = data["models"]
            if isinstance(models, list):
                return [m for m in models if isinstance(m, dict) and "id" in m]
        return None

    @property
    def provider_id(self) -> str:
        return self._provider_id
