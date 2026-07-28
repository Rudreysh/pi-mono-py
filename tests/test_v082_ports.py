"""Tests for v0.82.1 Python ports."""

from __future__ import annotations

import asyncio

import pytest


class TestKnownProviderTypes:
    def test_qwen_token_plan_in_known_provider(self) -> None:
        from pi_mono.ai.types import KnownProvider

        args = KnownProvider.__args__  # type: ignore[attr-defined]
        assert "qwen-token-plan" in args
        assert "qwen-token-plan-cn" in args
        assert "radius" in args

    def test_session_affinity_format_type(self) -> None:
        from pi_mono.ai.types import SessionAffinityFormat

        args = SessionAffinityFormat.__args__  # type: ignore[attr-defined]
        assert "openai" in args
        assert "openai-nosession" in args
        assert "openrouter" in args


class TestOpenAIResponsesCompat:
    def test_session_affinity_format_field(self) -> None:
        from pi_mono.ai.types import OpenAIResponsesCompat

        compat: OpenAIResponsesCompat = {"sessionAffinityFormat": "openrouter"}
        assert compat["sessionAffinityFormat"] == "openrouter"

    def test_deprecated_send_session_id_header(self) -> None:
        from pi_mono.ai.types import OpenAIResponsesCompat

        compat: OpenAIResponsesCompat = {"sendSessionIdHeader": True}
        assert compat["sendSessionIdHeader"] is True

    def test_get_compat_openrouter_model(self) -> None:
        from pi_mono.ai.providers.openai_responses import get_compat

        model = {"compat": {"sessionAffinityFormat": "openrouter"}}
        compat = get_compat(model)
        assert compat["sessionAffinityFormat"] == "openrouter"

    def test_get_compat_nosession_via_legacy(self) -> None:
        from pi_mono.ai.providers.openai_responses import get_compat

        model = {"compat": {"sendSessionIdHeader": False}}
        compat = get_compat(model)
        assert compat["sessionAffinityFormat"] == "openai-nosession"

    def test_get_compat_defaults(self) -> None:
        from pi_mono.ai.providers.openai_responses import get_compat

        model: dict = {}
        compat = get_compat(model)
        assert compat["sessionAffinityFormat"] == "openai"
        assert compat["supportsLongCacheRetention"] is True


class TestToolResultMessageAddedToolNames:
    def test_added_tool_names_optional(self) -> None:
        from pi_mono.ai.types import ToolResultMessage

        msg: ToolResultMessage = {
            "role": "toolResult",
            "toolCallId": "call_1",
            "toolName": "test",
            "content": [],
            "isError": False,
            "timestamp": 0,
        }
        assert "addedToolNames" not in msg

    def test_added_tool_names_present(self) -> None:
        from pi_mono.ai.types import ToolResultMessage

        msg: ToolResultMessage = {
            "role": "toolResult",
            "toolCallId": "call_1",
            "toolName": "test",
            "content": [],
            "addedToolNames": ["new_tool"],
            "isError": False,
            "timestamp": 0,
        }
        assert msg["addedToolNames"] == ["new_tool"]


class TestEnvApiKeys:
    def test_qwen_token_plan_env_key(self) -> None:
        from pi_mono.ai.env_api_keys import get_api_key_env_vars

        assert get_api_key_env_vars("qwen-token-plan") == ["QWEN_TOKEN_PLAN_API_KEY"]
        assert get_api_key_env_vars("qwen-token-plan-cn") == ["QWEN_TOKEN_PLAN_CN_API_KEY"]
        assert get_api_key_env_vars("radius") == ["RADIUS_API_KEY"]


class TestProviderDisplayNames:
    def test_new_providers(self) -> None:
        from pi_mono.core.provider_display_names import BUILT_IN_PROVIDER_DISPLAY_NAMES

        assert BUILT_IN_PROVIDER_DISPLAY_NAMES["qwen-token-plan"] == "Qwen Token Plan"
        assert BUILT_IN_PROVIDER_DISPLAY_NAMES["qwen-token-plan-cn"] == "Qwen Token Plan (China)"
        assert BUILT_IN_PROVIDER_DISPLAY_NAMES["radius"] == "Radius Gateway"


class TestDefaultModels:
    def test_new_provider_defaults(self) -> None:
        from pi_mono.coding_agent.core.model_resolver import default_model_per_provider

        assert "qwen-token-plan" in default_model_per_provider
        assert "qwen-token-plan-cn" in default_model_per_provider
        assert "radius" in default_model_per_provider


class TestConstrainedSampling:
    def test_supports_grammar_tools(self) -> None:
        from pi_mono.ai.utils.constrained_sampling import supports_grammar_tools

        assert supports_grammar_tools({"compat": {"supportsOpenAIGrammarTools": True}})
        assert not supports_grammar_tools({"compat": {}})
        assert not supports_grammar_tools({})

    def test_supports_strict_tools_openai(self) -> None:
        from pi_mono.ai.utils.constrained_sampling import supports_strict_tools

        assert supports_strict_tools({"compat": {"supportsStrictMode": True}})
        assert not supports_strict_tools({"compat": {"supportsStrictMode": False}})

    def test_supports_strict_tools_anthropic(self) -> None:
        from pi_mono.ai.utils.constrained_sampling import supports_strict_tools

        assert supports_strict_tools({"api": "anthropic-messages", "compat": {"supportsStrictTools": True}})
        assert not supports_strict_tools({"api": "anthropic-messages", "compat": {}})

    def test_resolve_json_schema_strict_sampling(self) -> None:
        from pi_mono.ai.utils.constrained_sampling import resolve_json_schema_strict_sampling

        assert resolve_json_schema_strict_sampling({"constrainedSampling": {"type": "json_schema"}}, True) is True
        assert resolve_json_schema_strict_sampling({"constrainedSampling": {"type": "json_schema"}}, False) is None
        assert resolve_json_schema_strict_sampling({}, True) is None

    def test_resolve_json_schema_strict_require(self) -> None:
        from pi_mono.ai.utils.constrained_sampling import resolve_json_schema_strict_sampling

        with pytest.raises(ValueError, match="requires JSON-schema"):
            resolve_json_schema_strict_sampling(
                {"name": "t", "constrainedSampling": {"type": "json_schema", "strict": "require"}},
                False,
            )

    def test_grammar_tool_input(self) -> None:
        from pi_mono.ai.utils.constrained_sampling import get_grammar_tool_input

        assert get_grammar_tool_input("t", {"code": "hello"}, "code") == "hello"
        with pytest.raises(ValueError, match="to be a string"):
            get_grammar_tool_input("t", {"code": 42}, "code")


class TestOAuthProviderRegistration:
    def test_builtin_providers_include_new(self) -> None:
        from pi_mono.ai.utils.oauth import BUILT_IN_OAUTH_PROVIDERS

        ids = [p.id for p in BUILT_IN_OAUTH_PROVIDERS]
        assert "openrouter" in ids
        assert "kimi-coding" in ids
        assert "xai" in ids
        assert "radius" in ids

    def test_get_provider_by_id(self) -> None:
        from pi_mono.ai.utils.oauth import get_oauth_provider

        assert get_oauth_provider("openrouter") is not None
        assert get_oauth_provider("kimi-coding") is not None
        assert get_oauth_provider("xai") is not None
        assert get_oauth_provider("radius") is not None

    def test_provider_names(self) -> None:
        from pi_mono.ai.utils.oauth import get_oauth_provider

        assert get_oauth_provider("openrouter").name == "OpenRouter OAuth"
        assert get_oauth_provider("kimi-coding").name == "Kimi Code (subscription)"
        assert get_oauth_provider("xai").name == "xAI (Grok/X subscription)"
        assert get_oauth_provider("radius").name == "Radius Gateway"


class TestRetryAssistantCall:
    def test_is_retryable_dns_error(self) -> None:
        from pi_mono.ai.utils.retry import is_retryable_assistant_error

        dns_msg: dict = {
            "stopReason": "error",
            "errorMessage": "getaddrinfo ENOTFOUND api.example.com",
        }
        assert is_retryable_assistant_error(dns_msg)

    def test_is_retryable_enotfound(self) -> None:
        from pi_mono.ai.utils.retry import is_retryable_assistant_error

        msg: dict = {
            "stopReason": "error",
            "errorMessage": "connect ENOTFOUND api.example.com",
        }
        assert is_retryable_assistant_error(msg)

    def test_is_retryable_eai_again(self) -> None:
        from pi_mono.ai.utils.retry import is_retryable_assistant_error

        msg: dict = {
            "stopReason": "error",
            "errorMessage": "EAI_AGAIN api.example.com",
        }
        assert is_retryable_assistant_error(msg)

    def test_is_retryable_stream_ended(self) -> None:
        from pi_mono.ai.utils.retry import is_retryable_assistant_error

        msg: dict = {
            "stopReason": "error",
            "errorMessage": "stream ended before a terminal response event",
        }
        assert is_retryable_assistant_error(msg)

    def test_not_retryable_quota(self) -> None:
        from pi_mono.ai.utils.retry import is_retryable_assistant_error

        msg: dict = {"stopReason": "error", "errorMessage": "insufficient_quota"}
        assert not is_retryable_assistant_error(msg)

    @pytest.mark.anyio
    async def test_retry_assistant_call_no_retry_on_success(self) -> None:
        from pi_mono.ai.utils.retry import RetryPolicy, retry_assistant_call

        calls = 0

        async def produce() -> dict:
            nonlocal calls
            calls += 1
            return {"content": [{"type": "text", "text": "ok"}], "stopReason": "stop"}

        policy = RetryPolicy(enabled=True, max_retries=3, base_delay_ms=0)
        result = await retry_assistant_call(produce, policy)
        assert result["stopReason"] == "stop"
        assert calls == 1

    @pytest.mark.anyio
    async def test_retry_assistant_call_retries_transient(self) -> None:
        from pi_mono.ai.utils.retry import RetryPolicy, retry_assistant_call

        calls = 0

        async def produce() -> dict:
            nonlocal calls
            calls += 1
            if calls < 3:
                return {"stopReason": "error", "errorMessage": "terminated"}
            return {"content": [{"type": "text", "text": "ok"}], "stopReason": "stop"}

        policy = RetryPolicy(enabled=True, max_retries=3, base_delay_ms=0)
        result = await retry_assistant_call(produce, policy)
        assert result["stopReason"] == "stop"
        assert calls == 3

    @pytest.mark.anyio
    async def test_retry_does_not_retry_non_retryable(self) -> None:
        from pi_mono.ai.utils.retry import RetryPolicy, retry_assistant_call

        calls = 0

        async def produce() -> dict:
            nonlocal calls
            calls += 1
            return {"stopReason": "error", "errorMessage": "insufficient_quota"}

        policy = RetryPolicy(enabled=True, max_retries=3, base_delay_ms=0)
        result = await retry_assistant_call(produce, policy)
        assert result["stopReason"] == "error"
        assert calls == 1


class TestMcpPlaceholder:
    def test_mcp_client_not_connected(self) -> None:
        from pi_mono.coding_agent.core.mcp import McpClient

        client = McpClient()
        assert not client.is_connected

    @pytest.mark.anyio
    async def test_mcp_client_raises(self) -> None:
        from pi_mono.coding_agent.core.mcp import McpClient

        client = McpClient()
        with pytest.raises(NotImplementedError):
            await client.list_tools()
        with pytest.raises(NotImplementedError):
            await client.call_tool("test", {})
        with pytest.raises(NotImplementedError):
            await client.connect({})
        with pytest.raises(NotImplementedError):
            await client.disconnect()


class TestRemoteCatalogProvider:
    def test_init(self) -> None:
        from pi_mono.coding_agent.core.remote_catalog_provider import RemoteCatalogProvider

        provider = RemoteCatalogProvider("test", "https://example.com/models")
        assert provider.provider_id == "test"


class TestCredentialPrint:
    def test_run_credential_print_found(self, capsys: pytest.CaptureFixture[str]) -> None:
        from pi_mono.coding_agent.cli.credential_print import run_credential_print

        run_credential_print("openai", env={"OPENAI_API_KEY": "sk-test-123"})
        out = capsys.readouterr().out
        assert "sk-test-123" in out

    def test_run_credential_print_not_found(self) -> None:
        from pi_mono.coding_agent.cli.credential_print import run_credential_print

        with pytest.raises(SystemExit):
            run_credential_print("nonexistent-provider", env={})


class TestBashSessionEvent:
    def test_bash_execution_update_event_type(self) -> None:
        from pi_mono.coding_agent.core.agent_session import AgentSessionEventBashExecutionUpdate

        event: AgentSessionEventBashExecutionUpdate = {
            "type": "bash_execution_update",
            "delta": "output chunk",
        }
        assert event["type"] == "bash_execution_update"
        assert event["delta"] == "output chunk"


class TestSummarizationRetryEvents:
    def test_summarization_retry_event_types(self) -> None:
        from pi_mono.coding_agent.core.agent_session import (
            AgentSessionEventSummarizationRetryScheduled,
            AgentSessionEventSummarizationRetryAttemptStart,
            AgentSessionEventSummarizationRetryFinished,
        )

        scheduled: AgentSessionEventSummarizationRetryScheduled = {
            "type": "summarization_retry_scheduled",
            "attempt": 1,
            "maxAttempts": 3,
            "delayMs": 1000,
            "errorMessage": "terminated",
        }
        assert scheduled["type"] == "summarization_retry_scheduled"

        start: AgentSessionEventSummarizationRetryAttemptStart = {
            "type": "summarization_retry_attempt_start",
            "source": "compaction",
        }
        assert start["type"] == "summarization_retry_attempt_start"

        finished: AgentSessionEventSummarizationRetryFinished = {
            "type": "summarization_retry_finished",
        }
        assert finished["type"] == "summarization_retry_finished"
