"""Stateful Chord delta codecs for one remote-service subscription."""

from __future__ import annotations

from typing import Any

from ..delta import Decoder, Encoder, decoder, encoder


def _key(instance: dict[str, Any] | None, member: str) -> tuple[str | None, int | None, str]:
    return (None if instance is None else instance["key"], None if instance is None else instance["generation"], member)


class _Registry:
    def __init__(self, factory: type[Encoder] | type[Decoder]) -> None:
        self._factory = factory
        self._entries: dict[tuple[str | None, int | None, str], Encoder | Decoder] = {}

    def reset(self) -> None:
        self._entries.clear()

    def add(self, instance: dict[str, Any] | None, member: str) -> Encoder | Decoder:
        key = _key(instance, member)
        if key in self._entries:
            raise ValueError(f"Duplicate service state {member}")
        value = self._factory()
        self._entries[key] = value
        return value

    def get(self, instance: dict[str, Any] | None, member: str) -> Encoder | Decoder:
        try:
            return self._entries[_key(instance, member)]
        except KeyError as error:
            raise ValueError(f"Unknown service state {member}") from error

    def remove_instance(self, instance: dict[str, Any]) -> None:
        for key in [key for key in self._entries if key[:2] == (instance["key"], instance["generation"])]:
            del self._entries[key]


class ServiceStateEncoder:
    def __init__(self) -> None:
        self._codecs = _Registry(Encoder)

    def encode_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        self._codecs.reset()
        return {**snapshot, "instances": [self._encode_instance(item) for item in snapshot["instances"]]}

    def encode_update(self, update: dict[str, Any]) -> dict[str, Any]:
        return self._update(update, "encode")

    def _encode_instance(self, instance: dict[str, Any]) -> dict[str, Any]:
        return {**instance, "members": [
            {**member, "ops": self._codecs.add(instance.get("instance"), member["name"]).encode(member["ops"])} if member["kind"] == "state" else member
            for member in instance["members"]
        ]}

    def _update(self, update: dict[str, Any], method: str) -> dict[str, Any]:
        kind = update["type"]
        if kind == "state": return {**update, "ops": getattr(self._codecs.get(update.get("instance"), update["member"]), method)(update["ops"])}
        if kind == "replaced": self._codecs.reset(); return {**update, "snapshot": self._encode_instance(update["snapshot"])}
        if kind == "spawned": return {**update, "instance": self._encode_instance(update["instance"])}
        if kind == "unavailable": self._codecs.reset()
        if kind == "closed": self._codecs.remove_instance(update["instance"])
        return update


class ServiceStateDecoder(ServiceStateEncoder):
    def __init__(self) -> None:
        self._codecs = _Registry(Decoder)

    def decode_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        self._codecs.reset()
        return {**snapshot, "instances": [self._decode_instance(item) for item in snapshot["instances"]]}

    def decode_update(self, update: dict[str, Any]) -> dict[str, Any]:
        return self._update(update, "decode")

    def _encode_instance(self, instance: dict[str, Any]) -> dict[str, Any]:
        return self._decode_instance(instance)

    def _decode_instance(self, instance: dict[str, Any]) -> dict[str, Any]:
        return {**instance, "members": [
            {**member, "ops": self._codecs.add(instance.get("instance"), member["name"]).decode(member["ops"])} if member["kind"] == "state" else member
            for member in instance["members"]
        ]}


def create_service_state_encoder() -> ServiceStateEncoder: return ServiceStateEncoder()
def create_service_state_decoder() -> ServiceStateDecoder: return ServiceStateDecoder()
