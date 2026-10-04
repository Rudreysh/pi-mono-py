"""Vendor-neutral telemetry."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol


class TelemetrySpan(Protocol):
    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None: ...
    def set_attributes(self, attributes: dict[str, Any]) -> None: ...
    def set_status(self, status: dict[str, Any]) -> None: ...
    async def start_span(self, options: dict[str, Any], callback: Callable[..., Any]) -> Any: ...


class TelemetryContext(Protocol):
    async def start_span(self, options: dict[str, Any], callback: Callable[..., Any]) -> Any: ...


class _NoopSpan:
    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        del name, attributes

    def set_attributes(self, attributes: dict[str, Any]) -> None:
        del attributes

    def set_status(self, status: dict[str, Any]) -> None:
        del status

    async def start_span(self, options: dict[str, Any], callback: Callable[..., Any]) -> Any:
        return await _invoke(callback, self)


class NoopTelemetryContext:
    async def start_span(self, options: dict[str, Any], callback: Callable[..., Any]) -> Any:
        return await _invoke(callback, _NoopSpan())


class MemorySpan(_NoopSpan):
    def __init__(self, name: str, store: list[dict[str, Any]]) -> None:
        self.name = name
        self.events: list[dict[str, Any]] = []
        self.attributes: dict[str, Any] = {}
        self.status: dict[str, Any] = {"status": "ok"}
        self._store = store

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        self.events.append({"name": name, "attributes": attributes or {}})

    def set_attributes(self, attributes: dict[str, Any]) -> None:
        self.attributes.update(attributes)

    def set_status(self, status: dict[str, Any]) -> None:
        self.status = status

    async def start_span(self, options: dict[str, Any], callback: Callable[..., Any]) -> Any:
        child = MemorySpan(str(options.get("name") or "span"), self._store)
        try:
            return await _invoke(callback, child)
        finally:
            self._store.append(
                {
                    "name": child.name,
                    "events": child.events,
                    "attributes": child.attributes,
                    "status": child.status,
                }
            )


class MemoryTelemetryContext:
    def __init__(self) -> None:
        self.spans: list[dict[str, Any]] = []

    async def start_span(self, options: dict[str, Any], callback: Callable[..., Any]) -> Any:
        span = MemorySpan(str(options.get("name") or "span"), self.spans)
        try:
            return await _invoke(callback, span)
        finally:
            self.spans.append(
                {
                    "name": span.name,
                    "events": span.events,
                    "attributes": span.attributes,
                    "status": span.status,
                }
            )


NOOP_TELEMETRY_CONTEXT = NoopTelemetryContext()


async def _invoke(callback: Callable[..., Any], span: Any) -> Any:
    result = callback(span)
    if isinstance(result, Awaitable):
        return await result
    return result
