"""FileModelsStore - JSON-backed persistent model catalog storage.

Port of packages/coding-agent/src/core/models-store.ts.
Uses the existing FileAuthStorageBackend for locked file access.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Optional

from pi_mono.ai.models_store import InMemoryModelsStore as _InMemoryBase, ModelsStoreEntry
from pi_mono.config import get_agent_dir
from pi_mono.core.auth_storage import FileAuthStorageBackend


class InMemoryCodingAgentModelsStore(_InMemoryBase):
    pass


class FileModelsStore:
    """Locked JSON-backed storage for dynamically refreshed provider catalogs."""

    def __init__(self, path: Optional[str] = None) -> None:
        if path is None:
            path = str(Path(get_agent_dir()) / "models-store.json")
        self._storage = FileAuthStorageBackend(path)

    def _parse(self, content: Optional[str]) -> dict[str, ModelsStoreEntry]:
        if not content:
            return {}
        return json.loads(content)

    async def read(self, provider_id: str) -> ModelsStoreEntry | None:
        entry = self._storage.with_lock(
            lambda content: {"result": self._parse(content).get(provider_id)}
        )
        return copy.deepcopy(entry) if entry else None

    async def write(self, provider_id: str, entry: ModelsStoreEntry) -> None:
        def do_write(content: Optional[str]) -> dict:
            current = self._parse(content)
            current[provider_id] = copy.deepcopy(entry)
            return {"result": None, "next": json.dumps(current, indent=2)}

        self._storage.with_lock(do_write)

    async def delete(self, provider_id: str) -> None:
        def do_delete(content: Optional[str]) -> dict:
            current = self._parse(content)
            current.pop(provider_id, None)
            return {"result": None, "next": json.dumps(current, indent=2)}

        self._storage.with_lock(do_delete)
