import json
from pi_mono.ai.providers.openai_responses import (
    OpenAIResponsesOptions,
    _apply_service_tier_pricing,
    _build_params,
    clamp_openai_prompt_cache_key,
    convert_responses_messages,
    format_openai_responses_error,
    get_compat,
    get_prompt_cache_options,
    get_prompt_cache_retention,
    parse_text_signature,
    resolve_cache_retention,
    encode_text_signature_v1,
)


def test_clamp_openai_prompt_cache_key():
    assert clamp_openai_prompt_cache_key(None) is None
    assert clamp_openai_prompt_cache_key("abc") == "abc"
    long_key = "a" * 100
    assert len(clamp_openai_prompt_cache_key(long_key)) == 64


def test_resolve_cache_retention(monkeypatch):
    assert resolve_cache_retention("long") == "long"
    assert resolve_cache_retention(None) == "short"

    monkeypatch.setenv("PI_CACHE_RETENTION", "long")
    assert resolve_cache_retention(None) == "long"


def test_get_compat():
    model_empty = {}
    compat = get_compat(model_empty)
    assert compat["sendSessionIdHeader"] is True
    assert compat["supportsLongCacheRetention"] is True

    model_custom = {"compat": {"sendSessionIdHeader": False, "supportsLongCacheRetention": False}}
    compat_custom = get_compat(model_custom)
    assert compat_custom["sendSessionIdHeader"] is False
    assert compat_custom["supportsLongCacheRetention"] is False


def test_get_prompt_cache_retention():
    compat = {"sendSessionIdHeader": True, "supportsLongCacheRetention": True}
    assert get_prompt_cache_retention(compat, "long") == "24h"
    assert get_prompt_cache_retention(compat, "short") is None

    compat_no_long = {"sendSessionIdHeader": True, "supportsLongCacheRetention": False}
    assert get_prompt_cache_retention(compat_no_long, "long") is None

    compat_explicit = {
        "supportsLongCacheRetention": True,
        "supportsExplicitPromptCacheMode": True,
    }
    assert get_prompt_cache_retention(compat_explicit, "long") is None


def test_format_openai_responses_error():
    # Exception with status_code
    class CustomError(Exception):
        status_code = 403

    assert "OpenAI API error (403)" in format_openai_responses_error(CustomError("Forbidden"))

    # Exception with status
    class StatusError(Exception):
        status = 500

    assert "OpenAI API error (500)" in format_openai_responses_error(StatusError("Internal error"))

    # Normal Exception
    assert format_openai_responses_error(ValueError("Simple error")) == "Simple error"


def test_text_signatures():
    # encode_text_signature_v1
    sig1 = encode_text_signature_v1("id123")
    parsed1 = json.loads(sig1)
    assert parsed1["v"] == 1
    assert parsed1["id"] == "id123"
    assert "phase" not in parsed1

    sig2 = encode_text_signature_v1("id123", "commentary")
    parsed2 = json.loads(sig2)
    assert parsed2["phase"] == "commentary"

    # parse_text_signature
    assert parse_text_signature(None) is None
    assert parse_text_signature("simple-id") == {"id": "simple-id"}

    encoded_json = encode_text_signature_v1("my-id", "final_answer")
    assert parse_text_signature(encoded_json) == {"id": "my-id", "phase": "final_answer"}


def test_convert_responses_messages():
    model = {"id": "gpt-4o", "provider": "openai", "api": "openai-responses", "reasoning": True}
    context = {
        "systemPrompt": "Keep it concise.",
        "messages": [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": [{"type": "text", "text": "Hi there!"}]},
        ],
    }

    msgs = convert_responses_messages(model, context, {"openai"})
    assert len(msgs) == 3
    assert msgs[0]["role"] == "developer"
    assert msgs[0]["content"] == "Keep it concise."
    assert msgs[1]["role"] == "user"
    assert msgs[1]["content"] == [{"type": "input_text", "text": "Hello"}]
    assert msgs[2]["role"] == "assistant"


def test_openai_responses_options_maps_camel_case_and_supports_get():
    options = OpenAIResponsesOptions(
        reasoningEffort="high",
        sessionId="sess-1",
        cacheRetention="long",
        maxTokens=128,
        serviceTier="flex",
    )
    assert options.get("maxTokens") == 128
    assert options["reasoningEffort"] == "high"
    assert options.reasoning_effort == "high"
    assert options.session_id == "sess-1"
    assert options.cache_retention == "long"
    assert options.service_tier == "flex"


def test_build_params_from_camel_case_stream_options():
    model = {
        "id": "gpt-5",
        "provider": "openai",
        "api": "openai-responses",
        "reasoning": True,
        "thinkingLevelMap": {"high": "high", "off": "none"},
    }
    context = {"systemPrompt": "sys", "messages": [{"role": "user", "content": "hi"}]}
    params = _build_params(
        model,
        context,
        OpenAIResponsesOptions(reasoningEffort="high", maxTokens=32, sessionId="abc"),
    )
    assert params["reasoning"]["effort"] == "high"
    assert params["max_output_tokens"] == 32
    assert params["prompt_cache_key"] == "abc"
    assert "prompt_cache_retention" not in params


def test_build_params_sends_long_cache_retention_via_extra_body():
    model = {"id": "gpt-5", "provider": "openai", "api": "openai-responses"}
    context = {"messages": [{"role": "user", "content": "hi"}]}

    params = _build_params(
        model,
        context,
        OpenAIResponsesOptions(cacheRetention="long"),
    )

    assert params["extra_body"] == {"prompt_cache_retention": "24h"}


def test_build_params_merges_model_and_request_sampling_params():
    model = {
        "id": "gpt-5",
        "provider": "openai",
        "api": "openai-responses",
        "samplingParams": {"temperature": 0.2, "top_p": 0.8},
    }
    context = {"messages": [{"role": "user", "content": "hi"}]}

    params = _build_params(
        model,
        context,
        OpenAIResponsesOptions(samplingParams={"temperature": 0.7}),
    )

    assert params["temperature"] == 0.7
    assert params["top_p"] == 0.8


def test_prompt_cache_options_ttl_for_explicit_mode():
    compat = {
        "supportsExplicitPromptCacheMode": True,
        "supportsLongCacheRetention": True,
    }
    assert get_prompt_cache_options(compat, "long") == {"ttl": "30m"}
    assert get_prompt_cache_options(compat, "none") == {"mode": "explicit"}
    assert get_prompt_cache_options({"supportsExplicitPromptCacheMode": False}, "long") is None


def test_apply_service_tier_pricing_totals_cache_write():
    usage = {
        "cost": {
            "input": 2.0,
            "output": 2.0,
            "cacheRead": 2.0,
            "cacheWrite": 2.0,
            "total": 8.0,
        }
    }
    _apply_service_tier_pricing(usage, "flex", "gpt-5")
    assert usage["cost"]["input"] == 1.0
    assert usage["cost"]["cacheWrite"] == 1.0
    assert usage["cost"]["total"] == 4.0


def test_openai_fast_service_tier_uses_priority_pricing():
    usage = {
        "cost": {
            "input": 2.0,
            "output": 2.0,
            "cacheRead": 2.0,
            "cacheWrite": 2.0,
            "total": 8.0,
        }
    }

    _apply_service_tier_pricing(usage, "fast", "gpt-6-luna")

    assert usage["cost"] == {
        "input": 4.0,
        "output": 4.0,
        "cacheRead": 4.0,
        "cacheWrite": 4.0,
        "total": 16.0,
    }
