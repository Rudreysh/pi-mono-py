"""Unix-socket remote session server."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Callable, Awaitable

from pi_mono.protocol import PROTOCOL_VERSION
from pi_mono.protocol.framing import FrameDecoder, encode_frame

Handler = Callable[[str, Any], Awaitable[Any] | Any]


class RemoteServer:
    def __init__(self, handler: Handler | None = None) -> None:
        self.server_id = str(uuid.uuid4())
        self._handler = handler or (lambda method, params: {"ok": True, "method": method})
        self._server: asyncio.AbstractServer | None = None

    async def start_unix(self, path: str) -> None:
        self._server = await asyncio.start_unix_server(self._handle, path=path)

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        decoder = FrameDecoder()
        try:
            while True:
                chunk = await reader.read(65536)
                if not chunk:
                    return
                for frame in decoder.feed(chunk):
                    if not isinstance(frame, dict):
                        continue
                    if frame.get("type") == "hello":
                        writer.write(
                            encode_frame(
                                {
                                    "type": "hello",
                                    "protocolVersion": PROTOCOL_VERSION,
                                    "serverId": self.server_id,
                                }
                            )
                        )
                        await writer.drain()
                        continue
                    if frame.get("type") == "request":
                        result = self._handler(str(frame.get("method")), frame.get("params"))
                        if asyncio.iscoroutine(result):
                            result = await result
                        writer.write(
                            encode_frame(
                                {
                                    "type": "response",
                                    "id": frame.get("id"),
                                    "result": result,
                                }
                            )
                        )
                        await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
