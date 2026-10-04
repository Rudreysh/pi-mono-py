"""Transport-neutral protocol types for remote sessions.

Ported from `packages/protocol`. Frames are length-prefixed CBOR maps.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

PROTOCOL_VERSION = 8

ProtocolErrorCode = str


class ProtocolError(TypedDict):
    code: str
    message: str


class ClientHello(TypedDict, total=False):
    type: Literal["hello"]
    protocolVersion: int
    client: str


class ServerHello(TypedDict, total=False):
    type: Literal["hello"]
    protocolVersion: int
    serverId: str


class RequestFrame(TypedDict, total=False):
    type: Literal["request"]
    id: str
    method: str
    params: Any


class ResponseFrame(TypedDict, total=False):
    type: Literal["response"]
    id: str
    result: Any
    error: ProtocolError


class EventFrame(TypedDict, total=False):
    type: Literal["event"]
    name: str
    payload: Any


ProtocolFrame = ClientHello | ServerHello | RequestFrame | ResponseFrame | EventFrame


def is_server_id(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 36:
        return False
    parts = value.split("-")
    return len(parts) == 5 and all(part for part in parts)
