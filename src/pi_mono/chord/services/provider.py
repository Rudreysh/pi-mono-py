"""In-process provider for singleton and keyed Chord services."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from .errors import RemoteServiceError

ServiceMode = Literal["singleton", "keyed"]


@dataclass(frozen=True)
class Service:
    id: str
    local: bool = False


def define_service(service_id: str, *, local: bool = False) -> Service:
    if not isinstance(service_id, str) or not service_id:
        raise TypeError("Service ID must not be empty")
    if service_id.startswith("$chord."):
        raise TypeError("Service IDs beginning with $chord. are reserved")
    return Service(service_id, local)


@dataclass
class _Instance:
    implementation: Any
    members: dict[str, tuple[str, Any]]
    address: dict[str, Any] | None
    remove_listeners: list[Callable[[], None]]
    active: bool = True


@dataclass
class _Subscription:
    listener: Callable[[dict[str, Any], Any], None]
    buffered: list[tuple[dict[str, Any], Any]] = field(default_factory=list)
    active: bool = False
    closed: bool = False


@dataclass
class _Registration:
    service: Service
    mode: ServiceMode
    singleton: _Instance | None = None
    singleton_shape: dict[str, str] | None = None
    instances: dict[str, _Instance] = field(default_factory=dict)
    generations: dict[str, int] = field(default_factory=dict)
    subscriptions: list[_Subscription] = field(default_factory=list)


class RemoteServiceProvider:
    """Owns published implementations and their consumer subscriptions."""

    def __init__(self, entries: list[Service | dict[str, Any]]) -> None:
        registrations: dict[str, _Registration] = {}
        for entry in entries:
            service, mode = self._definition(entry)
            if service.local:
                raise TypeError(f"Local service {service.id} cannot be published remotely")
            if service.id in registrations:
                raise TypeError("Remote service catalogue contains duplicate IDs")
            registrations[service.id] = _Registration(service, mode)
        self._registrations = registrations
        self._disposed = False

    @property
    def catalogue(self) -> list[dict[str, str]]:
        return [{"serviceId": entry.service.id, "mode": entry.mode} for entry in self._registrations.values()]

    def provide(self, service: Service, implementation: Any) -> None:
        registration = self._registration(service, "singleton")
        if registration.singleton is not None:
            raise RemoteServiceError("service_mode_mismatch", f"Remote service {service.id} already has a provider")
        instance = self._create_instance(registration, implementation, None)
        registration.singleton = instance
        registration.singleton_shape = self._shape(instance)

    def validate_replacement(self, service: Service, implementation: Any) -> None:
        registration = self._registration(service, "singleton")
        instance = self._create_instance(registration, implementation, None, subscribe=False)
        self._assert_singleton_shape(registration, self._shape(instance))

    def replace(self, service: Service, implementation: Any) -> None:
        registration = self._registration(service, "singleton")
        replacement = self._create_instance(registration, implementation, None)
        shape = self._shape(replacement)
        self._assert_singleton_shape(registration, shape)
        previous = registration.singleton
        if previous is not None:
            self._deactivate(previous)
        registration.singleton = replacement
        registration.singleton_shape = shape
        self._emit(registration, {"type": "replaced", "snapshot": self._snapshot_instance(replacement)}, None)

    def withdraw(self, service: Service) -> None:
        registration = self._registration(service, "singleton")
        if registration.singleton is None:
            return
        self._deactivate(registration.singleton)
        registration.singleton = None
        self._emit(registration, {"type": "unavailable"}, None)

    def use(self, service: Service) -> Any:
        registration = self._registration(service, "singleton")
        if registration.singleton is None:
            raise RemoteServiceError("service_not_found", f"Remote service {service.id} has no local provider")
        return registration.singleton.implementation

    def spawn(self, service: Service, key: str, implementation: Any) -> Callable[[], None]:
        registration = self._registration(service, "keyed")
        if not isinstance(key, str) or not key:
            raise TypeError("Remote service instance key must not be empty")
        if key in registration.instances:
            raise RemoteServiceError("service_mode_mismatch", f"Remote service {service.id} already has a live instance with key {key}")
        generation = registration.generations.get(key, 0) + 1
        registration.generations[key] = generation
        instance = self._create_instance(registration, implementation, {"key": key, "generation": generation})
        registration.instances[key] = instance
        self._emit(registration, {"type": "spawned", "instance": self._snapshot_instance(instance)}, None)

        closed = False

        def close() -> None:
            nonlocal closed
            if closed or registration.instances.get(key) is not instance:
                return
            closed = True
            del registration.instances[key]
            self._deactivate(instance)
            self._emit(registration, {"type": "closed", "instance": instance.address}, None)

        return close

    async def invoke(self, call: dict[str, Any], context: Any = None) -> Any:
        self._assert_active()
        service_id = call["serviceId"]
        registration = self._registration_by_id(service_id)
        instance = self._resolve_instance(registration, call.get("instance"))
        member = instance.members.get(call["member"])
        if member is None:
            raise RemoteServiceError("service_member_not_found", f"Unknown remote service member {service_id}.{call['member']}")
        if member[0] != "method":
            raise RemoteServiceError("service_member_mismatch", f"Remote service member {service_id}.{call['member']} is not a method")
        result = member[1](*call.get("args", []), context)
        return await result if inspect.isawaitable(result) else result

    def subscribe(self, service_id: str, mode: ServiceMode, listener: Callable[[dict[str, Any], Any], None], _context: Any = None) -> dict[str, Any]:
        self._assert_active()
        registration = self._registration_by_id(service_id, mode)
        if mode == "singleton" and registration.singleton is None:
            raise RemoteServiceError("service_not_found", f"Remote service {service_id} has no provider")
        self._publish_pending(registration)
        subscription = _Subscription(listener)
        registration.subscriptions.append(subscription)

        def activate() -> None:
            if subscription.closed or subscription.active:
                return
            subscription.active = True
            failures: list[Exception] = []
            for update, update_context in subscription.buffered:
                try:
                    listener(update, update_context)
                except Exception as error:
                    failures.append(error)
            subscription.buffered.clear()
            if failures:
                raise failures[0]

        def close(_close_context: Any = None) -> None:
            if subscription.closed:
                return
            subscription.closed = True
            subscription.buffered.clear()
            registration.subscriptions.remove(subscription)

        return {"snapshot": self._snapshot(registration), "activate": activate, "close": close}

    def dispose(self) -> None:
        if self._disposed:
            return
        for registration in self._registrations.values():
            if registration.singleton is not None:
                self._deactivate(registration.singleton)
                registration.singleton = None
            for instance in list(registration.instances.values()):
                self._deactivate(instance)
            registration.instances.clear()
            for subscription in registration.subscriptions:
                if subscription.active:
                    subscription.listener({"type": "unavailable"}, None)
                else:
                    subscription.buffered.append(({"type": "unavailable"}, None))
        self._disposed = True

    def _registration(self, service: Service, mode: ServiceMode) -> _Registration:
        if service.local:
            raise RemoteServiceError("service_not_allowed", f"Service {service.id} is process-local")
        return self._registration_by_id(service.id, mode)

    def _registration_by_id(self, service_id: str, mode: ServiceMode | None = None) -> _Registration:
        self._assert_active()
        registration = self._registrations.get(service_id)
        if registration is None:
            raise RemoteServiceError("service_not_allowed", f"Remote service {service_id} is not allowlisted")
        if mode is not None and registration.mode != mode:
            raise RemoteServiceError("service_mode_mismatch", f"Remote service {service_id} is {registration.mode}")
        return registration

    def _create_instance(self, registration: _Registration, implementation: Any, address: dict[str, Any] | None, *, subscribe: bool = True) -> _Instance:
        if not hasattr(implementation, "__dict__") and not isinstance(implementation, dict):
            raise TypeError(f"Remote service {registration.service.id} implementation must be an object")
        if isinstance(implementation, dict):
            values = implementation
        else:
            values = dict(vars(implementation))
            for name in dir(implementation):
                if not name.startswith("_") and name not in values:
                    values[name] = getattr(implementation, name)
        members: dict[str, tuple[str, Any]] = {}
        remove_listeners: list[Callable[[], None]] = []
        for name, value in values.items():
            if name.startswith("_"):
                continue
            if hasattr(value, "subscribe_source") and hasattr(value, "sequence") and hasattr(value, "value"):
                members[name] = ("state", value)
            elif callable(value):
                members[name] = ("method", value)
            else:
                raise RemoteServiceError("service_invalid_value", f"Remote service {registration.service.id}.{name} is not remotely exposable")
        instance = _Instance(implementation, members, address, remove_listeners)
        if subscribe:
            for name, (kind, value) in members.items():
                if kind != "state":
                    continue
                remove_listeners.append(value.subscribe_source(
                    lambda ops, sequence, context, name=name: self._state_update(registration, instance, name, sequence, ops, context)
                ))
        return instance

    def _state_update(self, registration: _Registration, instance: _Instance, member: str, sequence: int, ops: list[Any], context: Any) -> None:
        if not instance.active:
            return
        update: dict[str, Any] = {"type": "state", "member": member, "sequence": sequence, "ops": ops}
        if instance.address is not None:
            update["instance"] = instance.address
        self._emit(registration, update, context)

    @staticmethod
    def _shape(instance: _Instance) -> dict[str, str]:
        return {name: kind for name, (kind, _value) in instance.members.items()}

    def _assert_singleton_shape(self, registration: _Registration, shape: dict[str, str]) -> None:
        if registration.singleton_shape is not None and registration.singleton_shape != shape:
            raise RemoteServiceError("service_member_mismatch", f"Remote service {registration.service.id} replacement must preserve its member shape")

    def _resolve_instance(self, registration: _Registration, address: dict[str, Any] | None) -> _Instance:
        if registration.mode == "singleton":
            if address is not None:
                raise RemoteServiceError("service_mode_mismatch", f"Remote service {registration.service.id} is singleton")
            if registration.singleton is None:
                raise RemoteServiceError("service_not_found", f"Remote service {registration.service.id} has no provider")
            return registration.singleton
        if address is None:
            raise RemoteServiceError("service_mode_mismatch", f"Remote service {registration.service.id} is keyed")
        instance = registration.instances.get(address.get("key"))
        if instance is None:
            raise RemoteServiceError("service_instance_not_found", f"Remote service instance {registration.service.id} is not found")
        if instance.address != address:
            raise RemoteServiceError("service_stale_instance", f"Remote service instance {registration.service.id} is stale")
        return instance

    def _snapshot(self, registration: _Registration) -> dict[str, Any]:
        instances = [registration.singleton] if registration.mode == "singleton" else list(registration.instances.values())
        return {
            "serviceId": registration.service.id,
            "mode": registration.mode,
            "instances": [self._snapshot_instance(instance) for instance in instances if instance is not None],
        }

    @staticmethod
    def _snapshot_instance(instance: _Instance) -> dict[str, Any]:
        members = []
        for name, (kind, value) in instance.members.items():
            if kind == "method":
                members.append({"name": name, "kind": "method"})
            else:
                members.append({"name": name, "kind": "state", "sequence": value.sequence, "ops": [["r", value.value]]})
        snapshot: dict[str, Any] = {"members": members}
        if instance.address is not None:
            snapshot["instance"] = dict(instance.address)
        return snapshot

    @staticmethod
    def _deactivate(instance: _Instance) -> None:
        if not instance.active:
            return
        instance.active = False
        for remove in instance.remove_listeners:
            remove()

    def _publish_pending(self, registration: _Registration) -> None:
        instances = [registration.singleton] if registration.mode == "singleton" else registration.instances.values()
        for instance in instances:
            if instance is None:
                continue
            for kind, value in instance.members.values():
                if kind == "state":
                    value.publish()

    @staticmethod
    def _definition(entry: Service | dict[str, Any]) -> tuple[Service, ServiceMode]:
        if isinstance(entry, Service):
            return entry, "singleton"
        candidate = entry.get("service", entry)
        service = candidate if isinstance(candidate, Service) else Service(candidate["id"], candidate.get("local", False))
        mode = entry.get("mode", "singleton")
        if mode not in {"singleton", "keyed"}:
            raise TypeError("Remote service mode must be singleton or keyed")
        return service, mode

    def _emit(self, registration: _Registration, update: dict[str, Any], context: Any) -> None:
        failures: list[Exception] = []
        for subscription in list(registration.subscriptions):
            if subscription.closed:
                continue
            if subscription.active:
                try:
                    subscription.listener(update, context)
                except Exception as error:
                    failures.append(error)
            else:
                subscription.buffered.append((update, context))
        if failures:
            raise failures[0]

    def _assert_active(self) -> None:
        if self._disposed:
            raise RuntimeError("Remote service provider is disposed")


def create_loopback_service_transport(provider: RemoteServiceProvider) -> RemoteServiceProvider:
    return provider
