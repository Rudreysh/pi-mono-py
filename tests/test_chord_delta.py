from __future__ import annotations

import pytest
import anyio
from types import SimpleNamespace

from pi_mono.chord import BACKGROUND_CONTEXT, ReplicatedState, ReplicatedStateReplica, create_facet_host, define_facet
from pi_mono.chord.context import BACKGROUND_CONTEXT, create_context_key, with_context_value
from pi_mono.chord.facets import combine_facet_loaders, create_static_facet_loader
from pi_mono.chord.delta import (
    PathError,
    UnsafePathError,
    apply,
    apply_immutable,
    assert_valid_op,
    assert_valid_wire_op,
    decoder,
    encoder,
    is_base,
    overlap,
    track,
)
from pi_mono.chord.json import is_json_value
from pi_mono.chord.services.wire import (
    create_service_subscribe_call,
    decode_service_control_call,
    parse_service_call,
    parse_wire_service_subscription_snapshot,
)
from pi_mono.chord.services.state_codec import create_service_state_decoder, create_service_state_encoder
from pi_mono.chord.services.provider import RemoteServiceProvider, define_service
from pi_mono.chord.services.consumer import create_remote_service_binding


def test_tracker_emits_compact_string_and_array_operations() -> None:
    state = {"text": "abcdefgh", "items": [1, 2]}
    tracker = track(state)
    assert tracker.flush() == [["r", {"text": "abcdefgh", "items": [1, 2]}]]

    state["text"] = "defghxyz"
    state["items"].append(3)

    operations = tracker.flush()
    assert operations == [
        ["t", ["text"], 3],
        ["a", ["text"], "xyz"],
        ["p", ["items"], 2, 0, [3]],
    ]
    assert apply({"text": "abcdefgh", "items": [1, 2]}, operations) == state


def test_tracker_handles_nested_objects_deletes_and_rebase() -> None:
    state = {"message": {"content": "hello", "enabled": True}}
    tracker = track(state)
    tracker.flush()

    state["message"]["content"] = "hello world"
    del state["message"]["enabled"]
    assert tracker.flush() == [
        ["a", ["message", "content"], " world"],
        ["d", ["message", "enabled"]],
    ]

    tracker.rebase()
    base = tracker.flush()
    assert is_base(base)
    assert base == [["r", state]]


def test_apply_immutable_copies_only_changed_containers() -> None:
    original = {"left": {"value": 1}, "right": {"value": 2}}
    updated = apply_immutable(original, [["s", ["left", "value"], 3]])

    assert updated == {"left": {"value": 3}, "right": {"value": 2}}
    assert original == {"left": {"value": 1}, "right": {"value": 2}}
    assert updated["right"] is original["right"]


def test_encoder_decoder_round_trip_with_short_paths_and_interning() -> None:
    operations = [
        ["r", {"text": ""}],
        ["a", ["text"], "one"],
        ["a", ["text"], "two"],
        ["s", ["other"], 1],
        ["a", ["text"], "three"],
    ]
    wire = encoder().encode(operations)
    assert wire == [
        ["r", {"text": ""}],
        ["a", ["text"], "one"],
        ["a", "two"],
        ["s", ["other"], 1],
        ["#", 0, ["text"]],
        ["a", 0, "three"],
    ]
    assert decoder().decode(wire) == operations


def test_validators_and_applier_reject_unsafe_or_unresolvable_paths() -> None:
    with pytest.raises(UnsafePathError):
        assert_valid_op(["s", ["__proto__"], True])
    with pytest.raises(TypeError, match="path is not an array"):
        assert_valid_wire_op(["s", "text", "value"])
    with pytest.raises(PathError):
        apply({"value": 1}, [["a", ["missing"], "x"]])
    with pytest.raises(PathError):
        decoder().decode([["d"]])


def test_overlap_honors_scan_limit() -> None:
    assert overlap("abcdefgh", "defghxyz", 65_536) == 5
    assert overlap("abcdef", "defghi", 0) == 0


def test_json_validation_rejects_nonfinite_and_cyclic_values() -> None:
    cyclic: list[object] = []
    cyclic.append(cyclic)
    assert is_json_value({"ok": [None, True, 1, "text"]})
    assert not is_json_value(float("inf"))
    assert not is_json_value(cyclic)
    assert not is_json_value({1: "non-string key"})


def test_service_wire_control_calls_and_snapshot_validation() -> None:
    call = create_service_subscribe_call("sub-1", "chat", "singleton")
    assert decode_service_control_call(call) == {
        "type": "subscribe",
        "subscriptionId": "sub-1",
        "serviceId": "chat",
        "mode": "singleton",
    }
    assert parse_service_call({"serviceId": "chat", "member": "send", "args": ["hello"]})["member"] == "send"
    snapshot = {
        "serviceId": "chat",
        "mode": "singleton",
        "instances": [{"members": [{"name": "messages", "kind": "state", "sequence": 0, "ops": [["r", []]]}]}],
    }
    assert parse_wire_service_subscription_snapshot(snapshot) == snapshot
    with pytest.raises(TypeError, match="Invalid service call"):
        parse_service_call({"serviceId": "chat", "member": "send", "args": [], "extra": True})


def test_service_state_codec_preserves_delta_dictionary_across_updates() -> None:
    snapshot = {"serviceId": "chat", "mode": "singleton", "instances": [{"members": [{"name": "state", "kind": "state", "sequence": 0, "ops": [["r", {"text": ""}]]}]}]}
    encoder, decoder = create_service_state_encoder(), create_service_state_decoder()
    assert decoder.decode_snapshot(encoder.encode_snapshot(snapshot)) == snapshot
    update = {"type": "state", "member": "state", "sequence": 1, "ops": [["a", ["text"], "one"], ["a", ["text"], "two"]]}
    assert decoder.decode_update(encoder.encode_update(update)) == update


def test_replicated_state_publishes_immutable_revisions_and_replicas_detect_gaps() -> None:
    state = ReplicatedState({"value": 0})
    deliveries = []
    state.subscribe(lambda value, _context, delivery: deliveries.append((value, delivery["kind"])))
    state.state["value"] = 1
    state.publish("local")
    assert deliveries == [({"value": 0}, "hydrate"), ({"value": 1}, "update")]

    replica = ReplicatedStateReplica()
    replica.hydrate(1, [["r", {"value": 1}]])
    replica.update(2, [["s", ["value"], 2]])
    assert replica.value == {"value": 2}
    with pytest.raises(ValueError, match="sequence has a gap"):
        replica.update(4, [["s", ["value"], 4]])
    assert replica.value is None


@pytest.mark.anyio
async def test_singleton_service_provider_snapshots_methods_and_state_updates() -> None:
    service = define_service("test.counter")
    state = ReplicatedState({"count": 0})
    class Counter:
        def __init__(self) -> None: self.state = state
        async def increment(self, _context) -> int:
            self.state.state["count"] += 1; self.state.publish(); return self.state.value["count"]
    provider = RemoteServiceProvider([service])
    provider.provide(service, Counter())
    updates = []
    subscription = provider.subscribe(service.id, "singleton", lambda update, _context: updates.append(update))
    subscription["activate"]()
    assert subscription["snapshot"]["instances"][0]["members"][0]["ops"] == [["r", {"count": 0}]]
    assert await provider.invoke({"serviceId": service.id, "member": "increment", "args": []}) == 1
    assert updates[0]["ops"] == [["s", ["count"], 1]]


@pytest.mark.anyio
async def test_remote_service_binding_hydrates_and_updates_state_facade() -> None:
    service, state = define_service("test.binding"), ReplicatedState({"value": 0})
    class Implementation:
        def __init__(self) -> None: self.state = state
        async def set_value(self, value, _context) -> None: self.state.state["value"] = value; self.state.publish()
    provider = RemoteServiceProvider([service]); provider.provide(service, Implementation())
    binding = create_remote_service_binding(services=[service], transport=provider)
    facade = binding.use(service); await binding.ready()
    assert facade.state.value == {"value": 0}
    await facade.set_value(2, BACKGROUND_CONTEXT)
    assert facade.state.value == {"value": 2}


@pytest.mark.anyio
async def test_combined_facet_loader_disposes_in_reverse_order() -> None:
    trace = []
    class Loader:
        def __init__(self, name): self.name = name
        async def load(self):
            async def dispose(): trace.append(f"dispose {self.name}")
            trace.append(f"load {self.name}"); return SimpleNamespace(facets=[self.name], dispose=dispose)
    loaded = await combine_facet_loaders([Loader("first"), Loader("second")]).load()
    assert loaded.facets == ["first", "second"]
    await loaded.dispose(); await loaded.dispose()
    assert trace == ["load first", "load second", "dispose second", "dispose first"]


def test_context_values_are_immutable_and_scoped() -> None:
    key = create_context_key("request")
    derived = with_context_value(key, "value", BACKGROUND_CONTEXT)
    assert BACKGROUND_CONTEXT.value(key) is None
    assert derived.value(key) == "value"


def test_keyed_service_spawn_and_close_emit_lifecycle_updates() -> None:
    service = define_service("test.keyed")
    provider = RemoteServiceProvider([{"service": service, "mode": "keyed"}])
    class Singleton: pass
    updates = []
    subscription = provider.subscribe(service.id, "keyed", lambda update, _context: updates.append(update))
    subscription["activate"]()
    close = provider.spawn(service, "one", Singleton())
    close()
    assert [update["type"] for update in updates] == ["spawned", "closed"]
    assert updates[0]["instance"]["instance"] == {"key": "one", "generation": 1}


@pytest.mark.anyio
async def test_keyed_binding_hydrates_observations_and_fences_reused_keys() -> None:
    service = define_service("test.dialogs")
    provider = RemoteServiceProvider([{"service": service, "mode": "keyed"}])
    binding = create_remote_service_binding(services=[service], transport=provider)
    seen = []

    def observe(dialog, context) -> None:
        seen.append((dialog, context, dialog.state.value["value"]))

    stop = binding.observe(service, observe)
    state = ReplicatedState({"value": "first"})

    class Dialog:
        def __init__(self) -> None: self.state = state
        async def read(self, _context) -> str: return self.state.value["value"]

    close = provider.spawn(service, "current", Dialog())
    await anyio.sleep(0)
    assert seen[0][2] == "first"
    state.state["value"] = "updated"
    state.publish(BACKGROUND_CONTEXT)
    assert seen[0][0].state.value == {"value": "updated"}
    retained = seen[0][0].read
    close()
    assert seen[0][1].abort_signal.aborted
    with pytest.raises(Exception, match="binding is closed"):
        await retained(BACKGROUND_CONTEXT)

    next_state = ReplicatedState({"value": "second"})
    class NextDialog:
        def __init__(self) -> None: self.state = next_state
        async def read(self, _context) -> str: return self.state.value["value"]

    provider.spawn(service, "current", NextDialog())
    await anyio.sleep(0)
    assert [entry[2] for entry in seen] == ["first", "second"]
    stop()
    await binding.dispose()


@pytest.mark.anyio
async def test_facet_host_orders_dependencies_and_reloads_keyed_services() -> None:
    source = define_service("test.host.source")
    projection = define_service("test.host.projection")
    dialogs = define_service("test.host.dialogs")
    trace = []
    observed = []

    consumer = define_facet({
        "id": "consumer",
        "setup": lambda env: (
            env.observe(dialogs, lambda service, context: observed.append((service, context))),
            env.on_activate(lambda: trace.append("activate consumer")),
        ),
    })

    def source_facet(value: str):
        def setup(env) -> None:
            source_handle = env.use(source)
            env.provide(source, SimpleNamespace(read=lambda _context: value))
            env.provide(projection, SimpleNamespace(read=lambda context: source_handle.read(context)))
            items = env.provide_many(dialogs)
            env.on_activate(lambda: (trace.append(f"activate {value}"), items.spawn("current", SimpleNamespace(read=lambda _context: value))))
        return define_facet({"id": "provider", "setup": setup})

    host = await create_facet_host(facets=[consumer, source_facet("one")])
    await anyio.sleep(0)
    assert trace == ["activate one", "activate consumer"]
    assert host.services.use(projection).read(BACKGROUND_CONTEXT) == "one"
    assert await observed[0][0].read(observed[0][1]) == "one"

    first_service, first_context = observed[0]
    await host.reload([source_facet("two")])
    await anyio.sleep(0)
    assert first_context.abort_signal.aborted
    with pytest.raises(Exception, match="observation is closed"):
        await first_service.read(first_context)
    assert await observed[1][0].read(observed[1][1]) == "two"
    await host.dispose()


@pytest.mark.anyio
async def test_facet_host_binds_an_external_service_source() -> None:
    external = define_service("test.external.source")
    projection = define_service("test.external.projection")
    provider = RemoteServiceProvider([external])
    provider.provide(external, SimpleNamespace(read=lambda _context: "external"))

    class SourceBinding:
        def __init__(self, services) -> None:
            self.binding = create_remote_service_binding(services=services, transport=provider, bound=False)

        def use(self, service): return self.binding.use(service)
        def observe(self, service, handler): return self.binding.observe(service, handler)
        async def ready(self, context) -> None:
            await self.binding.rebind(True, context)
            await self.binding.ready(context)
        async def dispose(self, context) -> None: await self.binding.dispose(context)

    class Source:
        accepts_unavailable_services = False
        async def catalogue(self, _context): return [{"serviceId": external.id, "mode": "singleton"}]
        def open(self, options): return SourceBinding(options["services"])

    def setup(env) -> None:
        source = env.use(external)
        env.provide(projection, SimpleNamespace(read=lambda context: source.read(context)))

    host = await create_facet_host(
        facets=[define_facet({"id": "projection", "setup": setup})],
        service_sources=[Source()],
    )
    assert await host.services.use(projection).read(BACKGROUND_CONTEXT) == "external"
    await host.dispose()
    provider.dispose()
