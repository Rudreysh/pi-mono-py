"""Fireworks provider.

Fireworks models use the Anthropic Messages and OpenAI Completions APIs.
Catalog entries already select the correct `api` per model; GLM models go
through anthropic-messages with Fireworks-specific compat flags.
"""

from __future__ import annotations

FIREWORKS_BASE_URL = "https://api.fireworks.ai/inference"
FIREWORKS_API_KEY_ENV = "FIREWORKS_API_KEY"
