"""HTTP client helpers for per-request fetch injection.

Providers that use httpx can call ``resolve_httpx_client`` to honour the
optional ``fetch`` field on StreamOptions / SimpleStreamOptions.  When the
caller supplies a custom fetch callable that is already an
``httpx.AsyncClient``, it is returned directly.  Otherwise the provider's
default client is used.
"""

from __future__ import annotations

from typing import Any


def resolve_httpx_client(
    options: dict[str, Any] | None,
    default_client: Any | None = None,
) -> Any | None:
    """Return the httpx client to use for a request.

    If *options* contains a ``fetch`` key whose value is an
    ``httpx.AsyncClient`` instance, return it.  Otherwise fall back to
    *default_client*.
    """
    if options is None:
        return default_client

    fetch = options.get("fetch")
    if fetch is None:
        return default_client

    try:
        import httpx

        if isinstance(fetch, httpx.AsyncClient):
            return fetch
    except ImportError:
        pass

    return default_client
