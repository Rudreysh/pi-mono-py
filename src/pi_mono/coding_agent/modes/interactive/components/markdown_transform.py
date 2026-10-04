"""Apply extension Markdown transformers before TUI rendering."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Literal

from pi_mono.coding_agent.core.extensions.types import MarkdownTransformContext, MarkdownTransformer

MarkdownMessageType = Literal["user", "assistant", "assistant-thinking"]


def apply_markdown_transformers(
    markdown: str,
    context: MarkdownTransformContext,
    transformers: Sequence[MarkdownTransformer],
) -> str:
    transformed = markdown
    for transformer in transformers:
        try:
            next_value = transformer(transformed, context)
            if isinstance(next_value, str):
                transformed = next_value
        except Exception:
            continue
    return transformed


def create_markdown_transform(
    message_type: MarkdownMessageType,
    is_streaming: bool,
    transformers: Sequence[MarkdownTransformer],
) -> Callable[[str, int], str]:
    def transform(markdown: str, available_width: int) -> str:
        return apply_markdown_transformers(
            markdown,
            {
                "messageType": message_type,
                "isStreaming": is_streaming,
                "availableWidth": available_width,
            },
            transformers,
        )

    return transform


def transform_markdown(
    markdown: str,
    *,
    message_type: MarkdownMessageType,
    is_streaming: bool = False,
    available_width: int = 80,
    transformers: Sequence[MarkdownTransformer] | None = None,
) -> str:
    if not transformers:
        return markdown
    return apply_markdown_transformers(
        markdown,
        {
            "messageType": message_type,
            "isStreaming": is_streaming,
            "availableWidth": available_width,
        },
        transformers,
    )


__all__ = [
    "apply_markdown_transformers",
    "create_markdown_transform",
    "transform_markdown",
]
