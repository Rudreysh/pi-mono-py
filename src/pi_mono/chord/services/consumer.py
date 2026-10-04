"""Consumer-side Chord bindings for singleton and keyed services."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable

from ..context import BACKGROUND_CONTEXT, Context, with_cancel
from .errors import RemoteServiceError
from .provider import Service


def _error_reporter(error: Exception) -> None:
    return None


class _MemberSlot:
    def __init__(self, facade: "_Facade", name: str) -> None:
        self._facade = facade
        self._name = name
        self._kind: str | None = None
        self._expected: str | None = None
        self._state: Any = None

    @property
    def value(self) -> Any:
        self._assert("state")
        self._facade._assert_access()
        return None if self._state is None else self._state.value

    def subscribe(self, listener: Callable[[Any, Any, dict[str, Any]], None]) -> Callable[[], None]:
        self._assert("state")
        self._facade._assert_access()
        if self._state is None:
            from pi_mono.chord import ReplicatedStateReplica

            self._state = ReplicatedStateReplica(self._facade._on_error)
        return self._state.subscribe(listener)

    async def __call__(self, *args: Any) -> Any:
        self._assert("method")
        self._facade._assert_access()
        if not self._facade.active:
            raise RemoteServiceError("service_stale_instance", f"Remote service {self._facade.service_id} binding is closed")
        if not args or not isinstance(args[-1], Context):
            raise RemoteServiceError("service_invalid_value", f"Remote service method {self._facade.service_id}.{self._name} requires a trailing Context")
        return await self._facade._transport.invoke(
            {
                "serviceId": self._facade.service_id,
                **({} if self._facade.address is None else {"instance": self._facade.address}),
                "member": self._name,
                "args": list(args[:-1]),
            },
            args[-1],
        )

    def install(self, kind: str, sequence: int | None = None, ops: list[Any] | None = None, context: Any = None) -> None:
        self._set_kind(kind)
        if kind == "state":
            if self._state is None:
                from pi_mono.chord import ReplicatedStateReplica

                self._state = ReplicatedStateReplica(self._facade._on_error)
            self._state.hydrate(sequence, ops, context)

    def update(self, sequence: int, ops: list[Any], context: Any) -> None:
        if self._kind != "state" or self._state is None:
            raise RuntimeError(f"Remote service update targets non-state member {self._facade.service_id}.{self._name}")
        self._state.update(sequence, ops, context)

    def clear(self) -> None:
        if self._state is not None:
            self._state.clear()

    def _assert(self, expected: str) -> None:
        if self._expected is not None and self._expected != expected:
            raise RemoteServiceError("service_member_mismatch", f"Remote service member {self._facade.service_id}.{self._name} was used as two different kinds")
        self._expected = expected
        if self._kind is not None and self._kind != expected:
            raise RemoteServiceError("service_member_mismatch", f"Remote service member {self._facade.service_id}.{self._name} is {self._kind}, not {expected}")

    def _set_kind(self, kind: str) -> None:
        if self._kind is not None and self._kind != kind:
            raise RuntimeError(f"Remote service member {self._facade.service_id}.{self._name} changed kind")
        self._kind = kind
        if self._expected is not None and self._expected != kind:
            raise RemoteServiceError("service_member_mismatch", f"Remote service member {self._facade.service_id}.{self._name} is {kind}, not {self._expected}")


class _Facade:
    def __init__(self, service_id: str, address: dict[str, Any] | None, transport: Any, active: Callable[[], bool], assert_access: Callable[[], None], on_error: Callable[[Exception], None]) -> None:
        self.service_id = service_id
        self.address = address
        self._transport = transport
        self._is_active = active
        self._assert_access = assert_access
        self._on_error = on_error
        self._slots: dict[str, _MemberSlot] = {}
        self._descriptions: dict[str, str] = {}

    @property
    def active(self) -> bool:
        return self._is_active()

    def __getattr__(self, name: str) -> _MemberSlot:
        if name.startswith("_"):
            raise AttributeError(name)
        return self._slots.setdefault(name, _MemberSlot(self, name))

    def install(self, snapshot: dict[str, Any], context: Any) -> None:
        if snapshot.get("instance") != self.address:
            raise RuntimeError("Remote service snapshot has the wrong address")
        members = {member["name"]: member for member in snapshot["members"]}
        if len(members) != len(snapshot["members"]):
            raise RuntimeError("Remote service has invalid member descriptions")
        for name in self._slots:
            if name not in members:
                raise RemoteServiceError("service_member_not_found", f"Unknown remote service member {self.service_id}.{name}")
        self._descriptions = {name: member["kind"] for name, member in members.items()}
        for name, member in members.items():
            slot = self._slots.get(name)
            if slot is not None or member["kind"] == "state":
                slot = self._slots.setdefault(name, _MemberSlot(self, name))
                slot.install(member["kind"], member.get("sequence"), member.get("ops"), context)

    def update(self, member: str, sequence: int, ops: list[Any], context: Any) -> None:
        if self._descriptions.get(member) != "state":
            raise RuntimeError(f"Remote service update targets non-state member {self.service_id}.{member}")
        self._slots.setdefault(member, _MemberSlot(self, member)).update(sequence, ops, context)

    def clear(self) -> None:
        for slot in self._slots.values():
            slot.clear()


@dataclass
class _KeyedInstance:
    key: str
    generation: int
    facade: _Facade
    active: dict[str, bool]
    observers: dict[int, Callable[[], None]] = field(default_factory=dict)


class _KeyedBinding:
    def __init__(self, service: Service, owner: "RemoteServiceBinding") -> None:
        self.service = service
        self.owner = owner
        self.instances: dict[str, _KeyedInstance] = {}
        self.observers: dict[int, Callable[[Any, Context], Any]] = {}
        self.subscription: dict[str, Any] | None = None
        self.closed = False

    def observe(self, handler: Callable[[Any, Context], Any]) -> Callable[[], None]:
        token = id(handler) ^ id(self) ^ len(self.observers)
        self.observers[token] = handler
        for instance in self.instances.values():
            self._start_observer(token, handler, instance)
        if self.owner.bound and self.subscription is None:
            self.owner._start_keyed(self)

        def stop() -> None:
            self.observers.pop(token, None)
            for instance in self.instances.values():
                cancel = instance.observers.pop(token, None)
                if cancel is not None:
                    cancel()
            if not self.observers:
                self.close()
                self.owner._keyed.pop(self.service.id, None)

        return stop

    def install(self, snapshot: dict[str, Any], context: Context) -> None:
        address = snapshot.get("instance")
        if address is None:
            raise RuntimeError("Keyed service instance snapshot has no address")
        existing = self.instances.get(address["key"])
        if existing is not None:
            self._remove(existing)
        active = {"value": True}
        facade = _Facade(self.service.id, address, self.owner._transport, lambda: active["value"] and not self.closed and self.owner._bound, self.owner._assert_handle_access, self.owner._on_error)
        facade.install(snapshot, context)
        instance = _KeyedInstance(address["key"], address["generation"], facade, active)
        self.instances[instance.key] = instance
        for token, handler in self.observers.items():
            self._start_observer(token, handler, instance)

    def update(self, update: dict[str, Any], context: Context) -> None:
        kind = update["type"]
        if kind == "spawned":
            self.install(update["instance"], context)
        elif kind == "closed":
            instance = self.instances.get(update["instance"]["key"])
            if instance is not None and instance.generation == update["instance"]["generation"]:
                self._remove(instance)
        elif kind == "state":
            address = update.get("instance")
            if address is None:
                raise RuntimeError("Keyed state update has no instance address")
            instance = self.instances.get(address["key"])
            if instance is not None and instance.generation == address["generation"]:
                instance.facade.update(update["member"], update["sequence"], update["ops"], context)
        else:
            raise RuntimeError("Keyed service received a singleton lifecycle update")

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.subscription is not None:
            self.subscription["close"](BACKGROUND_CONTEXT)
            self.subscription = None
        for instance in list(self.instances.values()):
            self._remove(instance)

    def _remove(self, instance: _KeyedInstance) -> None:
        if self.instances.get(instance.key) is not instance:
            return
        del self.instances[instance.key]
        instance.active["value"] = False
        instance.facade.clear()
        for cancel in instance.observers.values():
            cancel()
        instance.observers.clear()

    def _start_observer(self, token: int, handler: Callable[[Any, Context], Any], instance: _KeyedInstance) -> None:
        if token in instance.observers:
            return
        context, cancel = with_cancel(BACKGROUND_CONTEXT)
        instance.observers[token] = cancel
        try:
            result = handler(instance.facade, context)
            if inspect.isawaitable(result):
                asyncio.create_task(self._watch(result, context))
        except Exception as error:
            if not context.abort_signal.aborted:
                self.owner._on_error(error)

    async def _watch(self, result: Any, context: Context) -> None:
        try:
            await result
        except Exception as error:
            if not context.abort_signal.aborted:
                self.owner._on_error(error)


class RemoteServiceBinding:
    def __init__(self, services: list[Service], transport: Any, on_error: Callable[[Exception], None] | None = None, assert_access: Callable[[], None] | None = None, bound: bool = True) -> None:
        ids = [service.id for service in services]
        if len(ids) != len(set(ids)):
            raise TypeError("Remote service binding has duplicate service IDs")
        self._services = {service.id: service for service in services}
        self._transport = transport
        self._on_error = on_error or _error_reporter
        self._assert_access = assert_access or (lambda: None)
        self._bound = bound
        self._disposed = False
        self._modes: dict[str, str] = {}
        self._singletons: dict[str, dict[str, Any]] = {}
        self._keyed: dict[str, _KeyedBinding] = {}

    @property
    def bound(self) -> bool:
        return self._bound and not self._disposed

    def use(self, service: Service) -> _Facade:
        self._assert_available(service, "singleton")
        binding = self._singletons.get(service.id)
        if binding is None:
            active = True
            facade = _Facade(service.id, None, self._transport, lambda: active and self.bound, self._assert_handle_access, self._on_error)
            binding = {"facade": facade, "subscription": None, "active": active}
            self._singletons[service.id] = binding
            if self.bound:
                self._start_singleton(service.id, binding)
        return binding["facade"]

    def observe(self, service: Service, handler: Callable[[Any, Context], Any]) -> Callable[[], None]:
        self._assert_available(service, "keyed")
        binding = self._keyed.get(service.id)
        if binding is None:
            binding = _KeyedBinding(service, self)
            self._keyed[service.id] = binding
        return binding.observe(handler)

    async def ready(self, _context: Context = BACKGROUND_CONTEXT) -> None:
        # Loopback subscriptions are synchronous. Support asynchronous custom transports too.
        pending = []
        for binding in self._singletons.values():
            pending.extend(binding.pop("pending", []))
        for binding in self._keyed.values():
            pending.extend(getattr(binding, "pending", []))
            binding.pending = []
        for item in pending:
            if inspect.isawaitable(item):
                await item

    async def rebind(self, bound: bool, _context: Context = BACKGROUND_CONTEXT) -> None:
        if self._disposed:
            raise RuntimeError("Remote service binding is disposed")
        self._bound = bound
        for binding in self._singletons.values():
            if binding["subscription"] is not None:
                binding["subscription"]["close"](_context)
                binding["subscription"] = None
            binding["facade"].clear()
            if bound:
                self._start_singleton(binding["facade"].service_id, binding)
        for keyed in list(self._keyed.values()):
            keyed.close()
            keyed.closed = False
            if bound and keyed.observers:
                self._start_keyed(keyed)

    async def dispose(self, _context: Context = BACKGROUND_CONTEXT) -> None:
        if self._disposed:
            return
        self._disposed = True
        for binding in self._singletons.values():
            binding["facade"].clear()
            if binding["subscription"] is not None:
                binding["subscription"]["close"](_context)
        for binding in self._keyed.values():
            binding.close()
        self._singletons.clear()
        self._keyed.clear()

    def _start_singleton(self, service_id: str, binding: dict[str, Any]) -> None:
        try:
            subscription = self._transport.subscribe(service_id, "singleton", lambda update, context: self._singleton_update(binding, update, context), BACKGROUND_CONTEXT)
            if inspect.isawaitable(subscription):
                binding.setdefault("pending", []).append(self._finish_singleton_start(binding, subscription))
            else:
                self._install_singleton(binding, subscription)
        except Exception as error:
            self._on_error(error)
            binding.setdefault("pending", []).append(_raise(error))

    async def _finish_singleton_start(self, binding: dict[str, Any], pending: Any) -> None:
        self._install_singleton(binding, await pending)

    def _install_singleton(self, binding: dict[str, Any], subscription: dict[str, Any]) -> None:
        snapshot = subscription["snapshot"]
        if snapshot["mode"] != "singleton" or len(snapshot["instances"]) != 1:
            raise RuntimeError("Remote service returned an invalid singleton snapshot")
        binding["subscription"] = subscription
        binding["facade"].install(snapshot["instances"][0], BACKGROUND_CONTEXT)
        subscription["activate"]()

    def _singleton_update(self, binding: dict[str, Any], update: dict[str, Any], context: Context) -> None:
        try:
            if update["type"] == "unavailable":
                binding["facade"].clear()
            elif update["type"] == "replaced":
                binding["facade"].install(update["snapshot"], context)
            elif update["type"] == "state" and "instance" not in update:
                binding["facade"].update(update["member"], update["sequence"], update["ops"], context)
        except Exception as error:
            self._on_error(error)

    def _start_keyed(self, binding: _KeyedBinding) -> None:
        try:
            subscription = self._transport.subscribe(binding.service.id, "keyed", lambda update, context: self._keyed_update(binding, update, context), BACKGROUND_CONTEXT)
            if inspect.isawaitable(subscription):
                binding.pending = [self._finish_keyed_start(binding, subscription)]
            else:
                self._install_keyed(binding, subscription)
        except Exception as error:
            self._on_error(error)
            binding.pending = [_raise(error)]

    async def _finish_keyed_start(self, binding: _KeyedBinding, pending: Any) -> None:
        self._install_keyed(binding, await pending)

    def _install_keyed(self, binding: _KeyedBinding, subscription: dict[str, Any]) -> None:
        snapshot = subscription["snapshot"]
        if snapshot["mode"] != "keyed" or snapshot["serviceId"] != binding.service.id:
            raise RuntimeError("Remote service returned an invalid keyed snapshot")
        binding.subscription = subscription
        for instance in snapshot["instances"]:
            binding.install(instance, BACKGROUND_CONTEXT)
        subscription["activate"]()

    def _keyed_update(self, binding: _KeyedBinding, update: dict[str, Any], context: Context) -> None:
        try:
            binding.update(update, context)
        except Exception as error:
            self._on_error(error)

    def _assert_available(self, service: Service, mode: str) -> None:
        if self._disposed:
            raise RuntimeError("Remote service binding is disposed")
        if service.local:
            raise RemoteServiceError("service_not_allowed", f"Service {service.id} is process-local")
        if service.id not in self._services:
            raise RemoteServiceError("service_not_allowed", f"Remote service {service.id} is not allowlisted")
        existing = self._modes.get(service.id)
        if existing is not None and existing != mode:
            raise RemoteServiceError("service_mode_mismatch", f"Remote service {service.id} is already used as {existing}")
        self._modes[service.id] = mode

    def _assert_handle_access(self) -> None:
        if self._disposed:
            raise RuntimeError("Remote service binding is disposed")
        self._assert_access()


async def _raise(error: Exception) -> None:
    raise error


def create_remote_service_binding(*, services: list[Service], transport: Any, on_error: Callable[[Exception], None] | None = None, assert_access: Callable[[], None] | None = None, bound: bool = True) -> RemoteServiceBinding:
    return RemoteServiceBinding(services, transport, on_error, assert_access, bound)
