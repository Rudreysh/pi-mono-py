"""Simple Perplexity Pro client (subscription cookie, no official API key).

Use your browser `__Secure-next-auth.session-token` via env
`PERPLEXITY_SESSION_TOKEN` or by passing `session_token=...`.

Unofficial / personal use only. Prefer `pip install 'curl_cffi>=0.7'` if
Cloudflare blocks requests.
"""

from __future__ import annotations

import os
from typing import Any, AsyncIterator

from pi_mono.ai.perplexity_pro_models import PERPLEXITY_PRO_MODEL_PREFS, PERPLEXITY_PRO_MODELS
from pi_mono.ai.providers.perplexity_web import (
    _format_sources_footer,
    _iter_perplexity_chunks,
)
from pi_mono.ai.utils.oauth.perplexity_pro import (
    normalize_session_token,
    validate_perplexity_session_token,
)


def list_models() -> list[str]:
    """Return available Perplexity Pro model ids (e.g. sonnet, sonar, gpt)."""
    return list(PERPLEXITY_PRO_MODELS.keys())


def _resolve_token(session_token: str | None) -> str:
    raw = session_token or os.environ.get("PERPLEXITY_SESSION_TOKEN") or ""
    token = normalize_session_token(raw)
    if not token:
        raise ValueError(
            "Missing Perplexity Pro session token. Set PERPLEXITY_SESSION_TOKEN or pass "
            "session_token= (browser cookie __Secure-next-auth.session-token)."
        )
    return token


def _resolve_model(model: str) -> tuple[str, str]:
    prefs = PERPLEXITY_PRO_MODEL_PREFS.get(model)
    if prefs is None:
        known = ", ".join(list_models())
        raise ValueError(f"Unknown model {model!r}. Choose one of: {known}")
    return prefs


async def validate_session(session_token: str | None = None) -> dict[str, Any]:
    """Check that the session cookie is valid (and typically Pro)."""
    return await validate_perplexity_session_token(_resolve_token(session_token))


async def ask_stream(
    prompt: str,
    *,
    model: str = "sonnet",
    session_token: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Stream chunks from Perplexity Pro.

    Yields dicts with keys like:
      - delta: new answer text
      - thinking: search/plan step text
      - answer: full answer so far
      - web_results: citation list
      - done: True on final chunk
      - error / detail: on failure
    """
    token = _resolve_token(session_token)
    mode, model_pref = _resolve_model(model)
    query = (prompt or "").strip() or "Hello"
    async for chunk in _iter_perplexity_chunks(token, query, mode, model_pref):
        yield chunk


async def ask(
    prompt: str,
    *,
    model: str = "sonnet",
    session_token: str | None = None,
    include_sources: bool = True,
) -> dict[str, Any]:
    """Ask Perplexity Pro and return the full answer.

    Returns:
      {
        "text": str,
        "sources": list[dict],
        "model": str,
        "backend_uuid": str | None,
      }
    """
    answer = ""
    sources: list[Any] = []
    backend_uuid: str | None = None
    async for chunk in ask_stream(prompt, model=model, session_token=session_token):
        if chunk.get("error"):
            detail = chunk.get("detail") or chunk["error"]
            raise RuntimeError(
                f"Perplexity Pro request failed: {chunk['error']}. {detail}\n"
                "If HTTP 401/403: refresh your session cookie. "
                "If Cloudflare: pip install 'curl_cffi>=0.7'."
            )
        if chunk.get("answer"):
            answer = str(chunk["answer"])
        elif chunk.get("delta"):
            answer += str(chunk["delta"])
        if chunk.get("web_results"):
            sources = list(chunk["web_results"])
        if chunk.get("backend_uuid"):
            backend_uuid = str(chunk["backend_uuid"])

    text = answer
    if include_sources and sources:
        footer = _format_sources_footer(sources)
        if footer:
            text = text + footer

    return {
        "text": text,
        "sources": sources,
        "model": model,
        "backend_uuid": backend_uuid,
    }
