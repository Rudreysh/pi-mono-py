"""Perplexity Pro subscription models (web backend, not official API)."""

from __future__ import annotations

from typing import Any

from pi_mono.ai.types import Model

PERPLEXITY_PRO_BASE_URL = "https://www.perplexity.ai"
PERPLEXITY_PRO_API = "perplexity-web"

# Stable pi model ids → (web mode, model_preference)
# mode "pro" → Perplexity "copilot"; mode "auto" → Perplexity "concise".
PERPLEXITY_PRO_MODEL_PREFS: dict[str, tuple[str, str]] = {
    "auto": ("auto", "pplx_pro"),
    "sonar": ("pro", "experimental"),
    "gpt": ("pro", "gpt55"),
    "gpt-5.4": ("pro", "gpt54"),
    "gpt-mini": ("pro", "gpt5_mini"),
    "sonnet": ("pro", "claude46sonnet"),
    "gemini": ("pro", "gemini31pro_high"),
    "gemini-flash": ("pro", "gemini35flash"),
    "grok": ("pro", "grok4"),
    "grok-reasoning": ("pro", "grok420reasoning"),
    "nemotron": ("pro", "nv_nemotron_3_super"),
}

# reasoning=False: web backend has no thinking-level controls (search steps still stream as thinking).
_MODEL_META: dict[str, dict[str, Any]] = {
    "auto": {"name": "Perplexity Best", "reasoning": False},
    "sonar": {"name": "Sonar", "reasoning": False},
    "gpt": {"name": "GPT-5.5", "reasoning": False},
    "gpt-5.4": {"name": "GPT-5.4", "reasoning": False},
    "gpt-mini": {"name": "GPT-5 Mini", "reasoning": False},
    "sonnet": {"name": "Claude Sonnet 4.6", "reasoning": False},
    "gemini": {"name": "Gemini 3.1 Pro", "reasoning": False},
    "gemini-flash": {"name": "Gemini 3.5 Flash", "reasoning": False},
    "grok": {"name": "Grok 4", "reasoning": False},
    "grok-reasoning": {"name": "Grok 4.20 Reasoning", "reasoning": False},
    "nemotron": {"name": "Nemotron 3 Super", "reasoning": False},
}


def _build_model(model_id: str) -> Model:
    meta = _MODEL_META[model_id]
    return {
        "id": model_id,
        "name": meta["name"],
        "api": PERPLEXITY_PRO_API,
        "provider": "perplexity-pro",
        "baseUrl": PERPLEXITY_PRO_BASE_URL,
        "reasoning": bool(meta["reasoning"]),
        "input": ["text"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": 128000,
        "maxTokens": 16000,
    }


PERPLEXITY_PRO_MODELS: dict[str, Model] = {
    model_id: _build_model(model_id) for model_id in PERPLEXITY_PRO_MODEL_PREFS
}
