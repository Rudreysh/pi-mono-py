"""Perplexity provider registration and auth wiring."""

from __future__ import annotations

from pi_mono.ai.env_api_keys import get_api_key_env_vars, get_env_api_key
from pi_mono.ai.models import get_model, get_models, get_providers
from pi_mono.coding_agent.core.model_resolver import default_model_per_provider
from pi_mono.coding_agent.modes.interactive.interactive_mode import is_api_key_login_provider
from pi_mono.core.provider_display_names import BUILT_IN_PROVIDER_DISPLAY_NAMES


def test_perplexity_models_are_registered() -> None:
    assert "perplexity" in get_providers()
    models = get_models("perplexity")
    ids = {model["id"] for model in models}
    assert ids == {"sonar", "sonar-pro", "sonar-reasoning-pro", "sonar-deep-research"}

    sonar_pro = get_model("perplexity", "sonar-pro")
    assert sonar_pro is not None
    assert sonar_pro["api"] == "openai-completions"
    assert sonar_pro["baseUrl"] == "https://api.perplexity.ai"
    assert sonar_pro["provider"] == "perplexity"


def test_perplexity_api_key_auth_wiring() -> None:
    assert get_api_key_env_vars("perplexity") == ["PERPLEXITY_API_KEY"]
    assert BUILT_IN_PROVIDER_DISPLAY_NAMES["perplexity"] == "Perplexity"
    assert default_model_per_provider["perplexity"] == "sonar-pro"
    assert is_api_key_login_provider("perplexity", set())


def test_perplexity_env_api_key(monkeypatch) -> None:
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    assert get_env_api_key("perplexity") is None
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")
    assert get_env_api_key("perplexity") == "pplx-test-key"
