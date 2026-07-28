"""Read tool for the agent harness."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Coroutine

from pi_mono.agent.harness.types import get_or_throw
from pi_mono.agent.harness.utils.truncate import DEFAULT_MAX_BYTES, DEFAULT_MAX_LINES, formatSize, truncateHead
from pi_mono.agent.types import AgentToolResult, AgentToolUpdateCallback
from pi_mono.utils.abort_signals import AbortSignal

from .image import detect_supported_image_mime_type, encode_base64
from .path_utils import resolve_read_tool_path
from .tool_context import ExecutionToolContext

READ_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Path to the file to read (relative or absolute)"},
        "offset": {"type": "number", "description": "Line number to start reading from (1-indexed)"},
        "limit": {"type": "number", "description": "Maximum number of lines to read"},
    },
    "required": ["path"],
}


@dataclass
class ReadToolDetails:
    truncation: dict[str, Any] | None = None


ReadImageProcessorResult = dict[str, Any]
ReadImageProcessor = Callable[[bytes, str, dict[str, Any]], Coroutine[Any, Any, ReadImageProcessorResult]]


@dataclass
class ReadToolOptions:
    auto_resize_images: bool = True
    image_processor: ReadImageProcessor | None = None


def create_read_tool(options: ReadToolOptions | None = None) -> Any:
    """Create a read tool that reads files via context.env."""
    opts = options or ReadToolOptions()

    class ReadTool:
        name = "read"
        label = "read"
        description = (
            f"Read the contents of a file. Supports text files and images "
            f"(jpg, png, gif, webp, bmp). Images are sent as attachments. "
            f"For text files, output is truncated to {DEFAULT_MAX_LINES} lines or "
            f"{DEFAULT_MAX_BYTES // 1024}KB (whichever is hit first). "
            f"Use offset/limit for large files. When you need the full file, "
            f"continue with offset until complete."
        )
        parameters = READ_PARAMETERS
        executionMode = None

        async def execute(
            self,
            tool_call_id: str,
            params: dict[str, Any],
            signal: AbortSignal | None = None,
            on_update: AgentToolUpdateCallback | None = None,
            context: ExecutionToolContext | None = None,
        ) -> AgentToolResult:
            if context is None:
                raise RuntimeError("ReadTool requires an ExecutionToolContext")
            env = context.env
            path = params["path"]
            offset = params.get("offset")
            limit = params.get("limit")

            absolute_path = await resolve_read_tool_path(env, path, signal)
            raw_bytes = get_or_throw(await env.readBinaryFile(absolute_path, signal))

            mime_type = detect_supported_image_mime_type(raw_bytes)
            if mime_type:
                return await _handle_image(raw_bytes, mime_type, opts)

            return _handle_text(raw_bytes, path, offset, limit)

    return ReadTool()


async def _handle_image(
    raw_bytes: bytes,
    mime_type: str,
    opts: ReadToolOptions,
) -> AgentToolResult:
    if opts.image_processor is not None:
        processed = await opts.image_processor(
            raw_bytes,
            mime_type,
            {"autoResizeImages": opts.auto_resize_images},
        )
        if not processed.get("ok", False):
            return {
                "content": [{"type": "text", "text": f"Read image file [{mime_type}]\n{processed.get('message', '')}"}],
                "details": None,
            }
        hints = processed.get("hints", [])
        hints_str = ("\n" + "\n".join(hints)) if hints else ""
        return {
            "content": [
                {"type": "text", "text": f"Read image file [{processed.get('mimeType', mime_type)}]{hints_str}"},
                {"type": "image", "data": processed["data"], "mimeType": processed.get("mimeType", mime_type)},
            ],
            "details": None,
        }

    if mime_type == "image/bmp":
        return {
            "content": [
                {
                    "type": "text",
                    "text": "Read image file [image/bmp]\n[Image omitted: configure an imageProcessor to convert BMP images.]",
                }
            ],
            "details": None,
        }

    return {
        "content": [
            {"type": "text", "text": f"Read image file [{mime_type}]"},
            {"type": "image", "data": encode_base64(raw_bytes), "mimeType": mime_type},
        ],
        "details": None,
    }


def _handle_text(
    raw_bytes: bytes,
    path: str,
    offset: int | None,
    limit: int | None,
) -> AgentToolResult:
    text_content = raw_bytes.decode("utf-8")
    all_lines = text_content.split("\n")
    total_file_lines = len(all_lines)
    start_line = max(0, (offset or 1) - 1)
    start_line_display = start_line + 1

    if start_line >= len(all_lines):
        raise ValueError(f"Offset {offset} is beyond end of file ({len(all_lines)} lines total)")

    user_limited_lines: int | None = None
    if limit is not None:
        end_line = min(start_line + limit, len(all_lines))
        selected_content = "\n".join(all_lines[start_line:end_line])
        user_limited_lines = end_line - start_line
    else:
        selected_content = "\n".join(all_lines[start_line:])

    truncation = truncateHead(selected_content)
    details: dict[str, Any] | None = None

    if truncation["firstLineExceedsLimit"]:
        first_line_size = formatSize(len(all_lines[start_line].encode("utf-8")))
        output_text = (
            f"[Line {start_line_display} is {first_line_size}, exceeds "
            f"{formatSize(DEFAULT_MAX_BYTES)} limit. Use bash: "
            f"sed -n '{start_line_display}p' {path} | head -c {DEFAULT_MAX_BYTES}]"
        )
        details = {"truncation": truncation}
    elif truncation["truncated"]:
        end_line_display = start_line_display + truncation["outputLines"] - 1
        next_offset = end_line_display + 1
        output_text = truncation["content"]
        if truncation["truncatedBy"] == "lines":
            output_text += (
                f"\n\n[Showing lines {start_line_display}-{end_line_display} of "
                f"{total_file_lines}. Use offset={next_offset} to continue.]"
            )
        else:
            output_text += (
                f"\n\n[Showing lines {start_line_display}-{end_line_display} of "
                f"{total_file_lines} ({formatSize(DEFAULT_MAX_BYTES)} limit). "
                f"Use offset={next_offset} to continue.]"
            )
        details = {"truncation": truncation}
    elif user_limited_lines is not None and start_line + user_limited_lines < len(all_lines):
        remaining = len(all_lines) - (start_line + user_limited_lines)
        next_offset = start_line + user_limited_lines + 1
        output_text = (
            f"{truncation['content']}\n\n[{remaining} more lines in file. "
            f"Use offset={next_offset} to continue.]"
        )
    else:
        output_text = truncation["content"]

    return {"content": [{"type": "text", "text": output_text}], "details": details}
