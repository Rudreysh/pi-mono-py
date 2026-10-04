"""Transactional in-memory storage for the portable durable API."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from .errors import StorageRejected


def _json_copy(value: Any) -> Any:
    # deepcopy keeps Python callers' records isolated while accepting JSON-compatible values.
    try:
        return copy.deepcopy(value)
    except Exception as error:
        raise TypeError("Durable records must be copyable JSON values") from error


@dataclass(frozen=True)
class PreparedCommit:
    writes: tuple[dict[str, Any], ...]
    _storage: "MemoryStorage"
    _sequence: int | None = None

    def apply(self) -> int:
        if self._sequence is not None:
            return self._sequence
        object.__setattr__(self, "_sequence", self._storage._apply(list(self.writes)))
        return self._sequence


class MemoryStorage:
    """Current-record storage with monotonic IDs and commit sequences."""

    def __init__(self) -> None:
        self._next_id = 1
        self._sequence = 0
        self._conversations: dict[int, dict[str, Any]] = {}
        self._entries: dict[int, dict[str, Any]] = {}
        self._tasks: dict[int, dict[str, Any]] = {}
        self._submissions: dict[int, dict[str, Any]] = {}
        self._documents: dict[str, dict[str, Any]] = {}

    async def mint_id(self) -> int:
        value = self._next_id
        self._next_id += 1
        return value

    async def commit(self, writes: list[dict[str, Any]], _context: Any = None) -> int:
        return self.prepare_commit(writes).apply()

    def prepare_commit(self, writes: list[dict[str, Any]]) -> PreparedCommit:
        return PreparedCommit(tuple(_json_copy(writes)), self)

    def _apply(self, writes: list[dict[str, Any]]) -> int:
        candidates = {
            "conversation": dict(self._conversations), "entry": dict(self._entries), "task": dict(self._tasks),
            "submission": dict(self._submissions), "document": dict(self._documents),
        }
        try:
            for write in writes:
                kind = write["type"]
                value = _json_copy(write["value"])
                if kind == "document":
                    candidates[kind][value["address"]] = value
                else:
                    candidates[kind][value["id"]] = value
        except Exception as error:
            raise StorageRejected("Invalid storage write") from error
        self._conversations = candidates["conversation"]
        self._entries = candidates["entry"]
        self._tasks = candidates["task"]
        self._submissions = candidates["submission"]
        self._documents = candidates["document"]
        self._sequence += 1
        return self._sequence

    async def conversation(self, value: int, _context: Any = None) -> dict[str, Any] | None: return _json_copy(self._conversations.get(value))
    async def entry(self, value: int, _context: Any = None) -> dict[str, Any] | None: return _json_copy(self._entries.get(value))
    async def task(self, value: int, _context: Any = None) -> dict[str, Any] | None: return _json_copy(self._tasks.get(value))
    async def document(self, value: str, _context: Any = None) -> dict[str, Any] | None: return _json_copy(self._documents.get(value))

    async def scan_conversations(self, _query: dict[str, Any] | None = None, limit: int = 100, cursor: int | None = None, _context: Any = None) -> dict[str, Any]:
        return self._page(self._conversations.values(), limit, cursor)

    async def scan_entries(self, query: dict[str, Any] | None = None, limit: int = 100, cursor: int | None = None, _context: Any = None) -> dict[str, Any]:
        items = self._entries.values()
        if query and "conversationId" in query:
            items = [item for item in items if item["conversationId"] == query["conversationId"]]
        return self._page(items, limit, cursor)

    async def scan_tasks(self, query: dict[str, Any] | None = None, limit: int = 100, cursor: int | None = None, _context: Any = None) -> dict[str, Any]:
        items = self._tasks.values()
        if query and "conversationId" in query:
            items = [item for item in items if item["conversationId"] == query["conversationId"]]
        return self._page(items, limit, cursor)

    @staticmethod
    def _page(items: Any, limit: int, cursor: int | None) -> dict[str, Any]:
        ordered = sorted(items, key=lambda item: item["id"])
        if cursor is not None:
            ordered = [item for item in ordered if item["id"] > cursor]
        page = ordered[:limit]
        result = {"items": _json_copy(page)}
        if len(ordered) > len(page):
            result["next"] = page[-1]["id"]
        return result
