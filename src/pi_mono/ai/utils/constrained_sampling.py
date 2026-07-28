"""Constrained sampling helpers.

Port of packages/ai/src/api/constrained-sampling.ts essentials.
"""

from __future__ import annotations

from typing import Any, TypedDict


class GrammarConstrainedSampling(TypedDict):
    format: str  # "lark" | "regex"
    definition: str
    inputProperty: str


class GrammarToolInputJsonBuffer(TypedDict):
    input: str
    started: bool
    closed: bool


def get_grammar_tool_input(
    tool_name: str,
    arguments: dict[str, Any],
    input_property: str,
) -> str:
    value = arguments.get(input_property)
    if not isinstance(value, str):
        raise ValueError(
            f'Grammar tool call "{tool_name}" requires argument "{input_property}" to be a string.'
        )
    return value


def append_grammar_tool_input_json_delta(
    buffer: GrammarToolInputJsonBuffer,
    input_property: str,
    next_input: str,
    close: bool,
) -> str | None:
    import json

    if buffer["closed"]:
        if close and next_input == buffer["input"]:
            return None
        raise ValueError(
            f'grammar tool input for property "{input_property}" changed after it was closed'
        )
    if not next_input.startswith(buffer["input"]):
        raise ValueError(
            f'grammar tool input for property "{input_property}" changed non-monotonically'
        )
    input_delta = next_input[len(buffer["input"]) :]
    if not close and len(input_delta) == 0:
        return None

    delta = ""
    if not buffer["started"]:
        delta += "{" + json.dumps(input_property) + ':"'
        buffer["started"] = True
    encoded = json.dumps(input_delta)
    delta += encoded[1:-1]
    buffer["input"] = next_input

    if close:
        delta += '"}'
        buffer["closed"] = True
    return delta


def _infer_grammar_input_property(tool: dict[str, Any]) -> str:
    schema = tool.get("parameters", {})
    if schema.get("type") != "object":
        raise ValueError("grammar constrained sampling requires an object parameter schema")
    required = schema.get("required")
    if not isinstance(required, list) or len(required) != 1 or not isinstance(required[0], str):
        raise ValueError(
            "grammar constrained sampling requires exactly one required string property"
        )
    input_property = required[0]
    properties = schema.get("properties", {})
    prop = properties.get(input_property)
    if not prop:
        raise ValueError(
            f"grammar constrained sampling requires a properties entry for {input_property}"
        )
    if prop.get("type") != "string":
        raise ValueError(
            f"grammar constrained sampling property {input_property} must have type string"
        )
    return input_property


def supports_grammar_tools(model: dict[str, Any]) -> bool:
    """Return True if the model supports OpenAI grammar-constrained tool calling."""
    compat = model.get("compat", {})
    return bool(compat.get("supportsOpenAIGrammarTools"))


def supports_strict_tools(model: dict[str, Any]) -> bool:
    """Return True if the model supports strict JSON-schema tool calling."""
    compat = model.get("compat", {})
    api = model.get("api", "")
    if api == "anthropic-messages":
        return bool(compat.get("supportsStrictTools"))
    return bool(compat.get("supportsStrictMode"))


def resolve_json_schema_strict_sampling(
    tool: dict[str, Any],
    supports_strict_mode: bool,
) -> bool | None:
    config = tool.get("constrainedSampling")
    if not config or config.get("type") != "json_schema":
        return None
    if supports_strict_mode:
        return True
    if config.get("strict") == "require":
        raise ValueError(
            f'Tool "{tool.get("name")}" requires JSON-schema constrained sampling, '
            "but strict tools are unsupported."
        )
    return None


def resolve_grammar_constrained_sampling(
    tool: dict[str, Any],
    supports_openai_grammar_tools: bool,
) -> GrammarConstrainedSampling | None:
    config = tool.get("constrainedSampling")
    if not config or config.get("type") != "grammar":
        return None
    if not supports_openai_grammar_tools:
        return None
    variants = config.get("variants", {})
    lark_def = variants.get("openai_lark")
    regex_def = variants.get("openai_regex")
    has_lark = isinstance(lark_def, str) and lark_def.strip()
    has_regex = isinstance(regex_def, str) and regex_def.strip()
    if not has_lark and not has_regex:
        raise ValueError(
            f'Tool "{tool.get("name")}" cannot use grammar constrained sampling: '
            "no supported grammar variant was provided."
        )
    try:
        return {
            "format": "lark" if has_lark else "regex",
            "definition": lark_def if has_lark else regex_def,
            "inputProperty": _infer_grammar_input_property(tool),
        }
    except Exception as e:
        raise ValueError(
            f'Tool "{tool.get("name")}" cannot use grammar constrained sampling: {e}.'
        ) from e


def create_grammar_tool_input_properties(
    tools: list[dict[str, Any]] | None,
    supports_openai_grammar_tools: bool,
) -> dict[str, str]:
    properties: dict[str, str] = {}
    for tool in tools or []:
        grammar = resolve_grammar_constrained_sampling(tool, supports_openai_grammar_tools)
        if grammar:
            properties[tool["name"]] = grammar["inputProperty"]
    return properties
