"""Remote session client over the pi protocol."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from pi_mono.protocol import PROTOCOL_VERSION
from pi_mono.protocol.framing import FrameDecoder, encode_frame


class RemoteClient:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._reader = reader
        self._writer = writer
        self._decoder = FrameDecoder()
        self._pending: dict[str, asyncio.Future[Any]] = {}
        self._events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._reader_task: asyncio.Task[None] | None = None

    async def hello(self, client: str = "pi-python") -> dict[str, Any]:
        self._writer.write(
            encode_frame({"type": "hello", "protocolVersion": PROTOCOL_VERSION, "client": client})
        )
        await self._writer.drain()
        self._reader_task = asyncio.create_task(self._read_loop())
        frame = await self._events.get()
        return frame

    async def request(self, method: str, params: Any = None) -> Any:
        request_id = str(uuid.uuid4())
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        frame: dict[str, Any] = {"type": "request", "id": request_id, "method": method}
        if params is not None:
            frame["params"] = params
        self._writer.write(encode_frame(frame))
        await self._writer.drain()
        return await future

    async def _read_loop(self) -> None:
        while True:
            chunk = await self._reader.read(65536)
            if not chunk:
                return
            for frame in self._decoder.feed(chunk):
                if not isinstance(frame, dict):
                    continue
                if frame.get("type") == "response":
                    pending = self._pending.pop(str(frame.get("id")), None)
                    if pending is None:
                        continue
                    if frame.get("error"):
                        pending.set_exception(RuntimeError(frame["error"]["message"]))
                    else:
                        pending.set_result(frame.get("result"))
                else:
                    await self._events.put(frame)

    async def close(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            self._reader_task = None
        self._writer.close()
        await self._writer.wait_closed()


async def connect_unix(path: str) -> RemoteClient:
    reader, writer = await asyncio.open_unix_connection(path)
    return RemoteClient(reader, writer)
