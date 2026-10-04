import base64
import json

import inspect

from pi_mono.ai.providers.openai_codex_responses import (
    _build_request_body,
    _build_sse_headers,
    _extract_account_id,
    _parse_sse,
    _resolve_codex_url,
    stream_openai_codex_responses,
    stream_simple_openai_codex_responses,
)


def _token(account_id: str) -> str:
    payload = (
        base64.urlsafe_b64encode(
            json.dumps({"https://api.openai.com/auth": {"chatgpt_account_id": account_id}}).encode()
        )
        .decode()
        .rstrip("=")
    )
    return f"aaa.{payload}.bbb"


def test_resolve_codex_url():
    assert (
        _resolve_codex_url("https://chatgpt.com/backend-api")
        == "https://chatgpt.com/backend-api/codex/responses"
    )
    assert (
        _resolve_codex_url("https://chatgpt.com/backend-api/codex")
        == "https://chatgpt.com/backend-api/codex/responses"
    )
    assert (
        _resolve_codex_url("https://chatgpt.com/backend-api/codex/responses")
        == "https://chatgpt.com/backend-api/codex/responses"
    )


def test_extract_account_id_from_token():
    assert _extract_account_id(_token("acc_test")) == "acc_test"


def test_stream_functions_are_synchronous():
    assert not inspect.iscoroutinefunction(stream_openai_codex_responses)
    assert not inspect.iscoroutinefunction(stream_simple_openai_codex_responses)


def test_build_sse_headers():
    headers = _build_sse_headers(None, None, "acc_test", _token("acc_test"), "session-1")
    assert headers["Authorization"].startswith("Bearer ")
    assert headers["chatgpt-account-id"] == "acc_test"
    assert headers["OpenAI-Beta"] == "responses=experimental"
    assert headers["accept"] == "text/event-stream"
    assert headers["session-id"] == "session-1"


def test_build_request_body_sends_off_effort_when_omitted():
    model = {
        "id": "gpt-5.4",
        "provider": "openai-codex",
        "api": "openai-codex-responses",
        "reasoning": True,
        "thinkingLevelMap": {"off": "none", "low": "low"},
    }
    context = {"systemPrompt": "sys", "messages": [{"role": "user", "content": "hi"}]}
    body = _build_request_body(model, context, {})
    assert body["reasoning"]["effort"] == "none"


def test_parse_sse_does_not_flush_partial_json_mid_stream():
    import asyncio

    class FakeResponse:
        async def aiter_text(self):
            yield 'data: {"type": "response.created", "n": '
            yield "1}\n\n"

    async def run():
        return [event async for event in _parse_sse(FakeResponse(), None)]

    events = asyncio.run(run())
    assert events == [{"type": "response.created", "n": 1}]


def _codex_sse_hello() -> str:
    events = [
        {
            "type": "response.output_item.added",
            "item": {
                "type": "message",
                "id": "msg_1",
                "role": "assistant",
                "status": "in_progress",
                "content": [],
            },
        },
        {"type": "response.content_part.added", "part": {"type": "output_text", "text": ""}},
        {"type": "response.output_text.delta", "delta": "Hello"},
        {
            "type": "response.output_item.done",
            "item": {
                "type": "message",
                "id": "msg_1",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "Hello"}],
            },
        },
        {
            "type": "response.completed",
            "response": {
                "status": "completed",
                "usage": {
                    "input_tokens": 5,
                    "output_tokens": 3,
                    "total_tokens": 8,
                    "input_tokens_details": {"cached_tokens": 0},
                },
            },
        },
    ]
    return "".join(f"data: {json.dumps(event)}\n\n" for event in events)


def test_stream_completes_with_abort_signal_and_none_max_retries(monkeypatch):
    import asyncio

    import httpx

    from pi_mono.ai.providers import openai_codex_responses as codex
    from pi_mono.utils.abort_signals import AbortSignal

    sse = _codex_sse_hello()

    class FakeResponse:
        status_code = 200
        is_success = True
        headers = httpx.Headers({"content-type": "text/event-stream", "date": "Thu"})
        reason_phrase = "OK"

        async def aiter_text(self):
            yield sse

        async def aread(self):
            return sse.encode()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method, url, **kwargs):
            assert method == "POST"
            return FakeResponse()

    monkeypatch.setattr(codex.httpx, "AsyncClient", FakeClient)

    model = {
        "id": "gpt-5.4",
        "provider": "openai-codex",
        "api": "openai-codex-responses",
        "reasoning": True,
        "cost": {"input": 1, "output": 1, "cacheRead": 0, "cacheWrite": 0},
    }
    context = {
        "systemPrompt": "sys",
        "messages": [{"role": "user", "content": "hi"}],
    }

    async def run():
        stream = stream_openai_codex_responses(
            model,
            context,
            {
                "apiKey": _token("acc_test"),
                "signal": AbortSignal(),
                "maxRetries": None,
            },
        )
        return [event async for event in stream]

    events = asyncio.run(run())
    assert events[0]["type"] == "start"
    assert events[-1]["type"] == "done"
    assert events[-1]["message"]["content"][0]["text"] == "Hello"
