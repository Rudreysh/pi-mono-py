import json
import os
import re
import urllib.parse
from typing import Dict, Optional

UNSUPPORTED_PROXY_PROTOCOL_MESSAGE = (
    "Unsupported proxy protocol. SOCKS and PAC proxy URLs are not supported; "
    "use an HTTP or HTTPS proxy URL."
)

DEFAULT_PROXY_PORTS = {
    "ftp": 21,
    "gopher": 70,
    "http": 80,
    "https": 443,
    "ws": 80,
    "wss": 443,
}


def get_proxy_env(key: str) -> str:
    return os.environ.get(key.lower()) or os.environ.get(key.upper()) or ""


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


def should_proxy_hostname(hostname: str, port: int) -> bool:
    no_proxy = get_proxy_env("no_proxy").lower()
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


def get_proxy_for_url(target_url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(target_url)
    except Exception:
        return ""
    if not parsed.scheme or not parsed.hostname:
        return ""

    protocol = parsed.scheme
    hostname = parsed.hostname
    port = parsed.port or DEFAULT_PROXY_PORTS.get(protocol, 0)

    if not should_proxy_hostname(hostname, port):
        return ""

    proxy = get_proxy_env(f"{protocol}_proxy") or get_proxy_env("all_proxy")
    if proxy and "://" not in proxy:
        proxy = f"{protocol}://{proxy}"
    return proxy


def resolve_http_proxy_url_for_target(target_url: str) -> Optional[urllib.parse.ParseResult]:
    proxy = get_proxy_for_url(target_url)
    if not proxy:
        return None
    try:
        proxy_url = urllib.parse.urlparse(proxy)
    except Exception as e:
        raise ValueError(f"Invalid proxy URL {json.dumps(proxy)}: {str(e)}")

    if proxy_url.scheme not in ("http", "https"):
        raise ValueError(f"{UNSUPPORTED_PROXY_PROTOCOL_MESSAGE} Got {proxy_url.scheme}:")

    return proxy_url


def create_http_proxy_agents_for_target(target_url: str) -> Optional[Dict[str, str]]:
    proxy_url = resolve_http_proxy_url_for_target(target_url)
    if not proxy_url:
        return None
    url_str = proxy_url.geturl()
    return {
        "http": url_str,
        "https": url_str,
    }
