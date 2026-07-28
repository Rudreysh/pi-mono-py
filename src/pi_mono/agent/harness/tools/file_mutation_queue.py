"""Serialize file mutations targeting the same environment and canonical path."""

from __future__ import annotations

import asyncio
import weakref
from collections.abc import Awaitable, Callable
from typing import TypeVar

from pi_mono.agent.harness.types import ExecutionEnv, get_or_throw

T = TypeVar("T")

_MutationQueueState = dict  # {queues: dict[str, asyncio.Lock], registration_lock: asyncio.Lock}

_states: weakref.WeakKeyDictionary[ExecutionEnv, _MutationQueueState] = weakref.WeakKeyDictionary()


def _get_state(env: ExecutionEnv) -> _MutationQueueState:
    state = _states.get(env)
    if state is None:
        state = {"queues": {}, "registration_lock": asyncio.Lock()}
        _states[env] = state
    return state


async def _get_mutation_queue_key(env: ExecutionEnv, path: str) -> str:
    absolute_path = get_or_throw(await env.absolutePath(path))
    canonical = await env.canonicalPath(absolute_path)
    if canonical.ok:
        return canonical.value
    if canonical.error.code in ("not_found", "not_supported"):
        return absolute_path
    raise canonical.error


async def with_file_mutation_queue(
    env: ExecutionEnv,
    path: str,
    fn: Callable[[], Awaitable[T]],
) -> T:
    """Serialize file mutations targeting the same environment and canonical path."""
    state = _get_state(env)
    async with state["registration_lock"]:
        key = await _get_mutation_queue_key(env, path)
        queues: dict[str, asyncio.Lock] = state["queues"]
        lock = queues.get(key)
        if lock is None:
            lock = asyncio.Lock()
            queues[key] = lock

    async with lock:
        try:
            return await fn()
        finally:
            async with state["registration_lock"]:
                if queues.get(key) is lock and not lock.locked():
                    queues.pop(key, None)
