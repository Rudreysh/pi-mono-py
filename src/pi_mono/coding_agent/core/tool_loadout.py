"""Apply prepareLoadout hooks before a request sees the tool list."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def apply_prepare_loadout(
    tools: list[Any],
    definitions: dict[str, Any],
    guidelines: dict[str, list[str]],
    *,
    registered: list[Any] | None = None,
    on_error: Callable[[str, BaseException], None] | None = None,
) -> tuple[list[Any], set[str]]:
    """Hide declarations and replace descriptions the way TypeScript does.

    Hidden tools stay in the returned list so they can still be called. They are
    marked ``hidden_declaration`` and left out of the model request and prompt.
    """
    hooks = [
        definitions[tool.name]
        for tool in tools
        if getattr(definitions.get(tool.name), "prepare_loadout", None)
    ]
    hidden: set[str] = set()
    descriptions: dict[str, str] = {}
    if hooks:
        loadout = {
            "declared": list(tools),
            "callable": list(registered if registered is not None else tools),
            "registered": list(registered if registered is not None else tools),
            "get_exposure": lambda _name: "direct",
            "get_namespace": lambda _name: None,
            "get_prompt_guidelines": lambda name: list(guidelines.get(name, [])),
        }
        for definition in hooks:
            try:
                changes = definition.prepare_loadout(loadout) or {}
            except Exception as error:
                if on_error is not None:
                    on_error(definition.name, error)
                continue
            if not isinstance(changes, dict):
                continue
            for name, description in (changes.get("descriptions") or {}).items():
                descriptions[str(name)] = str(description)
            hidden_names = changes.get("hidden_declarations")
            if hidden_names is None:
                hidden_names = changes.get("hiddenDeclarations") or []
            for name in hidden_names:
                hidden.add(str(name))

    for tool in tools:
        description = descriptions.get(tool.name)
        if description is not None:
            tool.description = description
        tool.hidden_declaration = tool.name in hidden
    return tools, hidden
