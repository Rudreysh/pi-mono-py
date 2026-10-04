"""App composition types: services, replicated state, and facets.

This is a usable subset of `packages/chord` for in-process composition. The
TypeScript package also includes plugin bundles, RPC replication, and a
service wire codec that are not fully ported here.
"""

from __future__ import annotations

from typing import Any, Callable, Generic, TypeVar

from .delta import (
    DeltaTracker,
    PathError,
    UnsafePathError,
    apply,
    apply_immutable,
    decoder,
    encoder,
    is_base,
    is_replace,
    overlap,
    track,
)
from .json import is_json_value
from .facets import Facet, FacetHost, combine_facet_loaders, create_facet_host, create_static_facet_loader, define_facet
from .context import BACKGROUND_CONTEXT, TODO_CONTEXT, AbortSignal, Context, ContextKey, create_context_key, with_cancel, with_context_value
from .node import FACET_BUNDLE_FORMAT, FACET_BUNDLE_FORMAT_VERSION, FACET_BUNDLE_MANIFEST_FILE, create_facet_bundle_loader, read_facet_bundle_artifact, read_facet_bundle_manifest
from .services import (
    REMOTE_SERVICE_ERROR_CODES,
    RemoteServiceError,
    RemoteServiceBinding,
    RemoteServiceProvider,
    Service,
    create_loopback_service_transport,
    create_remote_service_binding,
    create_service_catalogue_call,
    create_service_subscribe_call,
    create_service_unsubscribe_call,
    decode_service_control_call,
    define_service,
    is_remote_service_error_code,
    parse_service_call,
    parse_service_catalogue,
    parse_service_provider_update,
    parse_service_subscription_snapshot,
    parse_wire_service_provider_update,
    parse_wire_service_subscription_snapshot,
)

T = TypeVar("T")


class ServiceHandle(Generic[T]):
    def __init__(self, name: str, value: T) -> None:
        self.name = name
        self.value = value


class ChordContext:
    def __init__(self) -> None:
        self._services: dict[str, Any] = {}

    def provide(self, name: str, value: Any) -> None:
        self._services[name] = value

    def get(self, name: str) -> Any:
        return self._services[name]

    def has(self, name: str) -> bool:
        return name in self._services


class ReplicatedState(Generic[T]):
    """Mutable source state with immutable published revisions."""

    def __init__(self, initial: T) -> None:
        if not isinstance(initial, (dict, list)):
            raise TypeError("replicated state must be a JSON object or array")
        self._tracker = track(initial)
        self._value = apply_immutable(None, self._tracker.flush())
        self._sequence = 0
        self._listeners: list[Callable[[T, Any, dict[str, Any]], None]] = []
        self._source_listeners: list[Callable[[list[Any], int, Any], None]] = []

    @property
    def value(self) -> T:
        return self._value

    @property
    def state(self) -> T:
        return self._tracker.state

    @property
    def sequence(self) -> int:
        return self._sequence

    def publish(self, context: Any = None) -> None:
        operations = self._tracker.flush()
        if not operations:
            return
        self._sequence += 1
        self._value = apply_immutable(self._value, operations)
        for listener in list(self._source_listeners):
            listener(operations, self._sequence, context)
        for listener in list(self._listeners):
            listener(self._value, context, {"kind": "update", "sequence": self._sequence})

    def subscribe(self, listener: Callable[[T, Any, dict[str, Any]], None]) -> Callable[[], None]:
        self.publish()
        self._listeners.append(listener)
        listener(self._value, None, {"kind": "hydrate", "sequence": self._sequence})
        return lambda: self._listeners.remove(listener)

    def subscribe_source(self, listener: Callable[[list[Any], int, Any], None]) -> Callable[[], None]:
        self._source_listeners.append(listener)
        return lambda: self._source_listeners.remove(listener)


class ReplicatedStateReplica(Generic[T]):
    """Cold read-only replica populated by service snapshot/update deliveries."""

    def __init__(self, on_error: Callable[[Exception], None] | None = None) -> None:
        self._value: T | None = None
        self._sequence: int | None = None
        self._listeners: list[Callable[[T, Any, dict[str, Any]], None]] = []
        self._on_error = on_error or (lambda _error: None)

    @property
    def value(self) -> T | None:
        return self._value

    def subscribe(self, listener: Callable[[T, Any, dict[str, Any]], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        if self._value is not None:
            self._deliver(listener, None, {"kind": "hydrate", "sequence": self._sequence})
        return lambda: self._listeners.remove(listener)

    def hydrate(self, sequence: int, operations: list[Any], context: Any = None) -> None:
        if not is_base(operations):
            raise ValueError("Replicated state snapshot is not a base operation batch")
        self._value = apply_immutable(None, operations)
        self._sequence = sequence
        self._deliver_all(context, {"kind": "hydrate", "sequence": sequence})

    def update(self, sequence: int, operations: list[Any], context: Any = None) -> None:
        if self._value is None or self._sequence is None:
            raise ValueError("Replicated state received an update before hydration")
        if sequence != self._sequence + 1:
            self.clear()
            raise ValueError("Replicated state update sequence has a gap")
        self._value = apply_immutable(self._value, operations)
        self._sequence = sequence
        self._deliver_all(context, {"kind": "update", "sequence": sequence})

    def clear(self) -> None:
        self._value = None
        self._sequence = None

    def _deliver_all(self, context: Any, delivery: dict[str, Any]) -> None:
        for listener in list(self._listeners):
            self._deliver(listener, context, delivery)

    def _deliver(self, listener: Callable[[T, Any, dict[str, Any]], None], context: Any, delivery: dict[str, Any]) -> None:
        try:
            if self._value is not None:
                listener(self._value, context, delivery)
        except Exception as error:
            self._on_error(error)


__all__ = [
    "ChordContext",
    "AbortSignal",
    "Context",
    "ContextKey",
    "Facet",
    "FacetHost",
    "FACET_BUNDLE_FORMAT",
    "FACET_BUNDLE_FORMAT_VERSION",
    "FACET_BUNDLE_MANIFEST_FILE",
    "BACKGROUND_CONTEXT",
    "TODO_CONTEXT",
    "DeltaTracker",
    "PathError",
    "REMOTE_SERVICE_ERROR_CODES",
    "ReplicatedState",
    "ReplicatedStateReplica",
    "RemoteServiceError",
    "RemoteServiceBinding",
    "RemoteServiceProvider",
    "Service",
    "ServiceHandle",
    "UnsafePathError",
    "apply",
    "apply_immutable",
    "combine_facet_loaders",
    "create_static_facet_loader",
    "create_context_key",
    "create_facet_host",
    "create_facet_bundle_loader",
    "create_service_catalogue_call",
    "create_loopback_service_transport",
    "create_remote_service_binding",
    "create_service_subscribe_call",
    "create_service_unsubscribe_call",
    "decoder",
    "decode_service_control_call",
    "define_service",
    "define_facet",
    "encoder",
    "is_base",
    "is_json_value",
    "is_remote_service_error_code",
    "is_replace",
    "overlap",
    "parse_service_call",
    "parse_service_catalogue",
    "parse_service_provider_update",
    "parse_service_subscription_snapshot",
    "parse_wire_service_provider_update",
    "parse_wire_service_subscription_snapshot",
    "track",
    "read_facet_bundle_artifact",
    "read_facet_bundle_manifest",
    "with_context_value",
    "with_cancel",
]
