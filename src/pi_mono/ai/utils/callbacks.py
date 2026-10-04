"""Small callback helpers shared by provider adapters."""

from __future__ import annotations

import inspect
from typing import Any


async def emit_provider_stream_event(options: dict[str, Any] | None, data: Any, model: Any) -> None:
    """Notify the optional raw-stream observer before provider normalization."""

    callback = options.get("onProviderStreamEvent") if options else None
    if callback is None:
        return
    result = callback(data, model)
    if inspect.isawaitable(result):
        await result
