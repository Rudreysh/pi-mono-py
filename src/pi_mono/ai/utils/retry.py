"""Classify whether a failed assistant message looks retryable, and retry loop.

Port of packages/ai/src/utils/retry.ts.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

from pi_mono.ai.types import AssistantMessage

_NON_RETRYABLE_PROVIDER_LIMIT_ERROR_PATTERN = re.compile(
    r"GoUsageLimitError|FreeUsageLimitError|Monthly usage limit reached|available balance|"
    r"insufficient_quota|out of budget|quota exceeded|billing",
    re.IGNORECASE,
)

_RETRYABLE_PROVIDER_ERROR_PATTERN = re.compile(
    r"overloaded|rate.?limit|too many requests|429|500|502|503|504|524|"
    r"service.?unavailable|server.?error|internal.?error|"
    r"provider.?returned.?error|"
    r"network.?error|connection.?error|connection.?refused|connection.?lost|"
    r"other side closed|fetch failed|"
    r"getaddrinfo|ENOTFOUND|EAI_AGAIN|"
    r"upstream.?connect|reset before headers|"
    r"socket hang up|socket connection was closed|timed? out|timeout|terminated|"
    r"websocket.?closed|websocket.?error|"
    r"ended without|stream ended before message_stop|"
    r"stream ended before a terminal response event|"
    r"http2 request did not get a response|"
    r"retry delay|"
    r"you can retry your request|try your request again|please retry your request|"
    r"ResourceExhausted",
    re.IGNORECASE,
)


def is_retryable_assistant_error(message: AssistantMessage) -> bool:
    """Return True when the assistant error looks like a transient provider/transport failure.

    Does not implement retry policy. Callers should handle context overflow separately,
    then apply their own retry budget and backoff.
    """
    if message.get("stopReason") != "error" or not message.get("errorMessage"):
        return False
    error_message = str(message.get("errorMessage", ""))
    if _NON_RETRYABLE_PROVIDER_LIMIT_ERROR_PATTERN.search(error_message):
        return False
    return bool(_RETRYABLE_PROVIDER_ERROR_PATTERN.search(error_message))


@dataclass
class RetryPolicy:
    enabled: bool = False
    max_retries: int = 0
    base_delay_ms: int = 1000


@dataclass
class RetryCallbacks:
    on_retry_scheduled: Callable[[int, int, int, str], Any] | None = None
    on_retry_attempt_start: Callable[[], Any] | None = None
    on_retry_finished: Callable[[bool, int, str | None], Any] | None = None


async def retry_assistant_call(
    produce: Callable[[], Awaitable[AssistantMessage]],
    policy: RetryPolicy | None = None,
    signal: Any = None,
    callbacks: RetryCallbacks | None = None,
) -> AssistantMessage:
    """Run a single assistant-producing call with bounded retry on transient errors.

    Matches the TS retryAssistantCall semantics: successful/aborted responses
    return immediately; non-retryable errors fail fast; retryable errors retry
    up to max_retries with exponential backoff.
    """
    max_attempts = policy.max_retries if policy and policy.enabled else 0
    cb = callbacks or RetryCallbacks()

    attempt = 0
    last_retry: dict[str, Any] | None = None

    while True:
        response = await produce()

        if response.get("stopReason") == "aborted":
            if last_retry and cb.on_retry_finished:
                await _maybe_await(cb.on_retry_finished(False, last_retry["attempt"], None))
            return response

        if response.get("stopReason") != "error":
            if last_retry and cb.on_retry_finished:
                await _maybe_await(cb.on_retry_finished(True, last_retry["attempt"], None))
            return response

        if attempt >= max_attempts or not is_retryable_assistant_error(response):
            if last_retry and cb.on_retry_finished:
                await _maybe_await(
                    cb.on_retry_finished(False, last_retry["attempt"], response.get("errorMessage"))
                )
            return response

        attempt += 1
        error_message = response.get("errorMessage") or "Unknown error"
        last_retry = {"attempt": attempt, "errorMessage": error_message}
        delay_ms = (policy.base_delay_ms if policy else 1000) * (2 ** (attempt - 1))

        if cb.on_retry_scheduled:
            await _maybe_await(cb.on_retry_scheduled(attempt, max_attempts, delay_ms, error_message))

        aborted = getattr(signal, "aborted", False) if signal else False
        if aborted:
            if cb.on_retry_finished:
                await _maybe_await(cb.on_retry_finished(False, attempt, error_message))
            return {**response, "stopReason": "aborted", "errorMessage": ""}

        await asyncio.sleep(delay_ms / 1000)

        aborted = getattr(signal, "aborted", False) if signal else False
        if aborted:
            if cb.on_retry_finished:
                await _maybe_await(cb.on_retry_finished(False, attempt, error_message))
            return {**response, "stopReason": "aborted", "errorMessage": ""}

        if cb.on_retry_attempt_start:
            await _maybe_await(cb.on_retry_attempt_start())


async def _maybe_await(result: Any) -> None:
    if asyncio.iscoroutine(result) or asyncio.isfuture(result):
        await result
