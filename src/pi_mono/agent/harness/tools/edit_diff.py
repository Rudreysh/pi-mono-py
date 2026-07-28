"""Shared diff computation utilities for harness edit tools.

Re-exports the coding-agent edit_diff module which contains all the core logic.
"""

from pi_mono.coding_agent.core.tools.edit_diff import (
    AppliedEditsResult,
    DisplayDiffResult,
    Edit,
    EditDiffResult,
    FuzzyMatchResult,
    LineSpan,
    MatchedEdit,
    TextReplacement,
    apply_edits_to_normalized_content,
    apply_replacements_preserving_unchanged_lines,
    detect_line_ending,
    fuzzy_find_text,
    generate_diff_string,
    generate_display_diff_string,
    generate_unified_patch,
    normalize_for_fuzzy_match,
    normalize_to_lf,
    restore_line_endings,
    strip_bom,
)

__all__ = [
    "AppliedEditsResult",
    "DisplayDiffResult",
    "Edit",
    "EditDiffResult",
    "FuzzyMatchResult",
    "LineSpan",
    "MatchedEdit",
    "TextReplacement",
    "apply_edits_to_normalized_content",
    "apply_replacements_preserving_unchanged_lines",
    "detect_line_ending",
    "fuzzy_find_text",
    "generate_diff_string",
    "generate_display_diff_string",
    "generate_unified_patch",
    "normalize_for_fuzzy_match",
    "normalize_to_lf",
    "restore_line_endings",
    "strip_bom",
]
