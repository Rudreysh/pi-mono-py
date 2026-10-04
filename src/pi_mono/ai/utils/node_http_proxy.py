"""HTTP proxy utilities for Python - resolves proxy from environment variables."""

import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse

# Default proxy ports
DEFAULT_PROXY_PORTS: dict[str, int] = {
    "ftp": 21,
    "gopher": 70,
    "http": 80,
    "https": 443,
    "ws": 80,
    "wss": 443,
}

UNSUPPORTED_PROXY_PROTOCOL_MESSAGE = (
    "Unsupported proxy protocol. SOCKS and PAC proxy URLs are not supported; "
    "use an HTTP or HTTPS proxy URL."
)


def _get_proxy_env(key: str) -> str:
    """Get proxy environment variable (case-insensitive)."""
    return os.environ.get(key.lower()) or os.environ.get(key.upper()) or ""


def _parse_proxy_target_url(target_url: str) -> tuple[str, str, int] | None:
    """Parse target URL and return (protocol, hostname, port)."""
    try:
        parsed = urlparse(target_url)
        if not parsed.scheme or not parsed.netloc:
            return None

        protocol = parsed.scheme
        hostname = parsed.hostname or ""

        if parsed.port:
            port = parsed.port
        else:
            port = DEFAULT_PROXY_PORTS.get(protocol, 0)

        return protocol, hostname, port
    except Exception:
        return None


def _strip_brackets(host: str) -> str:
    if host.startswith("[") and host.endswith("]"):
        return host[1:-1]
    return host


def _parse_no_proxy_entry(entry: str) -> tuple[str, int] | None:
    trimmed = entry.strip().lower()
    if not trimmed:
        return None
    if trimmed.startswith("["):
        closing = trimmed.find("]")
        if closing != -1:
            host = trimmed[1:closing]
            rest = trimmed[closing + 1 :]
            if rest.startswith(":"):
                try:
                    return host, int(rest[1:])
                except ValueError:
                    return host, 0
            return host, 0
    if ":" in trimmed and trimmed.count(":") > 1:
        return trimmed, 0
    colon_index = trimmed.rfind(":")
    if colon_index != -1 and colon_index == trimmed.find(":"):
        host = trimmed[:colon_index]
        try:
            return host, int(trimmed[colon_index + 1 :])
        except ValueError:
            pass
    return trimmed, 0


def _should_proxy_hostname(hostname: str, port: int) -> bool:
    """Check if hostname should be proxied based on no_proxy env var."""
    no_proxy = _get_proxy_env("no_proxy").lower()
    if not no_proxy:
        return True
    if no_proxy == "*":
        return False

    normalized_target_host = _strip_brackets(hostname.lower())
    for entry in re.split(r"[,\s]+", no_proxy):
        parsed = _parse_no_proxy_entry(entry)
        if parsed is None:
            continue
        proxy_hostname, proxy_port = parsed
        if proxy_port and proxy_port != port:
            continue
        domain = _strip_brackets(proxy_hostname)
        if domain.startswith("*."):
            domain = domain[2:]
        elif domain.startswith(".") or domain.startswith("*"):
            domain = domain[1:]
        if not domain:
            continue
        if normalized_target_host == domain or normalized_target_host.endswith(f".{domain}"):
            return False
    return True


def _get_proxy_for_url(target_url: str) -> str:
    """Get proxy URL for a target URL from environment variables."""
    parsed = _parse_proxy_target_url(target_url)
    if not parsed:
        return ""

    protocol, hostname, port = parsed
    if not _should_proxy_hostname(hostname, port):
        return ""

    # Check for protocol-specific proxy or all_proxy
    proxy = _get_proxy_env(f"{protocol}_proxy") or _get_proxy_env("all_proxy")
    if proxy and "://" not in proxy:
        proxy = f"{protocol}://{proxy}"
    return proxy


def resolve_http_proxy_url_for_target(target_url: str) -> str | None:
    """
    Resolve HTTP proxy URL for a target URL.
    Returns proxy URL string or None if no proxy.
    """
    proxy = _get_proxy_for_url(target_url)
    if not proxy:
        return None

    try:
        parsed = urlparse(proxy)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"{UNSUPPORTED_PROXY_PROTOCOL_MESSAGE} Got {parsed.scheme}")
        return proxy
    except Exception as e:
        raise ValueError(f"Invalid proxy URL {proxy!r}: {e}")


@dataclass
class ProxyAgents:
    """HTTP/HTTPS proxy agents configuration."""

    http_proxy: str | None = None
    https_proxy: str | None = None


def create_http_proxy_agents_for_target(target_url: str) -> ProxyAgents | None:
    """
    Create proxy configuration for a target URL.
    Returns ProxyAgents with proxy URLs or None if no proxy.
    """
    proxy_url = resolve_http_proxy_url_for_target(target_url)
    if not proxy_url:
        return None

    return ProxyAgents(http_proxy=proxy_url, https_proxy=proxy_url)


# For requests library compatibility
def get_proxy_dict_for_requests(target_url: str) -> dict[str, str] | None:
    """Get proxy dict compatible with requests library."""
    agents = create_http_proxy_agents_for_target(target_url)
    if not agents:
        return None
    return {
        "http": agents.http_proxy or "",
        "https": agents.https_proxy or "",
    }
