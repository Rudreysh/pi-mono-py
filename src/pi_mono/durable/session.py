"""Durable session and transaction facade backed by a Storage implementation."""

from __future__ import annotations

import inspect
from typing import Any, Callable

from .documents import DocToken, address
from .errors import ReadAfterWrite


class Transaction:
    def __init__(self, storage: Any) -> None:
        self._storage = storage
        self._writes: list[dict[str, Any]] = []
        self._table_written = False
        self._documents: dict[str, dict[str, Any]] = {}

    def _readable(self, name: str) -> None:
        if self._table_written:
            raise ReadAfterWrite(name)

    async def conversation(self, value: int) -> dict[str, Any] | None: self._readable("conversation"); return await self._storage.conversation(value)
    async def entry(self, value: int) -> dict[str, Any] | None: self._readable("entry"); return await self._storage.entry(value)
    async def task(self, value: int) -> dict[str, Any] | None: self._readable("task"); return await self._storage.task(value)
    async def scan_conversations(self, query: dict[str, Any] | None, limit: int, cursor: int | None = None) -> dict[str, Any]: self._readable("scan_conversations"); return await self._storage.scan_conversations(query, limit, cursor)
    async def scan_entries(self, query: dict[str, Any] | None, limit: int, cursor: int | None = None) -> dict[str, Any]: self._readable("scan_entries"); return await self._storage.scan_entries(query, limit, cursor)
    async def scan_tasks(self, query: dict[str, Any] | None, limit: int, cursor: int | None = None) -> dict[str, Any]: self._readable("scan_tasks"); return await self._storage.scan_tasks(query, limit, cursor)

    async def create_conversation(self, ownership: dict[str, Any] | None = None) -> dict[str, Any]:
        self._table_written = True; value = {"id": await self._storage.mint_id()}
        if ownership and ownership.get("kind") == "task": value["owner"] = {"taskId": ownership["taskId"]}
        self._writes.append({"type": "conversation", "value": value}); return value

    async def append_entry(self, conversation_id: int, value: dict[str, Any]) -> dict[str, Any]:
        self._table_written = True
        if await self._storage.conversation(conversation_id) is None and not any(w["value"]["id"] == conversation_id for w in self._writes if w["type"] == "conversation"):
            raise ValueError(f"Conversation {conversation_id} does not exist")
        record = {**value, "id": await self._storage.mint_id(), "conversationId": conversation_id}
        if record.get("head") == "self": record["head"] = record["id"]
        self._writes.append({"type": "entry", "value": record}); return record

    async def create_task(self, task: dict[str, Any], input: Any, options: dict[str, Any] | None = None) -> int:
        self._table_written = True
        if not options or "conversationId" not in options: raise TypeError("Tx.create_task() requires options.conversationId")
        task_id = await self._storage.mint_id(); definition = task["definition"]
        record = {"id": task_id, "conversationId": options["conversationId"], "kind": definition["name"], "version": definition["version"], "input": input, "after": options.get("after", []), "background": options.get("background", False), "abortRequested": False, "state": {"status": "pending", "checkpoint": definition["initial"](input)}}
        self._writes.append({"type": "task", "value": record}); return task_id

    def set_task(self, value: dict[str, Any]) -> None: self._table_written = True; self._writes.append({"type": "task", "value": value})

    async def doc(self, token: DocToken, *args: Any) -> dict[str, Any]:
        key, rest, _owner = address(token, args)
        if key not in self._documents:
            stored = await self._storage.document(key)
            self._documents[key] = stored["value"] if stored else token.definition.initial(*rest)
        return self._documents[key]

    def writes(self) -> list[dict[str, Any]]:
        values = list(self._writes)
        values.extend({"type": "document", "value": {"address": key, "value": value}} for key, value in self._documents.items())
        return values


class Session:
    def __init__(self, storage: Any) -> None: self.storage = storage

    async def commit(self, change: Callable[[Transaction], Any], _context: Any = None) -> Any:
        tx = Transaction(self.storage); result = change(tx)
        if inspect.isawaitable(result): result = await result
        writes = tx.writes()
        if writes: await self.storage.commit(writes, _context)
        return result

    async def snapshot(self, token: DocToken, *args: Any) -> dict[str, Any] | None:
        key, _rest, _owner = address(token, args); stored = await self.storage.document(key)
        return None if stored is None else stored["value"]


def create_session(storage: Any) -> Session: return Session(storage)
