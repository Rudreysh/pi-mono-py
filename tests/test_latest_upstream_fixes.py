"""Regression tests for independent fixes from the current TypeScript upstream."""

from __future__ import annotations

from typing import Any

import pytest

from pi_mono.agent.harness.tools.image import (
    detect_supported_image_mime_type as detect_harness_image_mime_type,
)
from pi_mono.ai.providers.openai_completions import convert_messages, detect_compat
from pi_mono.ai.types import Model
from pi_mono.utils.mime import detect_supported_image_mime_type


@pytest.mark.parametrize("signature", [b"GIF87a", b"GIF89a"])
def test_complete_gif_signatures_are_recognized_in_both_read_paths(signature: bytes) -> None:
    assert detect_supported_image_mime_type(signature) == "image/gif"
    assert detect_harness_image_mime_type(signature) == "image/gif"


def test_incomplete_gif_signature_is_not_an_image() -> None:
    assert detect_supported_image_mime_type(b"GIF a text file") is None
    assert detect_harness_image_mime_type(b"GIF a text file") is None


def test_openai_completions_omits_empty_user_text_with_an_image() -> None:
    model: Model = {
        "id": "test",
        "name": "test",
        "api": "openai-completions",
        "provider": "openai",
        "baseUrl": "https://example.invalid",
        "reasoning": False,
        "input": ["text", "image"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": 8192,
        "maxTokens": 2048,
    }
    context: dict[str, Any] = {
        "systemPrompt": "",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": ""},
                    {"type": "image", "data": "ZmFrZQ==", "mimeType": "image/png"},
                ],
                "timestamp": 0,
            }
        ],
        "tools": [],
    }

    assert convert_messages(model, context, detect_compat(model)) == [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,ZmFrZQ=="}}
            ],
        }
    ]
