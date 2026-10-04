"""Replicated JSON state deltas compatible with Pi's Chord wire format.

The JavaScript runtime uses ``Proxy`` to mark mutations as they happen. Python
does not offer an equivalent hook for ordinary ``dict`` and ``list`` objects,
so :class:`DeltaTracker` compares a snapshot at flush time instead. The public
operations and encoded wire format are the same.
"""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Generic, TypeAlias, TypeVar

JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
Segment: TypeAlias = str | int
Path: TypeAlias = list[Segment]
Operation: TypeAlias = list[Any]
WireOperation: TypeAlias = list[Any]

RESERVED_SEGMENTS = frozenset({"__proto__", "constructor", "prototype"})
_MISSING = object()
T = TypeVar("T", bound=dict[str, Any] | list[Any])


class UnsafePathError(ValueError):
    """A delta path attempts to access a prototype-like or invalid segment."""

    def __init__(self, segment: object) -> None:
        super().__init__(f"unsafe path segment: {segment}")
        self.segment = segment


class PathError(ValueError):
    """A delta path cannot be resolved against the current state."""

    def __init__(self, path: Path | int) -> None:
        super().__init__(f"unresolvable path: {json.dumps(path, separators=(',', ':'))}")
        self.path = path


def is_replace(operation: Operation | WireOperation) -> bool:
    return bool(operation) and operation[0] == "r"


def is_base(operations: list[Operation] | list[WireOperation]) -> bool:
    return bool(operations) and is_replace(operations[0])


def overlap(before: str, after: str, scan: int, probe: int = 64, max_candidates: int = 8) -> int:
    """Return the longest suffix of ``before`` that prefixes ``after``."""

    if not before or not after or scan == 0:
        return 0
    tail = before[-scan:] if len(before) > scan else before
    for head_length in (min(probe, len(after)), 1):
        head = after[:head_length]
        offset = -1
        tried = 0
        while True:
            offset = tail.find(head, offset + 1)
            if offset == -1:
                break
            tried += 1
            if tried > max_candidates:
                break
            length = len(tail) - offset
            if length <= len(after) and tail[offset:] == after[:length]:
                return length
        if head_length == 1:
            break
    return 0


def assert_safe_path(path: Path) -> None:
    for segment in path:
        if isinstance(segment, str):
            if segment in RESERVED_SEGMENTS:
                raise UnsafePathError(segment)
        elif isinstance(segment, bool) or not isinstance(segment, int) or segment < 0:
            raise UnsafePathError(segment)


def _assert_path(value: object, *, non_empty: bool = False) -> Path:
    if not isinstance(value, list):
        raise TypeError("path is not an array")
    if non_empty and not value:
        raise TypeError("path is empty")
    assert_safe_path(value)
    return value


def _is_non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def assert_valid_op(operation: object) -> None:
    """Validate a decoded operation with an inline path."""

    if not isinstance(operation, list) or not operation:
        raise TypeError("op is not a tuple")
    verb = operation[0]
    if verb == "r":
        if len(operation) != 2:
            raise TypeError("r arity")
    elif verb == "s":
        if len(operation) != 3:
            raise TypeError("s arity")
        _assert_path(operation[1], non_empty=True)
    elif verb == "d":
        if len(operation) != 2:
            raise TypeError("d arity")
        _assert_path(operation[1], non_empty=True)
    elif verb == "a":
        if len(operation) != 3 or not isinstance(operation[2], str):
            raise TypeError("a shape")
        _assert_path(operation[1], non_empty=True)
    elif verb == "t":
        if len(operation) != 3 or not _is_non_negative_int(operation[2]):
            raise TypeError("t shape")
        _assert_path(operation[1], non_empty=True)
    elif verb == "p":
        if len(operation) != 5:
            raise TypeError("p arity")
        _assert_path(operation[1])
        if not _is_non_negative_int(operation[2]):
            raise TypeError("p index")
        if not _is_non_negative_int(operation[3]):
            raise TypeError("p remove")
        if not isinstance(operation[4], list):
            raise TypeError("p items")
    else:
        raise TypeError(f"unknown op verb: {verb}")


def assert_valid_wire_op(operation: object) -> None:
    """Validate an encoded operation, including path ids and short forms."""

    if not isinstance(operation, list) or not operation:
        raise TypeError("op is not a tuple")
    verb = operation[0]

    def check_ref(reference: object) -> None:
        if _is_non_negative_int(reference):
            return
        _assert_path(reference)

    if verb == "r":
        if len(operation) != 2:
            raise TypeError("r arity")
    elif verb == "s":
        if len(operation) == 3:
            check_ref(operation[1])
        elif len(operation) != 2:
            raise TypeError("s arity")
    elif verb == "d":
        if len(operation) == 2:
            check_ref(operation[1])
        elif len(operation) != 1:
            raise TypeError("d arity")
    elif verb == "a":
        if len(operation) == 3:
            check_ref(operation[1])
            if not isinstance(operation[2], str):
                raise TypeError("a value")
        elif len(operation) == 2:
            if not isinstance(operation[1], str):
                raise TypeError("a value")
        else:
            raise TypeError("a arity")
    elif verb == "t":
        if len(operation) == 3:
            check_ref(operation[1])
            if not _is_non_negative_int(operation[2]):
                raise TypeError("t count")
        elif len(operation) == 2:
            if not _is_non_negative_int(operation[1]):
                raise TypeError("t count")
        else:
            raise TypeError("t arity")
    elif verb == "p":
        if len(operation) == 5:
            check_ref(operation[1])
            index, remove, items = operation[2:]
        elif len(operation) == 4:
            index, remove, items = operation[1:]
        else:
            raise TypeError("p arity")
        if not _is_non_negative_int(index):
            raise TypeError("p index")
        if not _is_non_negative_int(remove):
            raise TypeError("p remove")
        if not isinstance(items, list):
            raise TypeError("p items")
    elif verb == "#":
        if len(operation) != 3 or not _is_non_negative_int(operation[1]) or not isinstance(operation[2], list):
            raise TypeError("# shape")
        assert_safe_path(operation[2])
    else:
        raise TypeError(f"unknown op verb: {verb}")


def _object_key(segment: Segment) -> str:
    return segment if isinstance(segment, str) else str(segment)


def _resolve_value(root: JsonValue, path: Path) -> JsonValue:
    node: JsonValue = root
    for segment in path:
        if isinstance(node, list):
            if not isinstance(segment, int) or isinstance(segment, bool):
                raise UnsafePathError(segment)
            if segment >= len(node):
                raise PathError(path)
            node = node[segment]
        elif isinstance(node, dict):
            key = _object_key(segment)
            if key not in node:
                raise PathError(path)
            node = node[key]
        else:
            raise PathError(path)
    return node


def _resolve_container(root: JsonValue, path: Path) -> list[JsonValue] | dict[str, JsonValue]:
    value = _resolve_value(root, path)
    if not isinstance(value, (list, dict)):
        raise PathError(path)
    return value


def _apply_ops(target: JsonValue | None, operations: list[Operation]) -> JsonValue:
    root = target
    for operation in operations:
        assert_valid_op(operation)
        verb = operation[0]
        if verb == "r":
            root = operation[1]
            continue
        if root is None:
            raise PathError(operation[1])
        path = operation[1]
        assert_safe_path(path)
        if verb == "p":
            array = root if not path else _resolve_container(root, path)
            if not isinstance(array, list):
                raise PathError(path)
            index, remove, items = operation[2], operation[3], operation[4]
            array[index : index + remove] = items
            continue

        parent = _resolve_container(root, path[:-1])
        key = path[-1]
        if isinstance(parent, list):
            if not isinstance(key, int) or isinstance(key, bool):
                raise UnsafePathError(key)
            if key > len(parent):
                raise UnsafePathError(key)
        else:
            key = _object_key(key)

        if verb == "s":
            if isinstance(parent, list):
                if key == len(parent):
                    parent.append(operation[2])
                else:
                    parent[key] = operation[2]
            else:
                parent[key] = operation[2]
        elif verb == "d":
            if isinstance(parent, list):
                if key >= len(parent):
                    raise PathError(path)
                del parent[key]
            else:
                parent.pop(key, None)
        elif verb == "a":
            try:
                current = parent[key]
            except (IndexError, KeyError) as error:
                raise PathError(path) from error
            if not isinstance(current, str):
                raise PathError(path)
            parent[key] = current + operation[2]
        elif verb == "t":
            try:
                current = parent[key]
            except (IndexError, KeyError) as error:
                raise PathError(path) from error
            if not isinstance(current, str):
                raise PathError(path)
            parent[key] = current[operation[2] :]
    return root


def apply(target: T | None, operations: list[Operation]) -> T:
    """Apply decoded operations, mutating ``target`` except for ``r``."""

    return _apply_ops(target, operations)  # type: ignore[return-value]


def _copy_containers(root: JsonValue, path: Path) -> JsonValue:
    if isinstance(root, list):
        copied: JsonValue = list(root)
    elif isinstance(root, dict):
        copied = dict(root)
    else:
        raise PathError(path)

    source: JsonValue = root
    destination: JsonValue = copied
    for segment in path:
        if isinstance(source, list):
            if not isinstance(segment, int) or isinstance(segment, bool):
                raise UnsafePathError(segment)
            if segment >= len(source):
                raise PathError(path)
            child = source[segment]
        elif isinstance(source, dict):
            key = _object_key(segment)
            if key not in source:
                raise PathError(path)
            child = source[key]
        else:
            raise PathError(path)
        if isinstance(child, list):
            copied_child: JsonValue = list(child)
        elif isinstance(child, dict):
            copied_child = dict(child)
        else:
            raise PathError(path)
        if isinstance(destination, list):
            destination[segment] = copied_child
        else:
            destination[_object_key(segment)] = copied_child
        source = child
        destination = copied_child
    return copied


def apply_immutable(target: T | None, operations: list[Operation]) -> T:
    """Apply decoded operations without changing the previous value."""

    root: JsonValue | None = target
    for operation in operations:
        assert_valid_op(operation)
        if operation[0] == "r":
            root = operation[1]
            continue
        if root is None:
            raise PathError(operation[1])
        copied_path = operation[1] if operation[0] == "p" else operation[1][:-1]
        root = _copy_containers(root, copied_path)
        root = _apply_ops(root, [operation])
    return root  # type: ignore[return-value]


def _json_equal(left: object, right: object) -> bool:
    return left == right


def _emit_set(path: Path, value: JsonValue, operations: list[Operation]) -> None:
    if path:
        operations.append(["s", list(path), deepcopy(value)])
    else:
        operations.append(["r", deepcopy(value)])


def _emit_delete(path: Path, operations: list[Operation]) -> None:
    if not path:
        raise TypeError("the tracked root cannot be deleted")
    operations.append(["d", list(path)])


def _diff_string(before: str, after: str, path: Path, scan: int, operations: list[Operation]) -> None:
    if before == after:
        return
    if not path:
        _emit_set(path, after, operations)
    elif len(after) > len(before) and after[: len(before)] == before:
        operations.append(["a", list(path), after[len(before) :]])
    else:
        shared = overlap(before, after, scan)
        if shared == 0:
            operations.append(["s", list(path), after])
        else:
            operations.append(["t", list(path), len(before) - shared])
            if len(after) > shared:
                operations.append(["a", list(path), after[shared:]])


def _diff_value(before: object, after: object, path: Path, scan: int, operations: list[Operation]) -> None:
    if before is _MISSING:
        if after is not _MISSING:
            _emit_set(path, after, operations)
    elif after is _MISSING:
        _emit_delete(path, operations)
    elif before == after:
        return
    elif isinstance(before, str) and isinstance(after, str):
        _diff_string(before, after, path, scan, operations)
    elif isinstance(before, list) and isinstance(after, list):
        _diff_array(before, after, path, scan, operations)
    elif isinstance(before, dict) and isinstance(after, dict):
        _diff_object(before, after, path, scan, operations)
    else:
        _emit_set(path, after, operations)


def _diff_object(
    before: dict[str, JsonValue], after: dict[str, JsonValue], path: Path, scan: int, operations: list[Operation]
) -> None:
    if any(key in RESERVED_SEGMENTS for key in (*before, *after)):
        _emit_set(path, after, operations)
        return
    for key, value in after.items():
        _diff_value(before.get(key, _MISSING), value, [*path, key], scan, operations)
    for key in before:
        if key not in after:
            _emit_delete([*path, key], operations)


def _diff_array(
    before: list[JsonValue], after: list[JsonValue], path: Path, scan: int, operations: list[Operation]
) -> None:
    if len(before) == len(after):
        for index, value in enumerate(after):
            _diff_value(before[index], value, [*path, index], scan, operations)
        return
    prefix = 0
    while prefix < len(before) and prefix < len(after) and _json_equal(before[prefix], after[prefix]):
        prefix += 1
    suffix = 0
    while (
        suffix < len(before) - prefix
        and suffix < len(after) - prefix
        and _json_equal(before[-1 - suffix], after[-1 - suffix])
    ):
        suffix += 1
    if prefix + suffix == min(len(before), len(after)):
        remove = len(before) - prefix - suffix
        items = after[prefix : len(after) - suffix if suffix else len(after)]
        if prefix == 0 and remove == len(before):
            _emit_set(path, after, operations)
        else:
            operations.append(["p", list(path), prefix, remove, deepcopy(items)])
        return
    shorter = min(len(before), len(after))
    for index in range(shorter):
        _diff_value(before[index], after[index], [*path, index], scan, operations)
    if len(after) > len(before):
        operations.append(["p", list(path), len(before), 0, deepcopy(after[len(before) :])])
    elif not after:
        _emit_set(path, after, operations)
    else:
        operations.append(["p", list(path), len(after), len(before) - len(after), []])


class DeltaTracker(Generic[T]):
    """Flush-time tracker for a mutable JSON ``dict`` or ``list`` root."""

    def __init__(self, root: T, *, max_overlap_scan: int = 65_536) -> None:
        self._state = root
        self._baseline: JsonValue | None = None
        self._force_base = True
        self._max_overlap_scan = max_overlap_scan

    @property
    def state(self) -> T:
        return self._state

    @state.setter
    def state(self, value: T) -> None:
        self._state = value
        self._baseline = None
        self._force_base = True

    @property
    def target(self) -> T:
        return self._state

    @property
    def dirty(self) -> bool:
        return self._force_base or self._baseline != self._state

    def rebase(self) -> None:
        self._force_base = True

    def discard(self) -> None:
        self._baseline = deepcopy(self._state)
        self._force_base = False

    def flush(self) -> list[Operation]:
        if self._force_base:
            value = deepcopy(self._state)
            self._baseline = deepcopy(self._state)
            self._force_base = False
            return [["r", value]]
        if self._baseline is None or self._baseline == self._state:
            return []
        operations: list[Operation] = []
        _diff_value(self._baseline, self._state, [], self._max_overlap_scan, operations)
        self._baseline = deepcopy(self._state)
        return operations


def track(root: T, *, max_overlap_scan: int = 65_536) -> DeltaTracker[T]:
    return DeltaTracker(root, max_overlap_scan=max_overlap_scan)


class Encoder:
    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._ids: dict[str, int] = {}
        self._next_id = 0

    def encode(self, operations: list[Operation]) -> list[WireOperation]:
        previous: str | None = None
        encoded: list[WireOperation] = []
        for operation in operations:
            assert_valid_op(operation)
            verb = operation[0]
            if verb == "r":
                encoded.append(operation)
                self._seen.clear()
                self._ids.clear()
                self._next_id = 0
                previous = None
                continue
            path = operation[1]
            key = json.dumps(path, separators=(",", ":"))
            if key == previous:
                if verb == "s":
                    encoded.append(["s", operation[2]])
                elif verb == "d":
                    encoded.append(["d"])
                elif verb in {"a", "t"}:
                    encoded.append([verb, operation[2]])
                else:
                    encoded.append(["p", operation[2], operation[3], operation[4]])
                continue
            reference: Path | int = path
            if key in self._ids:
                reference = self._ids[key]
            elif key in self._seen:
                reference = self._next_id
                self._ids[key] = reference
                self._next_id += 1
                encoded.append(["#", reference, path])
            else:
                self._seen.add(key)
            if verb == "s":
                encoded.append(["s", reference, operation[2]])
            elif verb == "d":
                encoded.append(["d", reference])
            elif verb in {"a", "t"}:
                encoded.append([verb, reference, operation[2]])
            else:
                encoded.append(["p", reference, operation[2], operation[3], operation[4]])
            previous = key
        return encoded


class Decoder:
    def __init__(self) -> None:
        self._paths: dict[int, Path] = {}

    def decode(self, operations: list[WireOperation]) -> list[Operation]:
        previous: Path | None = None
        decoded: list[Operation] = []
        for operation in operations:
            assert_valid_wire_op(operation)
            verb = operation[0]
            if verb == "#":
                self._paths[operation[1]] = operation[2]
                continue
            if verb == "r":
                decoded.append(operation)
                self._paths.clear()
                previous = None
                continue
            short = (verb == "d" and len(operation) == 1) or (
                verb not in {"d", "p"} and len(operation) == 2
            ) or (verb == "p" and len(operation) == 4)
            if short:
                if previous is None:
                    raise PathError([])
                path = previous
            else:
                reference = operation[1]
                if isinstance(reference, int) and not isinstance(reference, bool):
                    if reference not in self._paths:
                        raise PathError(reference)
                    path = self._paths[reference]
                else:
                    path = reference
                previous = path
            if verb != "p" and not path:
                raise PathError(path)
            if verb == "s":
                decoded.append(["s", path, operation[1] if short else operation[2]])
            elif verb == "d":
                decoded.append(["d", path])
            elif verb in {"a", "t"}:
                decoded.append([verb, path, operation[1] if short else operation[2]])
            else:
                index, remove, items = operation[1:] if short else operation[2:]
                decoded.append(["p", path, index, remove, items])
        return decoded


def encoder() -> Encoder:
    return Encoder()


def decoder() -> Decoder:
    return Decoder()
