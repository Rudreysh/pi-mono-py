"""Facet composition host for Chord services."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .context import BACKGROUND_CONTEXT, Context, with_cancel
from .services.consumer import RemoteServiceBinding, create_remote_service_binding
from .services.provider import RemoteServiceProvider, Service


@dataclass(frozen=True)
class Facet:
    id: str
    setup: Callable[[Any], Any]


def define_facet(facet: Facet | dict[str, Any]) -> Facet:
    if isinstance(facet, Facet):
        return facet
    return Facet(facet["id"], facet["setup"])


@dataclass
class LoadedFacets:
    facets: list[Any]
    dispose: Callable[[], Awaitable[None] | None]


class StaticFacetLoader:
    def __init__(self, facets: list[Any]) -> None:
        self._facets = list(facets)

    async def load(self) -> LoadedFacets:
        async def dispose() -> None:
            return None

        return LoadedFacets(self._facets, dispose)


def create_static_facet_loader(facets: list[Any]) -> StaticFacetLoader:
    return StaticFacetLoader(facets)


class CombinedFacetLoader:
    def __init__(self, loaders: list[Any]) -> None:
        self._loaders = list(loaders)

    async def load(self) -> LoadedFacets:
        loaded: list[LoadedFacets] = []
        try:
            for loader in self._loaders:
                loaded.append(await loader.load())
        except Exception:
            await _dispose_all(reversed(loaded))
            raise
        disposed = False

        async def dispose() -> None:
            nonlocal disposed
            if disposed:
                return
            disposed = True
            await _dispose_all(reversed(loaded))

        return LoadedFacets([facet for item in loaded for facet in item.facets], dispose)


def combine_facet_loaders(loaders: list[Any]) -> CombinedFacetLoader:
    return CombinedFacetLoader(loaders)


async def _dispose_all(loaded: Any) -> None:
    errors: list[Exception] = []
    for entry in loaded:
        try:
            result = entry.dispose()
            if inspect.isawaitable(result):
                await result
        except Exception as error:
            errors.append(error)
    if errors:
        raise errors[0]


class _Lifecycle:
    def __init__(self, facet_id: str) -> None:
        self.id = facet_id
        self.state = "setting_up"
        self.service_access = False
        self.effects: list[Callable[[], Any]] = []
        self.activators: list[Callable[[], Any]] = []
        self.observations: list[Callable[[], Callable[[], Any]]] = []

    def setting_up(self, operation: str) -> None:
        if self.state != "setting_up":
            raise RuntimeError(f"Facet {self.id} can {operation} only during setup")

    def running(self, operation: str) -> None:
        if self.state not in {"setting_up", "active"}:
            raise RuntimeError(f"Facet {self.id} cannot {operation} while {self.state}")

    def assert_access(self) -> None:
        if not self.service_access:
            raise RuntimeError(f"Facet {self.id} service handles cannot be used while {self.state}")

    def own(self, disposal: Callable[[], Any]) -> None:
        self.running("own resources")
        self.effects.append(disposal)

    def observe(self, start: Callable[[], Callable[[], Any]]) -> None:
        self.setting_up("observe services")
        self.observations.append(start)

    def on_activate(self, callback: Callable[[], Any]) -> None:
        self.setting_up("register activation callbacks")
        self.activators.append(callback)

    def prepared(self) -> None:
        self.setting_up("finish setup")
        self.state = "prepared"

    async def activate(self) -> None:
        if self.state != "prepared":
            raise RuntimeError(f"Facet {self.id} is not prepared")
        self.state = "active"
        self.service_access = True
        for start in self.observations:
            self.effects.append(start())
        for callback in self.activators:
            result = callback()
            if inspect.isawaitable(result):
                await result

    async def dispose(self) -> None:
        if self.state == "dead":
            return
        self.state = "disposing"
        self.service_access = False
        errors: list[Exception] = []
        for disposal in reversed(self.effects):
            try:
                result = disposal()
                if inspect.isawaitable(result):
                    await result
            except Exception as error:
                errors.append(error)
        self.effects.clear()
        self.state = "dead"
        if errors:
            raise errors[0]


class _ServiceView:
    """A guarded, stable view over a target replaced by the host on reload."""

    def __init__(self, slot: "_SingletonSlot", assert_access: Callable[[], None]) -> None:
        self._slot = slot
        self._assert_access = assert_access

    def __getattr__(self, name: str) -> Any:
        self._assert_access()
        value = getattr(self._slot.resolve(), name)
        if callable(value):
            def invoke(*args: Any, **kwargs: Any) -> Any:
                self._assert_access()
                return getattr(self._slot.resolve(), name)(*args, **kwargs)
            return invoke
        if hasattr(value, "subscribe") and hasattr(value, "value"):
            return _StateView(lambda: getattr(self._slot.resolve(), name), self._assert_access)
        return value


class _StateView:
    def __init__(self, resolve: Callable[[], Any], assert_access: Callable[[], None]) -> None:
        self._resolve = resolve
        self._assert_access = assert_access

    @property
    def value(self) -> Any:
        self._assert_access()
        return self._resolve().value

    def subscribe(self, listener: Callable[..., Any]) -> Callable[[], None]:
        self._assert_access()
        return self._resolve().subscribe(listener)


class _ObservationView:
    """Adds the observing facet's lifecycle fence to a keyed service facade."""

    def __init__(self, target: Any, assert_access: Callable[[], None]) -> None:
        self._target = target
        self._assert_access = assert_access

    def __getattr__(self, name: str) -> Any:
        self._assert_access()
        value = getattr(self._target, name)
        descriptions = getattr(self._target, "_descriptions", {})
        if descriptions.get(name) == "state":
            return _StateView(lambda: getattr(self._target, name), self._assert_access)
        if callable(value):
            def invoke(*args: Any, **kwargs: Any) -> Any:
                self._assert_access()
                return getattr(self._target, name)(*args, **kwargs)
            return invoke
        return value


class _SingletonSlot:
    def __init__(self, service_id: str) -> None:
        self.service_id = service_id
        self.target: Any = None

    def view(self, assert_access: Callable[[], None]) -> _ServiceView:
        return _ServiceView(self, assert_access)

    def bind(self, target: Any) -> None:
        self.target = target

    def resolve(self) -> Any:
        if self.target is None:
            raise RuntimeError(f"Service {self.service_id} is disconnected")
        return self.target


@dataclass
class _LocalInstance:
    key: str
    generation: int
    service: Any
    cancellations: dict[int, Callable[[], None]] = field(default_factory=dict)


class _LocalKeyedRegistry:
    def __init__(self, on_error: Callable[[Exception], None]) -> None:
        self._on_error = on_error
        self._instances: dict[str, dict[str, _LocalInstance]] = {}
        self._generations: dict[str, dict[str, int]] = {}
        self._observers: dict[str, dict[int, Callable[[Any, Context], Any]]] = {}

    def spawn(self, service: Service, key: str, implementation: Any) -> Callable[[], None]:
        if not key:
            raise TypeError("Local service instance key must not be empty")
        entries = self._instances.setdefault(service.id, {})
        if key in entries:
            raise RuntimeError(f"Local service {service.id} already has a live instance with key {key}")
        generation = self._generations.setdefault(service.id, {}).get(key, 0) + 1
        self._generations[service.id][key] = generation
        entry = _LocalInstance(key, generation, implementation)
        entries[key] = entry
        for token, handler in self._observers.get(service.id, {}).items():
            self._start(service.id, token, handler, entry)

        def close() -> None:
            if entries.get(key) is not entry:
                return
            del entries[key]
            for cancel in entry.cancellations.values():
                cancel()
            entry.cancellations.clear()

        return close

    def observe(self, service: Service, handler: Callable[[Any, Context], Any]) -> Callable[[], None]:
        token = id(handler) ^ len(self._observers.get(service.id, {}))
        observers = self._observers.setdefault(service.id, {})
        observers[token] = handler
        for entry in self._instances.get(service.id, {}).values():
            self._start(service.id, token, handler, entry)

        def stop() -> None:
            observers.pop(token, None)
            for entry in self._instances.get(service.id, {}).values():
                cancel = entry.cancellations.pop(token, None)
                if cancel:
                    cancel()

        return stop

    def dispose(self) -> None:
        for entries in self._instances.values():
            for entry in entries.values():
                for cancel in entry.cancellations.values():
                    cancel()
        self._instances.clear()
        self._observers.clear()

    def _start(self, service_id: str, token: int, handler: Callable[[Any, Context], Any], entry: _LocalInstance) -> None:
        if token in entry.cancellations:
            return
        context, cancel = with_cancel(BACKGROUND_CONTEXT)
        entry.cancellations[token] = cancel
        try:
            result = handler(entry.service, context)
            if inspect.isawaitable(result):
                asyncio.create_task(self._watch(result, context))
        except Exception as error:
            self._on_error(error)

    async def _watch(self, result: Any, context: Context) -> None:
        try:
            await result
        except Exception as error:
            if not context.abort_signal.aborted:
                self._on_error(error)


class _Spawner:
    def __init__(self, lifecycle: _Lifecycle, service: Service) -> None:
        self._lifecycle = lifecycle
        self.service = service
        self._installer: Callable[[str, Any], Callable[[], None]] | None = None
        self._entries: dict[str, tuple[Any, Callable[[], None] | None]] = {}

    def connect(self, installer: Callable[[str, Any], Callable[[], None]]) -> None:
        if self._installer is not None:
            raise RuntimeError("Facet service provider is already connected")
        self._installer = installer
        for key, (implementation, _) in list(self._entries.items()):
            self._entries[key] = (implementation, installer(key, implementation))

    def spawn(self, key: str, implementation: Any) -> Callable[[], None]:
        self._lifecycle.running("spawn service instances")
        if self._lifecycle.state != "active":
            raise RuntimeError(f"Facet {self._lifecycle.id} can spawn service instances only while active")
        if not key:
            raise TypeError("Facet service instance key must not be empty")
        if key in self._entries:
            raise RuntimeError(f"Facet service already has a live instance with key {key}")
        release = self._installer(key, implementation) if self._installer else None
        self._entries[key] = (implementation, release)

        def close() -> None:
            entry = self._entries.pop(key, None)
            if entry and entry[1]:
                entry[1]()

        self._lifecycle.own(close)
        return close


@dataclass
class _Provision:
    service: Service
    mode: str
    implementation: Any = None
    spawner: _Spawner | None = None


@dataclass
class _Runtime:
    facet: Facet
    lifecycle: _Lifecycle
    requires: dict[str, tuple[Service, str]] = field(default_factory=dict)
    provisions: list[_Provision] = field(default_factory=list)
    singleton_views: dict[str, _ServiceView] = field(default_factory=dict)


class FacetHost:
    def __init__(self, facets: list[Facet], on_error: Callable[[Exception], None] | None = None, service_sources: list[Any] | None = None) -> None:
        self._initial = facets
        self._on_error = on_error or (lambda _error: None)
        self._service_sources = service_sources or []
        self._runtimes: dict[str, _Runtime] = {}
        self._order: list[str] = []
        self._slots: dict[str, _SingletonSlot] = {}
        self._local_keyed = _LocalKeyedRegistry(self._on_error)
        self._provider: RemoteServiceProvider | None = None
        self._internal: RemoteServiceBinding | None = None
        self._external: dict[str, tuple[Service, str, Any]] = {}
        self._source_bindings: dict[int, Any] = {}
        self._phase = "setup"

    @property
    def services(self) -> RemoteServiceProvider:
        if self._provider is None:
            raise RuntimeError("Facet service provider is not assembled")
        return self._provider

    async def activate(self) -> None:
        self._validate_ids(self._initial, "Facet IDs must be unique within a generation")
        try:
            for facet in self._initial:
                runtime = self._setup(facet)
                self._runtimes[facet.id] = runtime
            external = await self._resolve_external(list(self._runtimes.values()))
            self._order = self._validate_graph(list(self._runtimes.values()), external)
            await self._assemble(list(self._runtimes.values()), external)
            self._phase = "activating"
            for facet_id in self._order:
                await self._runtimes[facet_id].lifecycle.activate()
            self._phase = "active"
        except Exception:
            await self._terminate()
            raise

    async def reload(self, facets: list[Facet]) -> None:
        if self._phase != "active":
            raise RuntimeError(f"Facet host cannot reload while {self._phase}")
        self._validate_ids(facets, "Reloaded facet IDs must be unique")
        staged: dict[str, _Runtime] = {}
        try:
            for facet in facets:
                previous = self._runtimes.get(facet.id)
                if previous is None:
                    raise RuntimeError(f"Facet {facet.id} is not active")
                candidate = self._setup(facet)
                if not self._same_shape(previous, candidate):
                    raise RuntimeError(f"Reloaded facet {facet.id} must preserve its service requirements and provisions")
                staged[facet.id] = candidate
            self._phase = "reloading"
            for facet_id in self._order:
                if facet_id in staged:
                    await staged[facet_id].lifecycle.activate()
            previous = {facet_id: self._runtimes[facet_id] for facet_id in staged}
            for facet_id, candidate in staged.items():
                for provision in candidate.provisions:
                    if provision.mode == "singleton":
                        self._replace_singleton(provision)
            for runtime in reversed(list(previous.values())):
                await runtime.lifecycle.dispose()
            for facet_id, candidate in staged.items():
                for provision in candidate.provisions:
                    if provision.mode == "keyed":
                        self._connect_spawner(provision)
                self._runtimes[facet_id] = candidate
            self._phase = "active"
        except Exception:
            for runtime in staged.values():
                await runtime.lifecycle.dispose()
            self._phase = "dead"
            await self._terminate()
            raise

    async def dispose(self) -> None:
        if self._phase == "dead":
            return
        if self._phase != "active":
            raise RuntimeError(f"Facet host cannot be disposed while {self._phase}")
        await self._terminate()

    def _setup(self, facet: Facet) -> _Runtime:
        if not facet.id:
            raise RuntimeError("Facet ID must not be empty")
        lifecycle = _Lifecycle(facet.id)
        runtime = _Runtime(facet, lifecycle)
        result = facet.setup(self._environment(runtime))
        if inspect.isawaitable(result):
            if inspect.iscoroutine(result):
                result.close()
            raise RuntimeError(f"Facet {facet.id} setup must be synchronous")
        lifecycle.prepared()
        return runtime

    def _environment(self, runtime: _Runtime) -> Any:
        host = self

        class Environment:
            def use(self, service: Service) -> _ServiceView:
                runtime.lifecycle.setting_up("acquire services")
                host._reference(runtime.requires, service, "singleton")
                return runtime.singleton_views.setdefault(service.id, host._slots.setdefault(service.id, _SingletonSlot(service.id)).view(runtime.lifecycle.assert_access))

            def observe(self, service: Service, handler: Callable[[Any, Context], Any]) -> None:
                runtime.lifecycle.setting_up("observe services")
                host._reference(runtime.requires, service, "keyed")

                def start() -> Callable[[], Any]:
                    def observe(target: Any, context: Context) -> Any:
                        def assert_observation_access() -> None:
                            runtime.lifecycle.assert_access()
                            if context.abort_signal is not None and context.abort_signal.aborted:
                                raise RuntimeError(f"Keyed service {service.id} observation is closed")

                        return handler(_ObservationView(target, assert_observation_access), context)

                    if service.local:
                        return host._local_keyed.observe(service, observe)
                    external = host._external.get(service.id)
                    if external is not None:
                        return host._source_bindings[id(external[2])].observe(service, observe)
                    if host._internal is None:
                        raise RuntimeError("Facet remote services are not assembled")
                    return host._internal.observe(service, observe)

                runtime.lifecycle.observe(start)

            def provide(self, service: Service, implementation: Any) -> None:
                runtime.lifecycle.setting_up("provide services")
                host._assert_provision_unique(runtime, service, "singleton")
                runtime.provisions.append(_Provision(service, "singleton", implementation=implementation))

            def provide_many(self, service: Service) -> _Spawner:
                runtime.lifecycle.setting_up("provide service instances")
                host._assert_provision_unique(runtime, service, "keyed")
                spawner = _Spawner(runtime.lifecycle, service)
                runtime.provisions.append(_Provision(service, "keyed", spawner=spawner))
                return spawner

            def replicated_state(self, initial: Any) -> Any:
                runtime.lifecycle.running("create replicated state")
                from pi_mono.chord import ReplicatedState

                return ReplicatedState(initial)

            def own(self, disposal: Callable[[], Any]) -> None:
                runtime.lifecycle.own(disposal)

            def on_activate(self, callback: Callable[[], Any]) -> None:
                runtime.lifecycle.on_activate(callback)

            def on_deactivate(self, callback: Callable[[], Any]) -> None:
                runtime.lifecycle.own(callback)

            provideMany = provide_many
            onActivate = on_activate
            onDeactivate = on_deactivate
            replicatedState = replicated_state

        return Environment()

    @staticmethod
    def _assert_provision_unique(runtime: _Runtime, service: Service, mode: str) -> None:
        for provision in runtime.provisions:
            if provision.service.id == service.id:
                if provision.mode != mode:
                    raise RuntimeError(f"Service {service.id} is used as both singleton and keyed")
                raise RuntimeError(f"Facet {runtime.facet.id} provides service {service.id} more than once")

    @staticmethod
    def _reference(target: dict[str, tuple[Service, str]], service: Service, mode: str) -> None:
        existing = target.get(service.id)
        if existing is not None and existing[1] != mode:
            raise RuntimeError(f"Service {service.id} is used as both singleton and keyed")
        target[service.id] = (service, mode)

    def _validate_graph(self, runtimes: list[_Runtime], external: dict[str, tuple[Service, str, Any]]) -> list[str]:
        offered: dict[str, tuple[str | None, str]] = {
            service_id: (None, mode) for service_id, (_service, mode, _source) in external.items()
        }
        for runtime in runtimes:
            for provision in runtime.provisions:
                if provision.service.id in offered:
                    raise RuntimeError(f"Service {provision.service.id} is provided by both {offered[provision.service.id][0]} and {runtime.facet.id}")
                offered[provision.service.id] = (runtime.facet.id, provision.mode)
        dependencies = {runtime.facet.id: set() for runtime in runtimes}
        for runtime in runtimes:
            for service, mode in runtime.requires.values():
                provider = offered.get(service.id)
                if provider is None:
                    raise RuntimeError(f"Facet {runtime.facet.id} requires local/{service.id}/{mode}, but no facet provides it")
                if provider[1] != mode:
                    raise RuntimeError(f"Facet {runtime.facet.id} requires {service.id} as {mode}, but {provider[0]} provides it as {provider[1]}")
                if provider[0] is not None and provider[0] != runtime.facet.id:
                    dependencies[runtime.facet.id].add(provider[0])
        order: list[str] = []
        pending = dict(dependencies)
        while pending:
            ready = [runtime.facet.id for runtime in runtimes if runtime.facet.id in pending and not pending[runtime.facet.id]]
            if not ready:
                raise RuntimeError(f"Facet dependency cycle: {', '.join(pending)}")
            for facet_id in ready:
                order.append(facet_id)
                del pending[facet_id]
                for values in pending.values():
                    values.discard(facet_id)
        return order

    async def _assemble(self, runtimes: list[_Runtime], external: dict[str, tuple[Service, str, Any]]) -> None:
        provisions = [provision for runtime in runtimes for provision in runtime.provisions]
        remote = [provision for provision in provisions if not provision.service.local]
        self._provider = RemoteServiceProvider([{"service": provision.service, "mode": provision.mode} for provision in remote])
        self._internal = create_remote_service_binding(services=[provision.service for provision in remote], transport=self._provider, bound=False, assert_access=self._assert_service_target_access, on_error=self._on_error)
        for provision in provisions:
            if provision.mode == "singleton":
                if provision.service.local:
                    self._slots.setdefault(provision.service.id, _SingletonSlot(provision.service.id)).bind(provision.implementation)
                else:
                    self._provider.provide(provision.service, provision.implementation)
                    self._slots.setdefault(provision.service.id, _SingletonSlot(provision.service.id)).bind(provision.implementation)
            else:
                self._connect_spawner(provision)
        for service_id, (service, mode, source) in external.items():
            if mode == "singleton":
                self._slots.setdefault(service_id, _SingletonSlot(service_id)).bind(self._source_bindings[id(source)].use(service))
        # Internal keyed consumers subscribe only after their facets activate.
        await self._internal.rebind(True, BACKGROUND_CONTEXT)
        bindings = {id(binding): binding for binding in self._source_bindings.values()}
        for binding in bindings.values():
            result = binding.ready(BACKGROUND_CONTEXT)
            if inspect.isawaitable(result):
                await result

    async def _resolve_external(self, runtimes: list[_Runtime]) -> dict[str, tuple[Service, str, Any]]:
        offered: dict[str, tuple[str, Any]] = {}
        for source in self._service_sources:
            entries = await source.catalogue(BACKGROUND_CONTEXT)
            for entry in entries:
                service_id, mode = entry["serviceId"], entry["mode"]
                if service_id in offered:
                    raise RuntimeError(f"Facet host service {service_id} is offered by more than one source")
                offered[service_id] = (mode, source)
        local = {provision.service.id for runtime in runtimes for provision in runtime.provisions}
        external: dict[str, tuple[Service, str, Any]] = {}
        for runtime in runtimes:
            for service, mode in runtime.requires.values():
                if service.id in local or service.id in external:
                    continue
                candidate = offered.get(service.id)
                if candidate is None:
                    deferred = [
                        source
                        for source in self._service_sources
                        if getattr(source, "accepts_unavailable_services", getattr(source, "acceptsUnavailableServices", False))
                    ]
                    if len(deferred) > 1:
                        raise RuntimeError(f"Facet host service {service.id} has more than one deferred source")
                    if deferred:
                        candidate = (mode, deferred[0])
                if candidate is not None:
                    external[service.id] = (service, candidate[0], candidate[1])
        grouped: dict[int, tuple[Any, list[Service]]] = {}
        for service, _mode, source in external.values():
            grouped.setdefault(id(source), (source, []))[1].append(service)
        for source_id, (source, services) in grouped.items():
            self._source_bindings[source_id] = source.open({
                "services": services,
                "assert_access": self._assert_service_target_access,
                "on_error": self._on_error,
            })
        self._external = external
        return external

    def _replace_singleton(self, provision: _Provision) -> None:
        self._slots.setdefault(provision.service.id, _SingletonSlot(provision.service.id)).bind(provision.implementation)
        if not provision.service.local:
            self.services.replace(provision.service, provision.implementation)

    def _connect_spawner(self, provision: _Provision) -> None:
        if provision.spawner is None:
            return
        if provision.service.local:
            provision.spawner.connect(lambda key, impl: self._local_keyed.spawn(provision.service, key, impl))
        else:
            provision.spawner.connect(lambda key, impl: self.services.spawn(provision.service, key, impl))

    async def _terminate(self) -> None:
        self._phase = "disposing"
        for facet_id in reversed(self._order or list(self._runtimes)):
            runtime = self._runtimes.get(facet_id)
            if runtime is not None:
                try:
                    await runtime.lifecycle.dispose()
                except Exception as error:
                    self._on_error(error)
        self._runtimes.clear()
        self._local_keyed.dispose()
        if self._internal is not None:
            await self._internal.dispose(BACKGROUND_CONTEXT)
            self._internal = None
        bindings = {id(binding): binding for binding in self._source_bindings.values()}
        for binding in bindings.values():
            try:
                result = binding.dispose(BACKGROUND_CONTEXT)
                if inspect.isawaitable(result):
                    await result
            except Exception as error:
                self._on_error(error)
        self._source_bindings.clear()
        if self._provider is not None:
            self._provider.dispose()
        self._phase = "dead"

    def _assert_service_target_access(self) -> None:
        if self._phase not in {"activating", "active", "reloading", "disposing"}:
            raise RuntimeError(f"Facet service targets cannot be used during {self._phase}")

    @staticmethod
    def _same_shape(left: _Runtime, right: _Runtime) -> bool:
        return left.requires == right.requires and [(item.service.id, item.mode) for item in left.provisions] == [(item.service.id, item.mode) for item in right.provisions]

    @staticmethod
    def _validate_ids(facets: list[Facet], duplicate_message: str) -> None:
        ids = [facet.id for facet in facets]
        if any(not facet_id for facet_id in ids):
            raise RuntimeError("Facet ID must not be empty")
        if len(ids) != len(set(ids)):
            raise RuntimeError(duplicate_message)


async def create_facet_host(*, facets: list[Facet | dict[str, Any]], on_error: Callable[[Exception], None] | None = None, service_sources: list[Any] | None = None) -> FacetHost:
    host = FacetHost([define_facet(facet) for facet in facets], on_error, service_sources)
    await host.activate()
    return host
