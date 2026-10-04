"""Minimal CBOR encoder/decoder for protocol frames."""

from __future__ import annotations

from typing import Any


def encode_cbor(value: Any) -> bytes:
    return _encode(value)


def decode_cbor(data: bytes) -> Any:
    value, offset = _decode(data, 0)
    if offset != len(data):
        raise ValueError("Trailing CBOR bytes")
    return value


def _encode(value: Any) -> bytes:
    if value is None:
        return b"\xf6"
    if value is False:
        return b"\xf4"
    if value is True:
        return b"\xf5"
    if isinstance(value, int):
        if value >= 0:
            return _encode_uint(0, value)
        return _encode_uint(1, -1 - value)
    if isinstance(value, bytes):
        return _encode_uint(2, len(value)) + value
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        return _encode_uint(3, len(encoded)) + encoded
    if isinstance(value, list):
        out = _encode_uint(4, len(value))
        for item in value:
            out += _encode(item)
        return out
    if isinstance(value, dict):
        out = _encode_uint(5, len(value))
        for key, item in value.items():
            out += _encode(key)
            out += _encode(item)
        return out
    if isinstance(value, float):
        import struct

        return b"\xfb" + struct.pack(">d", value)
    raise TypeError(f"Unsupported CBOR type: {type(value)!r}")


def _encode_uint(major: int, value: int) -> bytes:
    if value < 24:
        return bytes([(major << 5) | value])
    if value < 256:
        return bytes([(major << 5) | 24, value])
    if value < 65536:
        return bytes([(major << 5) | 25]) + value.to_bytes(2, "big")
    if value < 2**32:
        return bytes([(major << 5) | 26]) + value.to_bytes(4, "big")
    return bytes([(major << 5) | 27]) + value.to_bytes(8, "big")


def _decode(data: bytes, offset: int) -> tuple[Any, int]:
    if offset >= len(data):
        raise ValueError("Unexpected end of CBOR data")
    initial = data[offset]
    offset += 1
    major = initial >> 5
    additional = initial & 0x1F
    argument, offset = _read_argument(data, offset, additional)
    if major == 0:
        return argument, offset
    if major == 1:
        return -1 - argument, offset
    if major == 2:
        end = offset + argument
        return data[offset:end], end
    if major == 3:
        end = offset + argument
        return data[offset:end].decode("utf-8"), end
    if major == 4:
        items = []
        for _ in range(argument):
            item, offset = _decode(data, offset)
            items.append(item)
        return items, offset
    if major == 5:
        mapping: dict[Any, Any] = {}
        for _ in range(argument):
            key, offset = _decode(data, offset)
            value, offset = _decode(data, offset)
            mapping[key] = value
        return mapping, offset
    if major == 7:
        if additional == 20:
            return False, offset
        if additional == 21:
            return True, offset
        if additional == 22:
            return None, offset
        if additional == 27:
            import struct

            return struct.unpack(">d", data[offset : offset + 8])[0], offset + 8
    raise ValueError(f"Unsupported CBOR major type {major}")


def _read_argument(data: bytes, offset: int, additional: int) -> tuple[int, int]:
    if additional < 24:
        return additional, offset
    if additional == 24:
        return data[offset], offset + 1
    if additional == 25:
        return int.from_bytes(data[offset : offset + 2], "big"), offset + 2
    if additional == 26:
        return int.from_bytes(data[offset : offset + 4], "big"), offset + 4
    if additional == 27:
        return int.from_bytes(data[offset : offset + 8], "big"), offset + 8
    raise ValueError(f"Unsupported CBOR additional info {additional}")
