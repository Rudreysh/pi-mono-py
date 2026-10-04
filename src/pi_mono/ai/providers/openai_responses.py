"""OpenAI Responses API provider."""

import os
from openai import AsyncOpenAI

from pi_mono.ai.models import clamp_thinking_level
from pi_mono.ai.types import (
    Any,
    AssistantMessage,
    Context,
    Model,
    OpenAIResponsesCompat,
    SimpleStreamOptions,
    StreamOptions,
    Usage,
)
from pi_mono.ai.utils.event_stream import AssistantMessageEventStream
from pi_mono.ai.utils.headers import headers_to_record
from pi_mono.ai.providers.cloudflare import is_cloudflare_provider, resolve_cloudflare_base_url
from pi_mono.ai.providers.github_copilot_headers import (
    build_copilot_dynamic_headers,
    has_copilot_vision_input,
)
from pi_mono.ai.providers.openai_prompt_cache import clamp_openai_prompt_cache_key
from pi_mono.ai.providers.openai_responses_shared import (
    OpenAIResponsesStreamOptions,
    convert_responses_messages,
    convert_responses_tools,
    encode_text_signature_v1 as encode_text_signature_v1,
    parse_text_signature as parse_text_signature,
)
from pi_mono.ai.providers.simple_options import build_base_options, resolve_sampling_params
from pi_mono.utils.abort_signals import is_aborted

OPENAI_TOOL_CALL_PROVIDERS = {"openai", "openai-codex", "opencode"}


def resolve_cache_retention(cache_retention: str | None) -> str:
    if cache_retention:
        return cache_retention
    if os.environ.get("PI_CACHE_RETENTION") == "long":
        return "long"
    return "short"


def _detect_session_affinity_format(model: Model[str]) -> str:
    base_url = model.get("baseUrl", "")
    if "openrouter.ai" in base_url:
        return "openrouter"
    return "openai"


def get_compat(model: Model[str]) -> OpenAIResponsesCompat:
    compat = model.get("compat", {})
    format_val = compat.get("sessionAffinityFormat")
    if not format_val:
        if compat.get("sendSessionIdHeader") is False:
            format_val = "openai-nosession"
        else:
            format_val = _detect_session_affinity_format(model)
    return {
        "sessionAffinityFormat": format_val,
        "supportsLongCacheRetention": compat.get("supportsLongCacheRetention", True),
        "supportsExplicitPromptCacheMode": compat.get("supportsExplicitPromptCacheMode", False),
        "supportsMaxOutputTokens": compat.get("supportsMaxOutputTokens", True),
        "sendSessionIdHeader": compat.get("sendSessionIdHeader", True),
    }


def get_prompt_cache_retention(compat: OpenAIResponsesCompat, cache_retention: str) -> str | None:
    return (
        "24h"
        if cache_retention == "long"
        and compat.get("supportsLongCacheRetention")
        and not compat.get("supportsExplicitPromptCacheMode")
        else None
    )


def get_prompt_cache_options(
    compat: OpenAIResponsesCompat, cache_retention: str
) -> dict[str, str] | None:
    if not compat.get("supportsExplicitPromptCacheMode"):
        return None
    if cache_retention == "none":
        return {"mode": "explicit"}
    if cache_retention == "long" and compat.get("supportsLongCacheRetention"):
        return {"ttl": "30m"}
    return None


def format_openai_responses_error(error: Exception) -> str:
    for attr in ("status_code", "status"):
        status = getattr(error, attr, None)
        if isinstance(status, int):
            return f"OpenAI API error ({status}): {error}"
    return str(error)


def _get_prompt_cache_retention(compat: OpenAIResponsesCompat, cache_retention: str) -> str | None:
    return get_prompt_cache_retention(compat, cache_retention)


def _format_openai_responses_error(error: Exception) -> str:
    status = getattr(error, "status", None)
    if isinstance(status, int):
        return f"OpenAI API error ({status}): {error}"
    return str(error)


OPENAI_RESPONSES_MIN_OUTPUT_TOKENS = 16


def _pick(kwargs: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in kwargs:
            return kwargs[key]
    return None


class OpenAIResponsesOptions:
    def __init__(self, **kwargs: Any):
        self._data = kwargs
        self.reasoning_effort = _pick(kwargs, "reasoningEffort", "reasoning_effort")
        self.reasoning_summary = kwargs.get("reasoningSummary", kwargs.get("reasoning_summary"))
        self.service_tier = _pick(kwargs, "serviceTier", "service_tier")
        self.session_id = _pick(kwargs, "sessionId", "session_id")
        self.cache_retention = _pick(kwargs, "cacheRetention", "cache_retention")
        self.max_tokens = _pick(kwargs, "maxTokens", "max_tokens")
        self.temperature = kwargs.get("temperature")
        self.tool_choice = _pick(kwargs, "toolChoice", "tool_choice")

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self._data[key]


def _get_service_tier_cost_multiplier(model_id: str, service_tier: str | None) -> float:
    if service_tier == "flex":
        return 0.5
    if service_tier in ("priority", "fast"):
        return 2.5 if model_id == "gpt-5.5" else 2.0
    return 1.0


def _apply_service_tier_pricing(usage: Usage, service_tier: str | None, model_id: str) -> None:
    multiplier = _get_service_tier_cost_multiplier(model_id, service_tier)
    if multiplier == 1.0:
        return
    usage["cost"]["input"] *= multiplier
    usage["cost"]["output"] *= multiplier
    usage["cost"]["cacheRead"] *= multiplier
    usage["cost"]["cacheWrite"] *= multiplier
    usage["cost"]["total"] = (
        usage["cost"]["input"]
        + usage["cost"]["output"]
        + usage["cost"]["cacheRead"]
        + usage["cost"]["cacheWrite"]
    )


def _create_client(
    model: Model[str],
    context: Context,
    api_key: str,
    options_headers: dict[str, str] | None = None,
    session_id: str | None = None,
) -> AsyncOpenAI:
    compat = get_compat(model)
    headers = {**model.get("headers", {})}

    if model["provider"] == "github-copilot":
        has_images = has_copilot_vision_input(context.get("messages", []))
        copilot_headers = build_copilot_dynamic_headers(
            {"messages": context["messages"], "hasImages": has_images}
        )
        headers.update(copilot_headers)

    if session_id:
        affinity_format = compat.get("sessionAffinityFormat", "openai")
        if affinity_format == "openrouter":
            headers["x-session-id"] = session_id
        else:
            if affinity_format == "openai":
                headers["session_id"] = session_id
            headers["x-client-request-id"] = session_id

    if options_headers:
        headers.update(options_headers)

    if model["provider"] == "cloudflare-ai-gateway":
        default_headers = {
            **headers,
            "Authorization": headers.get("Authorization"),
            "cf-aig-authorization": f"Bearer {api_key}",
        }
    else:
        default_headers = headers

    base_url = (
        resolve_cloudflare_base_url(model)
        if is_cloudflare_provider(model["provider"])
        else model.get("baseUrl")
    )

    return AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        default_headers=default_headers,
    )


def _build_params(
    model: Model[str],
    context: Context,
    options: OpenAIResponsesOptions | None = None,
) -> dict[str, Any]:
    from pi_mono.ai.providers.openai_responses_shared import ConvertResponsesMessagesOptions

    messages = convert_responses_messages(
        model, context, OPENAI_TOOL_CALL_PROVIDERS, ConvertResponsesMessagesOptions()
    )

    cache_retention = resolve_cache_retention(options.cache_retention if options else None)
    compat = get_compat(model)

    params: dict[str, Any] = {
        "model": model["id"],
        "input": messages,
        "stream": True,
        "prompt_cache_key": (
            None
            if cache_retention == "none"
            else clamp_openai_prompt_cache_key(options.session_id if options else None)
        ),
        "store": False,
    }
    prompt_cache_retention = _get_prompt_cache_retention(compat, cache_retention)
    if prompt_cache_retention is not None:
        # Older OpenAI SDKs do not expose this newer request field in their type signature.
        params["extra_body"] = {"prompt_cache_retention": prompt_cache_retention}
    prompt_cache_options = get_prompt_cache_options(compat, cache_retention)
    if prompt_cache_options is not None:
        params["prompt_cache_options"] = prompt_cache_options

    if options:
        if options.max_tokens and compat.get("supportsMaxOutputTokens", True):
            params["max_output_tokens"] = max(options.max_tokens, OPENAI_RESPONSES_MIN_OUTPUT_TOKENS)
        if options.temperature is not None:
            params["temperature"] = options.temperature
        if options.service_tier is not None:
            params["service_tier"] = options.service_tier
        if options.tool_choice is not None:
            params["tool_choice"] = options.tool_choice

    if context.get("tools"):
        params["tools"] = convert_responses_tools(context["tools"])

    if model.get("reasoning"):
        reasoning_effort = options.reasoning_effort if options else None
        reasoning_summary = options.reasoning_summary if options else None
        if reasoning_effort or reasoning_summary:
            mapped = (
                model.get("thinkingLevelMap", {}).get(reasoning_effort, reasoning_effort)
                if reasoning_effort
                else "medium"
            )
            effort = mapped if mapped else "medium"
            params["reasoning"] = {
                "effort": effort,
                "summary": reasoning_summary or "auto",
            }
            params["include"] = ["reasoning.encrypted_content"]
        elif (
            model["provider"] != "github-copilot"
            and model.get("thinkingLevelMap", {}).get("off") is not None
        ):
            params["reasoning"] = {"effort": model["thinkingLevelMap"].get("off", "none")}

    # Last so model and request sampling parameters override named request fields.
    thinking_level = "off"
    if options:
        thinking_level = options.reasoning_effort or "off"
        if thinking_level == "off" and options.reasoning_summary:
            thinking_level = "medium"
    sampling_params = resolve_sampling_params(
        model, thinking_level, options.get("samplingParams") if options else None
    )
    if sampling_params:
        params.update(sampling_params)

    return params


def stream_openai_responses(
    model: Model[str],
    context: Context,
    options: StreamOptions | None = None,
) -> AssistantMessageEventStream:
    from pi_mono.ai.providers.openai_responses_shared import process_responses_stream as prs

    stream = AssistantMessageEventStream()

    async def run() -> None:
        output: AssistantMessage = {
            "role": "assistant",
            "content": [],
            "api": model["api"],
            "provider": model["provider"],
            "model": model["id"],
            "usage": {
                "input": 0,
                "output": 0,
                "cacheRead": 0,
                "cacheWrite": 0,
                "totalTokens": 0,
                "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0},
            },
            "stopReason": "pending",
            "timestamp": int(__import__("time").time() * 1000),
        }

        try:
            api_key = options.get("apiKey") if options else None
            if not api_key:
                raise ValueError(f"No API key for provider: {model['provider']}")

            cache_retention = resolve_cache_retention(
                options.get("cacheRetention") if options else None
            )
            cache_session_id = (
                None if cache_retention == "none" else options.get("sessionId") if options else None
            )

            client = _create_client(
                model,
                context,
                api_key,
                options.get("headers") if options else None,
                cache_session_id,
            )
            params = _build_params(
                model, context, OpenAIResponsesOptions(**options) if options else None
            )

            next_params = (
                await options.get("onPayload", lambda p, m: None)(params, model)
                if options
                else None
            )
            if next_params is not None:
                params = next_params

            request_options = {}
            if options:
                if options.get("timeoutMs") is not None:
                    request_options["timeout"] = options["timeoutMs"] / 1000
                client = client.with_options(max_retries=options.get("maxRetries") or 0)

            response = await client.responses.create(**params, **request_options)
            (
                await options.get("onResponse", lambda r, m: None)(
                    {
                        "status": getattr(response, "status", 200),
                        "headers": headers_to_record(getattr(response, "headers", {})),
                    },
                    model,
                )
                if options
                else None
            )

            stream.push({"type": "start", "partial": output})

            await prs(
                response,
                output,
                stream,
                model,
                OpenAIResponsesStreamOptions(
                    on_provider_stream_event=options.get("onProviderStreamEvent") if options else None,
                    service_tier=options.get("serviceTier") if options else None,
                    apply_service_tier_pricing=lambda u, st: _apply_service_tier_pricing(
                        u, st, model["id"]
                    ),
                ),
            )

            if options and is_aborted(options.get("signal")):
                raise RuntimeError("Request was aborted")

            if output["stopReason"] in ("aborted", "error"):
                raise RuntimeError("An unknown error occurred")

            stream.push({"type": "done", "reason": output["stopReason"], "message": output})
            stream.end()

        except Exception as error:
            for block in output["content"]:
                block.pop("index", None)
                block.pop("partialJson", None)
            output["stopReason"] = "aborted" if options and is_aborted(options.get("signal")) else "error"
            output["errorMessage"] = _format_openai_responses_error(error)
            stream.push({"type": "error", "reason": output["stopReason"], "error": output})
            stream.end()

    import asyncio

    asyncio.create_task(run())
    return stream


def stream_simple_openai_responses(
    model: Model[str],
    context: Context,
    options: SimpleStreamOptions | None = None,
) -> AssistantMessageEventStream:
    api_key = options.get("apiKey") if options else None
    if not api_key:
        raise ValueError(f"No API key for provider: {model['provider']}")

    base = build_base_options(model, context, options, api_key)
    clamped_reasoning = (
        clamp_thinking_level(model, options["reasoning"])
        if options and options.get("reasoning")
        else None
    )
    reasoning_effort = None if clamped_reasoning == "off" else clamped_reasoning

    return stream_openai_responses(model, context, {**base, "reasoningEffort": reasoning_effort})


streamOpenAIResponses = stream_openai_responses
streamSimpleOpenAIResponses = stream_simple_openai_responses
