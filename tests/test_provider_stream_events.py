from __future__ import annotations

import pytest

from pi_mono.agent.agent import Agent
from pi_mono.ai.providers.openai_responses_shared import (
    OpenAIResponsesStreamOptions,
    process_responses_stream,
)
from pi_mono.utils.event_stream import AssistantMessageEventStream


async def _events():
    yield {"type": "response.created", "response": {"id": "response-1"}}
    yield {"type": "response.completed", "response": {"status": "completed", "usage": {}}}


@pytest.mark.anyio
async def test_openai_responses_observes_each_raw_event_before_normalization() -> None:
    observed: list[dict[str, object]] = []
    stream = AssistantMessageEventStream()
    output = {
        "role": "assistant",
        "content": [],
        "api": "openai-responses",
        "provider": "openai",
        "model": "gpt-test",
        "usage": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 0, "cost": {}},
        "stopReason": "pending",
    }
    model = {
        "id": "gpt-test",
        "provider": "openai",
        "api": "openai-responses",
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
    }

    async def observe(data, callback_model) -> None:
        assert callback_model is model
        observed.append(data)

    await process_responses_stream(
        _events(),
        output,
        stream,
        model,
        OpenAIResponsesStreamOptions(on_provider_stream_event=observe),
    )

    assert observed == [
        {"type": "response.created", "response": {"id": "response-1"}},
        {"type": "response.completed", "response": {"status": "completed", "usage": {}}},
    ]
    assert output["responseId"] == "response-1"


def test_agent_forwards_provider_stream_event_callback_to_loop_config() -> None:
    callback = lambda _data, _model: None
    agent = Agent({"onProviderStreamEvent": callback})

    assert agent.createLoopConfig()["onProviderStreamEvent"] is callback
