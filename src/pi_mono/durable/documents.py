"""Definitions for mutable JSON documents owned by a durable Session."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class DocDefinition:
    kind: str
    version: int
    scope: str
    initial: Callable[..., dict[str, Any]]
    family: bool = False
    history: str | None = None
    fork: str | None = None
    migrate: Callable[[dict[str, Any], int], dict[str, Any]] | None = None


@dataclass(frozen=True)
class DocToken:
    definition: DocDefinition


def define_doc(definition: dict[str, Any]) -> DocToken:
    return _define(definition, False)


def define_doc_family(definition: dict[str, Any]) -> DocToken:
    return _define(definition, True)


def _define(definition: dict[str, Any], family: bool) -> DocToken:
    version = definition.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise TypeError(f"Document {definition.get('kind', '')} version must be a positive integer")
    scope = definition.get("scope")
    if scope not in {"session", "conversation", "task"}:
        raise TypeError(f"Document {definition.get('kind', '')} scope must be session, conversation, or task")
    if not isinstance(definition.get("kind"), str) or not definition["kind"]:
        raise TypeError("Document kind must not be empty")
    initial = definition.get("initial")
    if not callable(initial):
        raise TypeError(f"Document {definition['kind']} initial must be callable")
    return DocToken(DocDefinition(
        definition["kind"], version, scope, initial, family,
        definition.get("history"), definition.get("fork"), definition.get("migrate"),
    ))


def address(token: DocToken, args: tuple[Any, ...]) -> tuple[str, tuple[Any, ...], Any | None]:
    definition = token.definition
    index = 0
    owner: Any | None = None
    if definition.scope in {"conversation", "task"}:
        if not args or not isinstance(args[0], int):
            raise TypeError(f"Document {definition.kind} requires a {definition.scope} ID")
        owner = args[0]
        index = 1
    key = None
    if definition.family:
        if len(args) <= index or not isinstance(args[index], str):
            raise TypeError(f"Document {definition.kind} requires a family key")
        key = args[index]
        index += 1
    return repr((definition.kind, definition.scope, owner, key)), args[index:], owner
