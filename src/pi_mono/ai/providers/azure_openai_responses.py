"""Azure OpenAI Responses API provider."""

import os
from typing import Any

from openai import AzureOpenAI

from pi_mono.ai.models import clamp_thinking_level
from pi_mono.ai.providers.openai_prompt_cache import clamp_openai_prompt_cache_key
from pi_mono.ai.providers.openai_responses_shared import (
    OpenAIResponsesStreamOptions,
    convert_responses_messages,
    convert_responses_tools,
    process_responses_stream,
)
from pi_mono.ai.providers.simple_options import build_base_options, resolve_sampling_params
from pi_mono.ai.utils.event_stream import AssistantMessageEventStream
from pi_mono.ai.utils.headers import headers_to_record

DEFAULT_AZURE_API_VERSION = "v1"
AZURE_TOOL_CALL_PROVIDERS = {"openai", "openai-codex", "opencode", "azure"}


def _parse_deployment_name_map(value: str | None) -> dict[str, str]:
    """Parse deployment name map from string like 'model1=dep1,model2=dep2'."""
    result: dict[str, str] = {}
    if not value:
        return result
    for entry in value.split(","):
        entry = entry.strip()
        if not entry:
            continue
        model_id, separator, deployment_name = entry.partition("=")
        if not separator or not model_id.strip() or not deployment_name.strip():
            continue
        result[model_id.strip()] = deployment_name.strip()
    return result


def _resolve_deployment_name(model: dict[str, Any], options: dict[str, Any] | None) -> str:
    """Resolve deployment name from options, env, or model ID."""
    if options and options.get("azureDeploymentName"):
        return options["azureDeploymentName"]

    env_map = _parse_deployment_name_map(os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME_MAP"))
    return env_map.get(model["id"]) or model["id"]


def _format_azure_openai_error(error: Exception) -> str:
    status = getattr(error, "status", None)
    if isinstance(status, int):
        return f"Azure OpenAI API error ({status}): {error}"
    return str(error)


class AzureOpenAIResponsesOptions:
    """Azure OpenAI Responses-specific options."""

    def __init__(
        self,
        reasoning_effort: str | None = None,
        reasoning_summary: str | None = None,
        azure_api_version: str | None = None,
        azure_resource_name: str | None = None,
        azure_base_url: str | None = None,
        azure_deployment_name: str | None = None,
        **kwargs,
    ):
        self.reasoning_effort = reasoning_effort
        self.reasoning_summary = reasoning_summary
        self.azure_api_version = azure_api_version
        self.azure_resource_name = azure_resource_name
        self.azure_base_url = azure_base_url
        self.azure_deployment_name = azure_deployment_name
        for k, v in kwargs.items():
            setattr(self, k, v)


def _normalize_azure_base_url(base_url: str) -> str:
    """Normalize Azure base URL to ensure /openai/v1 path."""
    from urllib.parse import urlparse, urlunparse

    trimmed = base_url.strip().rstrip("/")
    parsed = urlparse(trimmed)
    if not parsed.scheme or not parsed.hostname:
        raise ValueError(f"Invalid Azure OpenAI base URL: {base_url}")
    is_azure_host = (
        parsed.hostname.endswith(".openai.azure.com")
        or parsed.hostname.endswith(".cognitiveservices.azure.com")
        or parsed.hostname.endswith(".ai.azure.com")
    )
    normalized_path = parsed.path.rstrip("/")

    if is_azure_host and normalized_path in ("", "/", "/openai", "/openai/v1/responses"):
        parsed = parsed._replace(path="/openai/v1", query="")

    return urlunparse(parsed).rstrip("/")


def _build_default_base_url(resource_name: str) -> str:
    return f"https://{resource_name}.openai.azure.com/openai/v1"


def _resolve_azure_config(
    model: dict[str, Any],
    options: dict[str, Any] | None,
) -> tuple[str, str]:
    """Resolve Azure base URL and API version."""
    resolved = options or {}
    api_version = (
        resolved.get("azureApiVersion")
        or os.environ.get("AZURE_OPENAI_API_VERSION")
        or DEFAULT_AZURE_API_VERSION
    )

    raw_base_url = resolved.get("azureBaseUrl")
    base_url = raw_base_url.strip() if isinstance(raw_base_url, str) else ""
    base_url = base_url or os.environ.get("AZURE_OPENAI_BASE_URL", "").strip() or None
    resource_name = resolved.get("azureResourceName") or os.environ.get("AZURE_OPENAI_RESOURCE_NAME")

    if not base_url and resource_name:
        base_url = _build_default_base_url(resource_name)
    if not base_url:
        base_url = model.get("baseUrl")

    if not base_url:
        raise ValueError(
            "Azure OpenAI base URL is required. Set AZURE_OPENAI_BASE_URL or AZURE_OPENAI_RESOURCE_NAME, "
            "or pass azureBaseUrl, azureResourceName, or model.baseUrl."
        )

    return _normalize_azure_base_url(base_url), api_version


def _create_client(
    model: dict[str, Any],
    api_key: str,
    options: dict[str, Any] | None = None,
) -> AzureOpenAI:
    headers = {**model.get("headers", {})}
    if options and options.get("headers"):
        headers.update(options["headers"])

    base_url, api_version = _resolve_azure_config(model, options)

    return AzureOpenAI(
        api_key=api_key,
        api_version=api_version,
        base_url=base_url,
        default_headers=headers,
    )


def _build_params(
    model: dict[str, Any],
    context: dict[str, Any],
    options: dict[str, Any] | None,
    deployment_name: str,
) -> dict[str, Any]:
    from pi_mono.ai.providers.openai_responses_shared import ConvertResponsesMessagesOptions

    messages = convert_responses_messages(
        model, context, AZURE_TOOL_CALL_PROVIDERS, ConvertResponsesMessagesOptions()
    )

    params: dict[str, Any] = {
        "model": deployment_name,
        "input": messages,
        "stream": True,
        "prompt_cache_key": clamp_openai_prompt_cache_key(
            options.get("sessionId") if options else None
        ),
    }

    if options:
        if options.get("maxTokens"):
            params["max_output_tokens"] = options["maxTokens"]
        if options.get("temperature") is not None:
            params["temperature"] = options["temperature"]
        if context.get("tools"):
            params["tools"] = convert_responses_tools(context["tools"])

    if model.get("reasoning"):
        reasoning_effort = options.get("reasoningEffort") if options else None
        reasoning_summary = options.get("reasoningSummary") if options else None
        if reasoning_effort or reasoning_summary:
            effort = reasoning_effort
            if reasoning_effort:
                effort = model.get("thinkingLevelMap", {}).get(reasoning_effort, reasoning_effort)
            else:
                effort = "medium"
            params["reasoning"] = {
                "effort": effort,
                "summary": reasoning_summary or "auto",
            }
            params["include"] = ["reasoning.encrypted_content"]
        elif model.get("thinkingLevelMap", {}).get("off") is not None:
            params["reasoning"] = {"effort": model["thinkingLevelMap"]["off"]}

    # Last so model and request sampling parameters override named request fields.
    thinking_level = "off"
    if options:
        thinking_level = options.get("reasoningEffort") or "off"
        if thinking_level == "off" and options.get("reasoningSummary"):
            thinking_level = "medium"
    sampling_params = resolve_sampling_params(
        model, thinking_level, options.get("samplingParams") if options else None
    )
    if sampling_params:
        params.update(sampling_params)

    return params


def stream_azure_openai_responses(
    model: dict[str, Any],
    context: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> AssistantMessageEventStream:
    stream = AssistantMessageEventStream()

    async def run() -> None:
        output: dict[str, Any] = {
            "role": "assistant",
            "content": [],
            "api": "azure-openai-responses",
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

            deployment_name = _resolve_deployment_name(model, options)
            client = _create_client(model, api_key, options)
            params = _build_params(model, context, options, deployment_name)

            next_params = (
                await options.get("onPayload", lambda p, m: None)(params, model)
                if options
                else None
            )
            if next_params is not None:
                params = next_params

            request_options = {}
            if options:
                if options.get("signal"):
                    request_options["signal"] = options["signal"]
                if options.get("timeoutMs") is not None:
                    request_options["timeout"] = options["timeoutMs"] / 1000
                request_options["max_retries"] = options.get("maxRetries", 0)

            response = await client.responses.create(**params, **request_options)
            (
                await options.get("onResponse", lambda r, m: None)(
                    {
                        "status": response.status if hasattr(response, "status") else 200,
                        "headers": (
                            headers_to_record(response.headers)
                            if hasattr(response, "headers")
                            else {}
                        ),
                    },
                    model,
                )
                if options
                else None
            )

            stream.push({"type": "start", "partial": output})

            await process_responses_stream(
                response,
                output,
                stream,
                model,
                OpenAIResponsesStreamOptions(
                    on_provider_stream_event=(
                        options.get("onProviderStreamEvent") if options else None
                    )
                ),
            )

            if options and options.get("signal", {}).get("aborted"):
                raise RuntimeError("Request was aborted")

            if output["stopReason"] in ("aborted", "error"):
                raise RuntimeError("An unknown error occurred")

            stream.push({"type": "done", "reason": output["stopReason"], "message": output})
            stream.end()

        except Exception as error:
            for block in output["content"]:
                block.pop("index", None)
                block.pop("partialJson", None)
            output["stopReason"] = (
                "aborted" if (options and options.get("signal", {}).get("aborted")) else "error"
            )
            output["errorMessage"] = _format_azure_openai_error(error)
            stream.push({"type": "error", "reason": output["stopReason"], "error": output})
            stream.end()

    import asyncio

    asyncio.create_task(run())
    return stream


def stream_simple_azure_openai_responses(
    model: dict[str, Any],
    context: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> AssistantMessageEventStream:
    api_key = options.get("apiKey") if options else None
    if not api_key:
        raise ValueError(f"No API key for provider: {model['provider']}")

    base = build_base_options(model, context, options, api_key)
    clamped_reasoning = (
        clamp_thinking_level(model, options.get("reasoning"))
        if options and options.get("reasoning")
        else None
    )
    reasoning_effort = None if clamped_reasoning == "off" else clamped_reasoning

    return stream_azure_openai_responses(
        model, context, {**base, "reasoningEffort": reasoning_effort}
    )


def _prepare_azure_completions(
    model: dict[str, Any],
    options: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve the Azure endpoint and send the deployment name as the request model."""
    resolved_options = dict(options or {})
    base_url, _api_version = _resolve_azure_config(model, resolved_options)
    resolved_model = {**model, "baseUrl": base_url, "provider": model.get("provider") or "azure"}
    deployment_name = _resolve_deployment_name(model, resolved_options)
    if deployment_name != model["id"]:
        previous = resolved_options.get("onPayload")

        async def _on_payload(
            payload: dict[str, Any], payload_model: dict[str, Any]
        ) -> dict[str, Any]:
            params = {**payload, "model": deployment_name}
            if previous is None:
                return params
            next_params = previous(params, payload_model)
            if hasattr(next_params, "__await__"):
                next_params = await next_params
            return next_params if next_params is not None else params

        resolved_options["onPayload"] = _on_payload
    return resolved_model, resolved_options


def _setup_error_stream(model: dict[str, Any], error: BaseException) -> AssistantMessageEventStream:
    """Report endpoint setup failures on the stream, matching lazyStream."""
    import asyncio

    stream = AssistantMessageEventStream()
    message: dict[str, Any] = {
        "role": "assistant",
        "content": [],
        "api": model.get("api", "openai-completions"),
        "provider": model.get("provider", "azure"),
        "model": model.get("id", ""),
        "usage": {
            "input": 0,
            "output": 0,
            "cacheRead": 0,
            "cacheWrite": 0,
            "totalTokens": 0,
            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0},
        },
        "stopReason": "error",
        "errorMessage": str(error),
        "timestamp": stream._started_at - 1,
    }

    async def emit() -> None:
        stream.push({"type": "error", "reason": "error", "error": message})
        stream.end()

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()
    loop.create_task(emit())
    return stream


def stream_azure_openai_completions(
    model: dict[str, Any],
    context: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> AssistantMessageEventStream:
    from pi_mono.ai.providers.openai_completions import stream_openai_completions

    try:
        resolved_model, resolved_options = _prepare_azure_completions(model, options)
    except Exception as error:
        return _setup_error_stream(model, error)
    return stream_openai_completions(resolved_model, context, resolved_options)


def stream_simple_azure_openai_completions(
    model: dict[str, Any],
    context: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> AssistantMessageEventStream:
    from pi_mono.ai.providers.openai_completions import stream_simple_openai_completions

    try:
        resolved_model, resolved_options = _prepare_azure_completions(model, options)
    except Exception as error:
        return _setup_error_stream(model, error)
    return stream_simple_openai_completions(resolved_model, context, resolved_options)


streamAzureOpenAIResponses = stream_azure_openai_responses
streamSimpleAzureOpenAIResponses = stream_simple_azure_openai_responses
