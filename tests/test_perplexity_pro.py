"""Perplexity Pro subscription (session cookie) wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from pi_mono.ai.models import get_model, get_models, get_providers
from pi_mono.ai.perplexity_pro_models import PERPLEXITY_PRO_MODEL_PREFS
from pi_mono.ai.providers.perplexity_web import (
    _StreamState,
    _build_payload,
    _consume_sse_buffer,
    _extract_stream_items,
    _messages_to_query,
    _parse_sse_message,
    stream_perplexity_web,
)
from pi_mono.ai.utils.oauth import get_oauth_provider
from pi_mono.ai.utils.oauth.perplexity_pro import (
    SESSION_TTL_MS,
    _normalize_session_token,
    login_perplexity_pro,
    normalize_session_token,
    validate_perplexity_session_token,
)
from pi_mono.coding_agent.core.model_resolver import default_model_per_provider
from pi_mono.coding_agent.modes.interactive.interactive_mode import is_api_key_login_provider
from pi_mono.ai.env_api_keys import get_api_key_env_vars


def test_perplexity_pro_models_registered() -> None:
    assert "perplexity-pro" in get_providers()
    models = get_models("perplexity-pro")
    ids = {model["id"] for model in models}
    assert ids == set(PERPLEXITY_PRO_MODEL_PREFS)
    sonnet = get_model("perplexity-pro", "sonnet")
    assert sonnet is not None
    assert sonnet["api"] == "perplexity-web"
    assert sonnet["provider"] == "perplexity-pro"
    assert sonnet["reasoning"] is False


def test_perplexity_pro_oauth_and_defaults() -> None:
    provider = get_oauth_provider("perplexity-pro")
    assert provider is not None
    assert provider.name == "Perplexity Pro"
    assert default_model_per_provider["perplexity-pro"] == "sonnet"
    # OAuth-only: not an API-key login provider (same rule as github-copilot).
    assert is_api_key_login_provider("perplexity-pro", {"perplexity-pro"}) is False
    assert is_api_key_login_provider("perplexity", set()) is True
    assert get_api_key_env_vars("perplexity-pro") == ["PERPLEXITY_SESSION_TOKEN"]
    assert SESSION_TTL_MS == 12 * 60 * 60 * 1000


def test_normalize_session_token() -> None:
    raw = "__Secure-next-auth.session-token=abc123; Path=/; Secure"
    assert _normalize_session_token(raw) == "abc123"
    assert normalize_session_token("  xyz  ") == "xyz"
    assert normalize_session_token('__Secure-next-auth.session-token="quoted"') == "quoted"


def test_build_payload_mode_mapping() -> None:
    auto_payload = _build_payload("q", "auto", "pplx_pro")
    assert auto_payload["params"]["mode"] == "concise"
    assert auto_payload["params"]["model_preference"] == "pplx_pro"

    pro_payload = _build_payload("q", "pro", "claude46sonnet")
    assert pro_payload["params"]["mode"] == "copilot"
    assert pro_payload["params"]["model_preference"] == "claude46sonnet"


@pytest.mark.anyio
async def test_validate_session_token_ok() -> None:
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json = lambda: {"user": {"email": "pro@example.com"}}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        get = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient", return_value=_Client()):
        data = await validate_perplexity_session_token("tok")
        assert data["user"]["email"] == "pro@example.com"


@pytest.mark.anyio
async def test_validate_session_token_rejects_empty_user() -> None:
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json = lambda: {"user": {}}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        get = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient", return_value=_Client()):
        with pytest.raises(RuntimeError, match="no user"):
            await validate_perplexity_session_token("tok")


@pytest.mark.anyio
async def test_login_perplexity_pro_prompt() -> None:
    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        get = AsyncMock(
            return_value=type(
                "R",
                (),
                {
                    "status_code": 200,
                    "json": lambda self: {"user": {"email": "a@b.c"}},
                    "text": "",
                },
            )()
        )

    async def on_prompt(prompt):
        assert "session-token" in prompt["message"]
        return "__Secure-next-auth.session-token=session-abc"

    with patch("httpx.AsyncClient", return_value=_Client()):
        creds = await login_perplexity_pro({"onPrompt": on_prompt, "onProgress": lambda _m: None})
    assert creds["access"] == "session-abc"
    assert creds["expires"] > 0


def test_parse_sse_and_query_helpers() -> None:
    raw = (
        'event: message\r\ndata: {"blocks":[{"intended_usage":"markdown_answer",'
        '"markdown_block":{"progress":"PROCESSING","chunks":["hi"]}}]}\r\n'
    )
    parsed = _parse_sse_message(raw)
    assert parsed is not None
    assert "blocks" in parsed

    # Always only the latest user-typed prompt — no system, history, or answers.
    query = _messages_to_query(
        {
            "systemPrompt": (
                "Instructions:\nYou are an expert coding assistant operating inside pi..."
            ),
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "write me about latest studies about adhd how is it diagonosed",
                        }
                    ],
                },
            ],
        }
    )
    assert query == "write me about latest studies about adhd how is it diagonosed"
    assert "coding assistant" not in query
    assert "Instructions:" not in query

    # Follow-up in same pi session still sends ONLY the new prompt.
    followup = _messages_to_query(
        {
            "systemPrompt": "You are pi.",
            "messages": [
                {"role": "user", "content": "What is ADHD?"},
                {"role": "assistant", "content": [{"type": "text", "text": "ADHD is…"}]},
                {"role": "user", "content": "How is it diagnosed?"},
            ],
        }
    )
    assert followup == "How is it diagnosed?"
    assert "What is ADHD?" not in followup
    assert "ADHD is…" not in followup
    assert "You are pi." not in followup


def test_extract_web_result_block_citations() -> None:
    from pi_mono.ai.providers.perplexity_web import _format_sources_footer

    state = _StreamState()
    chunk = {
        "blocks": [
            {
                "intended_usage": "web_results",
                "web_result_block": {
                    "web_results": [
                        {
                            "name": "ADHD diagnosis review",
                            "url": "https://example.com/adhd-1",
                            "snippet": "DSM-5 criteria…",
                        },
                        {
                            "title": "VR assessment study",
                            "url": "https://example.com/adhd-2",
                        },
                    ]
                },
            },
            {
                "intended_usage": "markdown_answer",
                "markdown_block": {
                    "progress": "DONE",
                    "chunks": ["ADHD is diagnosed clinically.[1][2]"],
                },
            },
        ]
    }
    items = _extract_stream_items(chunk, state)
    assert any(item.get("delta") for item in items)
    assert len(state.web_results) == 2
    footer = _format_sources_footer(state.web_results)
    assert "[1] ADHD diagnosis review" in footer
    assert "https://example.com/adhd-1" in footer
    assert "https://example.com/adhd-2" in footer


def test_extract_processing_and_done_only() -> None:
    state = _StreamState()
    processing = {
        "blocks": [
            {
                "intended_usage": "markdown_answer",
                "markdown_block": {"progress": "PROCESSING", "chunks": ["Hel"]},
            }
        ]
    }
    items = _extract_stream_items(processing, state)
    assert items[0]["delta"] == "Hel"
    assert state.full_answer == "Hel"

    more = {
        "blocks": [
            {
                "intended_usage": "markdown_answer",
                "markdown_block": {"progress": "PROCESSING", "chunks": ["lo"]},
            }
        ]
    }
    items = _extract_stream_items(more, state)
    assert items[0]["delta"] == "lo"
    assert state.full_answer == "Hello"

    # DONE with same text should not re-emit.
    done_same = {
        "blocks": [
            {
                "intended_usage": "markdown_answer",
                "markdown_block": {"progress": "DONE", "chunks": ["Hello"]},
            }
        ]
    }
    assert _extract_stream_items(done_same, state) == []

    # DONE-only stream (no prior PROCESSING).
    state2 = _StreamState()
    done_only = {
        "blocks": [
            {
                "intended_usage": "markdown_answer",
                "markdown_block": {"progress": "DONE", "chunks": ["Full answer"]},
            }
        ]
    }
    items = _extract_stream_items(done_only, state2)
    assert len(items) == 1
    assert items[0]["delta"] == "Full answer"
    assert state2.full_answer == "Full answer"


def test_consume_sse_buffer_and_flush() -> None:
    state = _StreamState()
    event = (
        'event: message\n'
        'data: {"blocks":[{"intended_usage":"markdown_answer",'
        '"markdown_block":{"progress":"DONE","chunks":["ok"]}}]}\n\n'
        "event: end_of_stream\n\n"
    )
    remainder, items, ended = _consume_sse_buffer(event, state)
    assert ended is True
    assert items[0]["delta"] == "ok"
    assert remainder == ""


@pytest.mark.anyio
async def test_stream_done_only_answer() -> None:
    model = get_model("perplexity-pro", "sonnet")
    assert model is not None

    async def fake_chunks(*_args, **_kwargs):
        yield {
            "delta": "",
            "answer": "Only final",
            "web_results": [],
            "done": True,
        }

    with patch(
        "pi_mono.ai.providers.perplexity_web._iter_perplexity_chunks",
        fake_chunks,
    ):
        stream = stream_perplexity_web(
            model,
            {"messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]},
            {"apiKey": "__Secure-next-auth.session-token=tok; Path=/"},
        )
        events = [event async for event in stream]
    done = next(e for e in events if e["type"] == "done")
    text = "".join(
        block["text"] for block in done["message"]["content"] if block.get("type") == "text"
    )
    assert "Only final" in text


@pytest.mark.anyio
async def test_stream_normalizes_cookie_fragment() -> None:
    model = get_model("perplexity-pro", "auto")
    assert model is not None
    seen: dict[str, str] = {}

    async def fake_chunks(session_token, query, mode, model_pref):
        seen["token"] = session_token
        seen["mode"] = mode
        yield {"delta": "x", "answer": "x", "done": False}
        yield {"delta": "", "answer": "x", "done": True}

    with patch(
        "pi_mono.ai.providers.perplexity_web._iter_perplexity_chunks",
        fake_chunks,
    ):
        stream = stream_perplexity_web(
            model,
            {"messages": [{"role": "user", "content": "hi"}]},
            {"apiKey": "__Secure-next-auth.session-token=env-tok; Path=/; Secure"},
        )
        _ = [event async for event in stream]
    assert seen["token"] == "env-tok"
    assert seen["mode"] == "auto"
