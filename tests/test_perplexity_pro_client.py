"""Tests for the standalone Perplexity Pro client."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from pi_mono.ai.perplexity_pro_client import ask, list_models


def test_list_models_includes_sonnet() -> None:
    assert "sonnet" in list_models()
    assert "sonar" in list_models()


@pytest.mark.anyio
async def test_ask_returns_text_and_sources() -> None:
    async def fake_stream(*_args, **_kwargs):
        yield {
            "delta": "ADHD is clinical.",
            "answer": "ADHD is clinical.",
            "web_results": [{"name": "DSM", "url": "https://example.com/dsm"}],
            "done": False,
        }
        yield {
            "delta": "",
            "answer": "ADHD is clinical.",
            "web_results": [{"name": "DSM", "url": "https://example.com/dsm"}],
            "done": True,
        }

    with patch("pi_mono.ai.perplexity_pro_client._iter_perplexity_chunks", fake_stream):
        result = await ask("how is ADHD diagnosed?", session_token="tok")
    assert "ADHD is clinical." in result["text"]
    assert "https://example.com/dsm" in result["text"]
    assert result["sources"][0]["url"] == "https://example.com/dsm"
