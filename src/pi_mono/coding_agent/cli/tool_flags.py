"""Tool allowlists, denylists, and +name/-name modifiers.

Port of the helpers in packages/coding-agent/src/core/settings-manager.ts and
packages/coding-agent/src/core/mcp-servers.ts.
"""

from __future__ import annotations

import re

DEFAULT_TOOL_NAMES: tuple[str, ...] = ("read", "bash", "edit", "write")

MCP_RESOURCE_TOOLS: frozenset[str] = frozenset(
    {
        "list_mcp_resources",
        "list_mcp_resource_templates",
        "read_mcp_resource",
    }
)


def is_tool_modifier(entry: object) -> bool:
    return isinstance(entry, str) and (entry.startswith("+") or entry.startswith("-"))


def get_tool_list_error(entries: list[str]) -> str | None:
    """A tools list is an allowlist, or only +name/-name entries. Not both."""
    modifiers = [entry for entry in entries if is_tool_modifier(entry)]
    if not modifiers:
        return None
    if len(modifiers) < len(entries):
        return "tool names cannot be mixed with +name or -name entries"
    pattern = next((entry for entry in modifiers if "*" in entry), None)
    if pattern:
        return f"+name and -name entries take exact tool names, not patterns: {pattern}"
    return None


def apply_tool_modifiers(base: list[str], entries: list[str]) -> list[str]:
    """Apply +name and -name in order. Other entries are ignored."""
    tools = list(base)
    for entry in entries:
        if not is_tool_modifier(entry):
            continue
        name = entry[1:]
        try:
            index = tools.index(name)
        except ValueError:
            index = -1
        if entry.startswith("+") and index == -1 and name:
            tools.append(name)
        elif entry.startswith("-") and index != -1:
            del tools[index]
    return tools


def tool_pattern_regexp(pattern: str) -> re.Pattern[str]:
    source = ".*".join(re.escape(part) for part in pattern.split("*"))
    return re.compile(f"^{source}$")


def create_tool_name_matcher(entries: list[str]):
    names = {entry for entry in entries if "*" not in entry}
    patterns = [tool_pattern_regexp(entry) for entry in entries if "*" in entry]

    def matches(name: str) -> bool:
        return name in names or any(pattern.search(name) for pattern in patterns)

    return matches


def is_mcp_tool_name(name: str) -> bool:
    return name.startswith("mcp__") or name in MCP_RESOURCE_TOOLS


def allowlist_filters_mcp(entries: list[str]) -> bool:
    """An empty allowlist, or one that names an MCP tool, filters MCP tools."""
    return len(entries) == 0 or any(entry.startswith("mcp__") for entry in entries)
