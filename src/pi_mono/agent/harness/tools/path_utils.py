"""Path resolution helpers for harness execution tools."""

from __future__ import annotations

import re
import unicodedata

from pi_mono.agent.harness.types import ExecutionEnv, get_or_throw
from pi_mono.utils.abort_signals import AbortSignal

UNICODE_SPACES = re.compile(r"[\u00a0\u2000-\u200a\u202f\u205f\u3000]")
NARROW_NO_BREAK_SPACE = "\u202f"


def _normalize_tool_path(path: str) -> str:
    normalized = UNICODE_SPACES.sub(" ", path)
    return normalized[1:] if normalized.startswith("@") else normalized


async def resolve_tool_path(
    env: ExecutionEnv,
    path: str,
    signal: AbortSignal | None = None,
) -> str:
    return get_or_throw(await env.absolutePath(_normalize_tool_path(path), signal))


async def resolve_read_tool_path(
    env: ExecutionEnv,
    path: str,
    signal: AbortSignal | None = None,
) -> str:
    resolved = await resolve_tool_path(env, path, signal)

    variants = [
        resolved,
        re.sub(r" (AM|PM)\.", lambda m: f"{NARROW_NO_BREAK_SPACE}{m.group(1)}.", resolved, flags=re.IGNORECASE),
        unicodedata.normalize("NFD", resolved),
        resolved.replace("'", "\u2019"),
        unicodedata.normalize("NFD", resolved).replace("'", "\u2019"),
    ]

    seen: set[str] = set()
    for variant in variants:
        if variant in seen:
            continue
        seen.add(variant)
        if get_or_throw(await env.exists(variant, signal)):
            return variant

    return resolved
