"""Edit tool for the agent harness."""

from __future__ import annotations

import json
from typing import Any

from pi_mono.agent.harness.types import FileError
from pi_mono.agent.types import AgentToolResult, AgentToolUpdateCallback
from pi_mono.utils.abort_signals import AbortSignal

from .edit_diff import (
    apply_edits_to_normalized_content,
    detect_line_ending,
    generate_diff_string,
    generate_unified_patch,
    normalize_to_lf,
    restore_line_endings,
    strip_bom,
)
from .file_mutation_queue import with_file_mutation_queue
from .path_utils import resolve_tool_path
from .tool_context import ExecutionToolContext

EDIT_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Path to the file to edit (relative or absolute)"},
        "edits": {
            "type": "array",
            "description": (
                "One or more targeted replacements. Each edit is matched against the original file, "
                "not incrementally. Do not include overlapping or nested edits."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "oldText": {
                        "type": "string",
                        "description": "Exact text for one targeted replacement. Must be unique in the original file.",
                    },
                    "newText": {"type": "string", "description": "Replacement text for this targeted edit."},
                },
                "required": ["oldText", "newText"],
            },
        },
    },
    "required": ["path", "edits"],
}


def _prepare_edit_arguments(params: dict[str, Any]) -> dict[str, Any]:
    edits = params.get("edits")
    if isinstance(edits, str):
        try:
            parsed = json.loads(edits)
            if isinstance(parsed, list):
                params = {**params, "edits": parsed}
        except json.JSONDecodeError:
            pass
    if "oldText" in params and "newText" in params:
        legacy_edits = list(params.get("edits") or [])
        legacy_edits.append({"oldText": params["oldText"], "newText": params["newText"]})
        params = {k: v for k, v in params.items() if k not in ("oldText", "newText")}
        params["edits"] = legacy_edits
    return params


def _edit_access_error(path: str, error: FileError) -> RuntimeError:
    return RuntimeError(f"Could not edit file: {path}. Error code: {error.code}.")


def create_edit_tool() -> Any:
    """Create an edit tool that modifies files via context.env."""

    class EditTool:
        name = "edit"
        label = "edit"
        description = (
            "Edit a single file using exact text replacement. Every edits[].oldText must match "
            "a unique, non-overlapping region of the original file. If two changes affect the same "
            "block or nearby lines, merge them into one edit instead of emitting overlapping edits."
        )
        parameters = EDIT_PARAMETERS
        executionMode = None
        prepareArguments = staticmethod(_prepare_edit_arguments)

        async def execute(
            self,
            tool_call_id: str,
            params: dict[str, Any],
            signal: AbortSignal | None = None,
            on_update: AgentToolUpdateCallback | None = None,
            context: ExecutionToolContext | None = None,
        ) -> AgentToolResult:
            if context is None:
                raise RuntimeError("EditTool requires an ExecutionToolContext")
            env = context.env
            prepared = _prepare_edit_arguments(params)
            path = prepared["path"]
            edits = prepared.get("edits")
            if not isinstance(edits, list) or not edits:
                raise ValueError("Edit tool input is invalid. edits must contain at least one replacement.")

            absolute_path = await resolve_tool_path(env, path, signal)

            async def run() -> AgentToolResult:
                if signal is not None and getattr(signal, "aborted", False):
                    raise RuntimeError("Operation aborted")

                info = await env.fileInfo(absolute_path, signal)
                if not info.ok:
                    raise _edit_access_error(path, info.error)
                if info.value.kind not in ("file", "symlink"):
                    raise RuntimeError(f"Could not edit file: {path}. Path is not a file.")

                read_result = await env.readTextFile(absolute_path, signal)
                if not read_result.ok:
                    raise _edit_access_error(path, read_result.error)
                if signal is not None and getattr(signal, "aborted", False):
                    raise RuntimeError("Operation aborted")

                raw_content = read_result.value
                bom = ""
                content = raw_content
                if content.startswith("\ufeff"):
                    bom = "\ufeff"
                    content = content[1:]

                original_ending = detect_line_ending(content)
                normalized_content = normalize_to_lf(content)
                applied = apply_edits_to_normalized_content(normalized_content, edits, path)
                if signal is not None and getattr(signal, "aborted", False):
                    raise RuntimeError("Operation aborted")

                final_content = bom + restore_line_endings(applied.new_content, original_ending)
                write_result = await env.writeFile(absolute_path, final_content, signal)
                if not write_result.ok:
                    raise _edit_access_error(path, write_result.error)
                if signal is not None and getattr(signal, "aborted", False):
                    raise RuntimeError("Operation aborted")

                diff_result = generate_diff_string(applied.base_content, applied.new_content)
                patch = generate_unified_patch(path, applied.base_content, applied.new_content)
                return {
                    "content": [{"type": "text", "text": f"Successfully replaced {len(edits)} block(s) in {path}."}],
                    "details": {
                        "diff": diff_result.diff,
                        "patch": patch,
                        "firstChangedLine": diff_result.first_changed_line,
                    },
                }

            return await with_file_mutation_queue(env, absolute_path, run)

    return EditTool()
