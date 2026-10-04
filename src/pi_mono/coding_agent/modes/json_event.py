"""JSON/RPC wire shape for session events.

Public `message_update` events emit only usage + the assistant delta. The
interactive TUI still reads the internal cumulative `message` field.
"""

from __future__ import annotations

from typing import Any


def to_json_assistant_message_event(event: dict[str, Any] | None) -> dict[str, Any]:
    assistant_event = dict(event or {})
    if assistant_event.get("type") == "toolcall_start":
        partial = assistant_event.get("partial") or {}
        content = partial.get("content") or []
        content_index = assistant_event.get("contentIndex", 0)
        tool_call = content[content_index] if 0 <= content_index < len(content) else None
        assistant_event.pop("partial", None)
        if isinstance(tool_call, dict) and tool_call.get("type") == "toolCall":
            assistant_event["id"] = tool_call.get("id")
            assistant_event["toolName"] = tool_call.get("name")
        return assistant_event
    assistant_event.pop("partial", None)
    return assistant_event


def to_json_event(event: dict[str, Any]) -> dict[str, Any]:
    if event.get("type") != "message_update":
        return event
    message = event.get("message") or {}
    return {
        "type": "message_update",
        "usage": message.get("usage"),
        "assistantMessageEvent": to_json_assistant_message_event(
            event.get("assistantMessageEvent")
        ),
    }
