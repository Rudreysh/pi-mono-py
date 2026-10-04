"""Validation and construction for Chord remote-service wire values."""

from __future__ import annotations

from typing import Any, Callable

from ..delta import assert_valid_op, assert_valid_wire_op

_SERVICE_CONTROL_ID = "$chord.service"
_CATALOGUE_MEMBER = "catalogue"
_SUBSCRIBE_MEMBER = "subscribe"
_UNSUBSCRIBE_MEMBER = "unsubscribe"


def create_service_catalogue_call() -> dict[str, Any]:
    return {"serviceId": _SERVICE_CONTROL_ID, "member": _CATALOGUE_MEMBER, "args": []}


def create_service_subscribe_call(subscription_id: str, service_id: str, mode: str) -> dict[str, Any]:
    return {
        "serviceId": _SERVICE_CONTROL_ID,
        "member": _SUBSCRIBE_MEMBER,
        "args": [subscription_id, service_id, mode],
    }


def create_service_unsubscribe_call(subscription_id: str) -> dict[str, Any]:
    return {"serviceId": _SERVICE_CONTROL_ID, "member": _UNSUBSCRIBE_MEMBER, "args": [subscription_id]}


def decode_service_control_call(call: dict[str, Any]) -> dict[str, Any] | None:
    if call.get("serviceId") != _SERVICE_CONTROL_ID or "instance" in call:
        return None
    member, args = call.get("member"), call.get("args")
    if member == _CATALOGUE_MEMBER and args == []:
        return {"type": "catalogue"}
    if (
        member == _SUBSCRIBE_MEMBER
        and isinstance(args, list)
        and len(args) == 3
        and _is_id(args[0])
        and _is_id(args[1])
        and _is_mode(args[2])
    ):
        return {"type": "subscribe", "subscriptionId": args[0], "serviceId": args[1], "mode": args[2]}
    if member == _UNSUBSCRIBE_MEMBER and isinstance(args, list) and len(args) == 1 and _is_id(args[0]):
        return {"type": "unsubscribe", "subscriptionId": args[0]}
    return None


def parse_service_call(value: object) -> dict[str, Any]:
    call = _record(value, "service call")
    _assert_keys(call, {"serviceId", "member", "args"}, {"instance"}, "service call")
    if not _is_id(call["serviceId"]) or not _is_id(call["member"]) or not isinstance(call["args"], list):
        raise TypeError("Invalid service call")
    if "instance" in call:
        _assert_address(call["instance"])
    return call


def parse_service_catalogue(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise TypeError("Invalid service catalogue")
    ids: set[str] = set()
    for candidate in value:
        entry = _record(candidate, "service catalogue entry")
        _assert_keys(entry, {"serviceId", "mode"}, set(), "service catalogue entry")
        if not _is_id(entry["serviceId"]) or not _is_mode(entry["mode"]) or entry["serviceId"] in ids:
            raise TypeError("Invalid service catalogue")
        ids.add(entry["serviceId"])
    return value


def parse_service_subscription_snapshot(value: object) -> dict[str, Any]:
    _assert_subscription_snapshot(value, assert_valid_op)
    return value  # type: ignore[return-value]


def parse_wire_service_subscription_snapshot(value: object) -> dict[str, Any]:
    _assert_subscription_snapshot(value, assert_valid_wire_op)
    return value  # type: ignore[return-value]


def parse_service_provider_update(value: object) -> dict[str, Any]:
    _assert_provider_update(value, assert_valid_op)
    return value  # type: ignore[return-value]


def parse_wire_service_provider_update(value: object) -> dict[str, Any]:
    _assert_provider_update(value, assert_valid_wire_op)
    return value  # type: ignore[return-value]


def _assert_subscription_snapshot(value: object, assert_op: Callable[[object], None]) -> None:
    snapshot = _record(value, "service subscription snapshot")
    _assert_keys(snapshot, {"serviceId", "mode", "instances"}, set(), "service subscription snapshot")
    if not _is_id(snapshot["serviceId"]) or not _is_mode(snapshot["mode"]) or not isinstance(snapshot["instances"], list):
        raise TypeError("Invalid service subscription snapshot")
    for instance in snapshot["instances"]:
        _assert_instance(instance, assert_op)


def _assert_provider_update(value: object, assert_op: Callable[[object], None]) -> None:
    update = _record(value, "service provider update")
    kind = update.get("type")
    if kind == "state":
        _assert_keys(update, {"type", "member", "sequence", "ops"}, {"instance"}, "state update")
        if not _is_id(update["member"]) or not _is_integer(update["sequence"], 1) or not isinstance(update["ops"], list):
            raise TypeError("Invalid service state update")
        if "instance" in update:
            _assert_address(update["instance"])
        for operation in update["ops"]:
            assert_op(operation)
    elif kind == "unavailable":
        _assert_keys(update, {"type"}, set(), "unavailable update")
    elif kind == "replaced":
        _assert_keys(update, {"type", "snapshot"}, set(), "replacement update")
        _assert_instance(update["snapshot"], assert_op)
    elif kind == "spawned":
        _assert_keys(update, {"type", "instance"}, set(), "spawn update")
        _assert_instance(update["instance"], assert_op)
    elif kind == "closed":
        _assert_keys(update, {"type", "instance"}, set(), "close update")
        _assert_address(update["instance"])
    else:
        raise TypeError("Invalid service provider update")


def _assert_instance(value: object, assert_op: Callable[[object], None]) -> None:
    instance = _record(value, "service instance snapshot")
    _assert_keys(instance, {"members"}, {"instance"}, "service instance snapshot")
    if "instance" in instance:
        _assert_address(instance["instance"])
    if not isinstance(instance["members"], list):
        raise TypeError("Invalid service instance snapshot")
    for candidate in instance["members"]:
        member = _record(candidate, "service member snapshot")
        if member.get("kind") == "method":
            _assert_keys(member, {"name", "kind"}, set(), "service method snapshot")
            if not _is_id(member["name"]):
                raise TypeError("Invalid service method snapshot")
        elif member.get("kind") == "state":
            _assert_keys(member, {"name", "kind", "sequence", "ops"}, set(), "service state snapshot")
            if not _is_id(member["name"]) or not _is_integer(member["sequence"], 0) or not isinstance(member["ops"], list):
                raise TypeError("Invalid service state snapshot")
            for operation in member["ops"]:
                assert_op(operation)
        else:
            raise TypeError("Invalid service member snapshot")


def _assert_address(value: object) -> None:
    address = _record(value, "service instance address")
    _assert_keys(address, {"key", "generation"}, set(), "service instance address")
    if not _is_id(address["key"]) or not _is_integer(address["generation"], 1):
        raise TypeError("Invalid service instance address")


def _record(value: object, description: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise TypeError(f"Invalid {description}")
    return value


def _assert_keys(value: dict[str, Any], required: set[str], optional: set[str], description: str) -> None:
    if not required.issubset(value) or set(value) - required - optional:
        raise TypeError(f"Invalid {description}")


def _is_id(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _is_mode(value: object) -> bool:
    return value in {"singleton", "keyed"}


def _is_integer(value: object, minimum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum
