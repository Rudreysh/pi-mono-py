"""Immutable invocation-scoped values and cancellation for Chord."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from typing import Any, Callable, Generic, TypeVar

T = TypeVar("T")


class AbortSignal:
    """Small, dependency-free equivalent of an AbortSignal."""

    def __init__(self) -> None:
        self._event = Event()

    @property
    def aborted(self) -> bool:
        return self._event.is_set()

    def _abort(self) -> None:
        self._event.set()


@dataclass(frozen=True)
class ContextKey(Generic[T]):
    description: str


class Context:
    def __init__(
        self,
        values: dict[ContextKey[Any], Any] | None = None,
        name: str = "Context",
        abort_signal: AbortSignal | None = None,
    ) -> None:
        self._values = values or {}
        self._name = name
        self.abort_signal = abort_signal

    def value(self, key: ContextKey[T]) -> T | None:
        return self._values.get(key)

    def with_value(self, key: ContextKey[T], value: T) -> "Context":
        return Context({**self._values, key: value}, self._name, self.abort_signal)

    def __str__(self) -> str:
        return self._name


BACKGROUND_CONTEXT = Context(name="[Context BACKGROUND_CONTEXT]")
TODO_CONTEXT = Context(name="[Context TODO_CONTEXT]")


def create_context_key(description: str) -> ContextKey[Any]:
    return ContextKey(description)


def with_context_value(key: ContextKey[T], value: T, context: Context) -> Context:
    return context.with_value(key, value)


def with_cancel(context: Context) -> tuple[Context, Callable[[], None]]:
    """Derive a context whose signal is revoked when an observation ends."""

    signal = AbortSignal()
    return Context(dict(context._values), str(context), signal), signal._abort
