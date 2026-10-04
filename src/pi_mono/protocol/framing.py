"""Length-prefixed CBOR framing."""

from __future__ import annotations

from typing import Any

from pi_mono.protocol.cbor import decode_cbor, encode_cbor


def encode_frame(value: Any) -> bytes:
    payload = encode_cbor(value)
    return len(payload).to_bytes(4, "big") + payload


class FrameDecoder:
    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, chunk: bytes) -> list[Any]:
        self._buffer.extend(chunk)
        frames: list[Any] = []
        while True:
            if len(self._buffer) < 4:
                return frames
            length = int.from_bytes(self._buffer[:4], "big")
            if len(self._buffer) < 4 + length:
                return frames
            payload = bytes(self._buffer[4 : 4 + length])
            del self._buffer[: 4 + length]
            frames.append(decode_cbor(payload))
