"""Perplexity Pro web SSE provider (subscription session cookie).

Talks to Perplexity's browser endpoint `/rest/sse/perplexity_ask` using the
session token from `/login` → Perplexity Pro.

This is unofficial and can break when Perplexity changes their web API.
Prefer the official `perplexity` API-key provider when possible.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator
from uuid import uuid4

import httpx

from pi_mono.ai.perplexity_pro_models import PERPLEXITY_PRO_MODEL_PREFS
from pi_mono.ai.types import (
    AssistantMessage,
    Context,
    Model,
    SimpleStreamOptions,
    StreamOptions,
    TextContent,
    ThinkingContent,
)
from pi_mono.ai.utils.oauth.perplexity_pro import normalize_session_token
from pi_mono.utils.event_stream import AssistantMessageEventStream

PPLX_SSE_ASK = "https://www.perplexity.ai/rest/sse/perplexity_ask"
PPLX_API_VERSION = "2.18"
SESSION_COOKIE_NAME = "__Secure-next-auth.session-token"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


@dataclass
class _StreamState:
    full_answer: str = ""
    seen_len: int = 0
    seen_thinking: set[str] = field(default_factory=set)
    web_results: list[Any] = field(default_factory=list)
    backend_uuid: str | None = None


def _default_headers(session_token: str) -> dict[str, str]:
    return {
        "Accept": "text/event-stream",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
        "Origin": "https://www.perplexity.ai",
        "Referer": "https://www.perplexity.ai/",
        "User-Agent": USER_AGENT,
        "Cookie": f"{SESSION_COOKIE_NAME}={session_token}",
        "sec-ch-ua": '"Chromium";v="130", "Not?A_Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
    }


def _is_aborted(options: StreamOptions | None) -> bool:
    if not options:
        return False
    signal = options.get("signal") if isinstance(options, dict) else None
    return bool(isinstance(signal, dict) and signal.get("aborted"))


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    texts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and block.get("text"):
            texts.append(str(block["text"]))
        elif block.get("type") == "toolResult":
            texts.append(str(block.get("content") or block.get("text") or ""))
    return "\n".join(t for t in texts if t).strip()


def _messages_to_query(context: Context) -> str:
    """Build Perplexity query_str from the latest user-typed prompt only.

    When provider is perplexity-pro, never send:
    - pi system / coding-agent instructions
    - prior user turns
    - prior assistant answers
    - tool results

    Only the most recent user message text goes to Perplexity.
    """
    messages = list(context.get("messages") or [])
    latest = ""
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        text = _message_text(message)
        if text:
            latest = text
    return latest or "Hello"


def _build_payload(query: str, mode: str, model_pref: str) -> dict[str, Any]:
    pplx_mode = "concise" if mode == "auto" else "copilot"
    return {
        "query_str": query,
        "params": {
            "attachments": [],
            "frontend_context_uuid": str(uuid4()),
            "frontend_uuid": str(uuid4()),
            "is_incognito": False,
            "language": "en-US",
            "last_backend_uuid": None,
            "mode": pplx_mode,
            "model_preference": model_pref,
            "source": "default",
            "sources": ["web"],
            "search_focus": "internet",
            "search_recency_filter": None,
            "timezone": "UTC",
            "visitor_id": str(uuid4()),
            "user_nextauth_id": str(uuid4()),
            "prompt_source": "user",
            "query_source": "home",
            "browser_history_summary": [],
            "is_related_query": False,
            "is_sponsored": False,
            "is_nav_suggestions_disabled": False,
            "use_schematized_api": True,
            "send_back_text_in_streaming_api": False,
            "supported_block_use_cases": [
                "answer_modes",
                "media_items",
                "knowledge_cards",
                "inline_entity_cards",
                "place_widgets",
                "finance_widgets",
                "sports_widgets",
                "shopping_widgets",
                "search_result_widgets",
            ],
            "client_coordinates": None,
            "version": PPLX_API_VERSION,
        },
    }


def _parse_sse_message(raw: str) -> dict[str, Any] | None:
    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    event_type: str | None = None
    data_parts: list[str] = []
    for line in lines:
        if line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data_parts.append(line[5:].lstrip())
    if event_type != "message" or not data_parts:
        return None
    data_str = "\n".join(data_parts).strip()
    try:
        parsed = json.loads(data_str)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _result_url(result: Any) -> str:
    if isinstance(result, dict):
        return str(result.get("url") or result.get("link") or "").strip()
    return str(result or "").strip()


def _result_title(result: Any) -> str:
    if isinstance(result, dict):
        return str(result.get("name") or result.get("title") or result.get("snippet") or "").strip()
    return ""


def _merge_web_results(existing: list[Any], incoming: list[Any]) -> list[Any]:
    """Append unique web results by URL (citation index order preserved)."""
    seen = {_result_url(item) for item in existing if _result_url(item)}
    merged = list(existing)
    for item in incoming:
        url = _result_url(item)
        if not url or url in seen:
            continue
        seen.add(url)
        merged.append(item)
    return merged


def _collect_web_results_from_chunk(chunk: dict[str, Any]) -> list[Any]:
    found: list[Any] = []
    top = chunk.get("web_results")
    if isinstance(top, list):
        found = _merge_web_results(found, top)
    for block in chunk.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        usage = str(block.get("intended_usage") or "")
        web_block = block.get("web_result_block")
        if isinstance(web_block, dict):
            nested = web_block.get("web_results")
            if isinstance(nested, list):
                found = _merge_web_results(found, nested)
        # Some payloads put results directly on the block.
        if usage in ("web_results", "web_result") and isinstance(block.get("web_results"), list):
            found = _merge_web_results(found, block["web_results"])
    return found


def _format_sources_footer(web_results: list[Any], limit: int = 12) -> str:
    lines: list[str] = []
    for index, result in enumerate(web_results[:limit]):
        url = _result_url(result)
        if not url:
            continue
        title = _result_title(result)
        if title and title != url:
            lines.append(f"[{index + 1}] {title}\n    {url}")
        else:
            lines.append(f"[{index + 1}] {url}")
    if not lines:
        return ""
    return "\n\n---\nSources:\n" + "\n".join(lines) + "\n"


def _emit_answer_delta(
    state: _StreamState,
    text: str,
    *,
    replace: bool,
) -> dict[str, Any] | None:
    """Update answer state and return a delta item when new text is available."""
    if not text:
        return None

    cumulative = text if replace else (state.full_answer + text)

    if replace and state.seen_len > 0:
        prefix = state.full_answer[: state.seen_len]
        if not cumulative.startswith(prefix):
            # Authoritative final text diverged from what we already streamed.
            # Keep streamed output; store final for the done/fallback path.
            state.full_answer = cumulative
            return None

    if len(cumulative) <= state.seen_len:
        state.full_answer = cumulative
        return None

    delta = cumulative[state.seen_len :]
    state.full_answer = cumulative
    state.seen_len = len(cumulative)
    return {
        "delta": delta,
        "answer": cumulative,
        "backend_uuid": state.backend_uuid,
        "web_results": state.web_results,
        "done": False,
    }


def _extract_stream_items(chunk: dict[str, Any], state: _StreamState) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if "backend_uuid" in chunk:
        state.backend_uuid = str(chunk["backend_uuid"])

    collected = _collect_web_results_from_chunk(chunk)
    if collected:
        state.web_results = _merge_web_results(state.web_results, collected)

    for block in chunk.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        usage = str(block.get("intended_usage") or "")

        if usage == "pro_search_steps":
            plan = block.get("plan_block") or {}
            for step in plan.get("steps") or []:
                step_type = step.get("step_type")
                if step_type == "SEARCH_WEB":
                    queries = [
                        q.get("query", "")
                        for q in (step.get("search_web_content") or {}).get("queries", [])
                    ]
                    for query in queries:
                        if query and query not in state.seen_thinking:
                            state.seen_thinking.add(query)
                            items.append({"thinking": f"Searching: {query}", "done": False})
                elif step_type == "READ_RESULTS":
                    urls = [
                        u for u in (step.get("read_results_content") or {}).get("urls", []) if u
                    ]
                    for url in urls[:3]:
                        if url not in state.seen_thinking:
                            state.seen_thinking.add(url)
                            items.append({"thinking": f"Reading: {url}", "done": False})

        if usage == "plan":
            plan = block.get("plan_block") or {}
            for goal in plan.get("goals") or []:
                desc = goal.get("description", "")
                if desc and desc not in state.seen_thinking:
                    state.seen_thinking.add(desc)
                    items.append({"thinking": desc, "done": False})

        if "markdown" not in usage:
            continue
        markdown = block.get("markdown_block") or {}
        chunks = markdown.get("chunks") or []
        if not chunks:
            continue
        chunk_text = "".join(str(c) for c in chunks)
        progress = markdown.get("progress", "")
        # DONE = authoritative full answer; PROCESSING = incremental piece.
        item = _emit_answer_delta(state, chunk_text, replace=(progress == "DONE"))
        if item is not None:
            items.append(item)
    return items


def _consume_sse_buffer(
    buffer: str,
    state: _StreamState,
) -> tuple[str, list[dict[str, Any]], bool]:
    """Split SSE events from a text buffer. Returns (remainder, items, ended)."""
    items: list[dict[str, Any]] = []
    ended = False
    while True:
        if "\r\n\r\n" in buffer:
            raw, buffer = buffer.split("\r\n\r\n", 1)
        elif "\n\n" in buffer:
            raw, buffer = buffer.split("\n\n", 1)
        else:
            break
        stripped = raw.lstrip("\r\n")
        if stripped.startswith("event: end_of_stream"):
            ended = True
            break
        message = _parse_sse_message(raw)
        if message is None:
            continue
        items.extend(_extract_stream_items(message, state))
    return buffer, items, ended


def _flush_sse_buffer(buffer: str, state: _StreamState) -> list[dict[str, Any]]:
    """Parse any trailing SSE event that arrived without a final blank line."""
    if not buffer.strip():
        return []
    message = _parse_sse_message(buffer)
    if message is None:
        return []
    return _extract_stream_items(message, state)


async def _iter_perplexity_chunks(
    session_token: str,
    query: str,
    mode: str,
    model_pref: str,
) -> AsyncIterator[dict[str, Any]]:
    payload = _build_payload(query, mode, model_pref)
    headers = _default_headers(session_token)
    state = _StreamState()

    try:
        from curl_cffi.requests import AsyncSession  # type: ignore[import-untyped]

        use_curl = True
    except ImportError:
        use_curl = False

    if use_curl:
        from curl_cffi.requests import AsyncSession  # type: ignore[import-untyped]

        async with AsyncSession(impersonate="chrome", timeout=120) as session:
            async with session.stream(
                "POST", PPLX_SSE_ASK, headers=headers, json=payload
            ) as response:
                if response.status_code != 200:
                    body = ""
                    try:
                        body = (await response.atext())[:400]
                    except Exception:
                        try:
                            chunks: list[bytes] = []
                            async for piece in response.aiter_content():
                                chunks.append(piece if isinstance(piece, bytes) else bytes(piece))
                                if sum(len(c) for c in chunks) > 400:
                                    break
                            body = b"".join(chunks)[:400].decode("utf-8", errors="replace")
                        except Exception:
                            body = str(response.status_code)
                    yield {"error": f"HTTP {response.status_code}", "detail": body}
                    return

                buffer = ""
                async for piece in response.aiter_content():
                    if isinstance(piece, bytes):
                        buffer += piece.decode("utf-8", errors="replace")
                    else:
                        buffer += str(piece)
                    buffer, items, ended = _consume_sse_buffer(buffer, state)
                    for item in items:
                        yield item
                    if ended:
                        buffer = ""
                        break
                for item in _flush_sse_buffer(buffer, state):
                    yield item
        yield {
            "delta": "",
            "answer": state.full_answer,
            "backend_uuid": state.backend_uuid,
            "web_results": state.web_results,
            "done": True,
        }
        return

    async with httpx.AsyncClient(timeout=None, follow_redirects=True) as client:
        async with client.stream("POST", PPLX_SSE_ASK, headers=headers, json=payload) as response:
            if response.status_code != 200:
                body = (await response.aread())[:400].decode("utf-8", errors="replace")
                yield {"error": f"HTTP {response.status_code}", "detail": body}
                return

            buffer = ""
            async for piece in response.aiter_text():
                buffer += piece
                buffer, items, ended = _consume_sse_buffer(buffer, state)
                for item in items:
                    yield item
                if ended:
                    buffer = ""
                    break
            for item in _flush_sse_buffer(buffer, state):
                yield item

    yield {
        "delta": "",
        "answer": state.full_answer,
        "backend_uuid": state.backend_uuid,
        "web_results": state.web_results,
        "done": True,
    }


def stream_perplexity_web(
    model: Model,
    context: Context,
    options: StreamOptions | None = None,
) -> AssistantMessageEventStream:
    event_stream = AssistantMessageEventStream()

    async def run() -> None:
        output: AssistantMessage = {
            "role": "assistant",
            "content": [],
            "api": model.get("api", "perplexity-web"),
            "provider": model.get("provider", "perplexity-pro"),
            "model": model["id"],
            "usage": {
                "input": 0,
                "output": 0,
                "cacheRead": 0,
                "cacheWrite": 0,
                "totalTokens": 0,
                "cost": {
                    "input": 0.0,
                    "output": 0.0,
                    "cacheRead": 0.0,
                    "cacheWrite": 0.0,
                    "total": 0.0,
                },
            },
            "stopReason": "stop",
            "timestamp": int(time.time() * 1000),
        }

        try:
            if _is_aborted(options):
                raise RuntimeError("Request was aborted")

            options_dict = dict(options or {})
            session_token = normalize_session_token(str(options_dict.get("apiKey") or ""))
            if not session_token:
                raise ValueError(
                    "No Perplexity Pro session token. Use /login → Use a subscription → "
                    "Perplexity Pro and paste your browser session cookie."
                )

            prefs = PERPLEXITY_PRO_MODEL_PREFS.get(model["id"])
            if prefs is None:
                raise ValueError(f"Unknown Perplexity Pro model: {model['id']}")
            mode, model_pref = prefs
            query = _messages_to_query(context)

            event_stream.push({"type": "start", "partial": output})

            text_block: TextContent | None = None
            thinking_block: ThinkingContent | None = None
            full_answer = ""
            web_results: list[Any] = []

            async for chunk in _iter_perplexity_chunks(session_token, query, mode, model_pref):
                if _is_aborted(options):
                    raise RuntimeError("Request was aborted")

                if chunk.get("error"):
                    detail = chunk.get("detail") or chunk["error"]
                    raise RuntimeError(
                        f"Perplexity Pro request failed: {chunk['error']}. {detail}\n"
                        "If this is HTTP 401/403, re-run /login and paste a fresh session cookie. "
                        "If blocked by Cloudflare, install: pip install 'curl_cffi>=0.7' "
                        "(or pip install '.[perplexity-pro]')."
                    )

                thinking = chunk.get("thinking")
                if isinstance(thinking, str) and thinking:
                    if thinking_block is None:
                        thinking_block = {"type": "thinking", "thinking": ""}
                        output["content"].append(thinking_block)
                        event_stream.push(
                            {
                                "type": "thinking_start",
                                "contentIndex": len(output["content"]) - 1,
                                "partial": output,
                            }
                        )
                    thinking_block["thinking"] += thinking + "\n"
                    event_stream.push(
                        {
                            "type": "thinking_delta",
                            "contentIndex": len(output["content"]) - 1,
                            "delta": thinking + "\n",
                            "partial": output,
                        }
                    )
                    continue

                delta = chunk.get("delta")
                if isinstance(delta, str) and delta:
                    if text_block is None:
                        text_block = {"type": "text", "text": ""}
                        output["content"].append(text_block)
                        event_stream.push(
                            {
                                "type": "text_start",
                                "contentIndex": len(output["content"]) - 1,
                                "partial": output,
                            }
                        )
                    text_block["text"] += delta
                    full_answer = str(chunk.get("answer") or full_answer)
                    event_stream.push(
                        {
                            "type": "text_delta",
                            "contentIndex": len(output["content"]) - 1,
                            "delta": delta,
                            "partial": output,
                        }
                    )

                if chunk.get("web_results"):
                    web_results = list(chunk["web_results"])

                if chunk.get("done"):
                    answer = chunk.get("answer")
                    if isinstance(answer, str) and answer.strip():
                        full_answer = answer
                        if text_block is None:
                            text_block = {"type": "text", "text": answer}
                            output["content"].append(text_block)
                            event_stream.push(
                                {
                                    "type": "text_start",
                                    "contentIndex": len(output["content"]) - 1,
                                    "partial": output,
                                }
                            )
                            event_stream.push(
                                {
                                    "type": "text_delta",
                                    "contentIndex": len(output["content"]) - 1,
                                    "delta": answer,
                                    "partial": output,
                                }
                            )
                        elif not text_block["text"].strip():
                            text_block["text"] = answer
                            event_stream.push(
                                {
                                    "type": "text_delta",
                                    "contentIndex": len(output["content"]) - 1,
                                    "delta": answer,
                                    "partial": output,
                                }
                            )
                    break

            if web_results:
                cites = _format_sources_footer(web_results)
                if cites:
                    if text_block is None:
                        text_block = {"type": "text", "text": ""}
                        output["content"].append(text_block)
                        event_stream.push(
                            {
                                "type": "text_start",
                                "contentIndex": len(output["content"]) - 1,
                                "partial": output,
                            }
                        )
                    text_block["text"] += cites
                    event_stream.push(
                        {
                            "type": "text_delta",
                            "contentIndex": len(output["content"]) - 1,
                            "delta": cites,
                            "partial": output,
                        }
                    )

            if thinking_block is not None:
                event_stream.push(
                    {
                        "type": "thinking_end",
                        "contentIndex": output["content"].index(thinking_block),
                        "content": thinking_block["thinking"],
                        "partial": output,
                    }
                )
            if text_block is not None:
                event_stream.push(
                    {
                        "type": "text_end",
                        "contentIndex": output["content"].index(text_block),
                        "content": text_block["text"],
                        "partial": output,
                    }
                )

            if not output["content"]:
                output["content"].append(
                    {
                        "type": "text",
                        "text": full_answer or "(no response from Perplexity Pro)",
                    }
                )

            if _is_aborted(options):
                raise RuntimeError("Request was aborted")

            output["stopReason"] = "stop"
            event_stream.push({"type": "done", "message": output, "reason": "stop"})
        except Exception as error:
            aborted = str(error) == "Request was aborted" or _is_aborted(options)
            output["stopReason"] = "aborted" if aborted else "error"
            output["errorMessage"] = str(error)
            event_stream.push(
                {
                    "type": "error",
                    "reason": "aborted" if aborted else "error",
                    "error": output,
                }
            )

    asyncio.create_task(run())
    return event_stream


def stream_simple_perplexity_web(
    model: Model,
    context: Context,
    options: SimpleStreamOptions | None = None,
) -> AssistantMessageEventStream:
    return stream_perplexity_web(model, context, options)
