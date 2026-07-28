"""Evals package -- placeholder for the TS ``packages/evals`` vitest harness.

The TypeScript eval harness (vitest-based, under ``packages/evals``) has not
been ported to Python yet.  This module exports a stub ``EvalHarness`` class so
that downstream code can reference it without import errors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class EvalCase:
    """A single evaluation case."""

    name: str
    prompt: str
    expected: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalResult:
    """Result of running one evaluation case."""

    case: EvalCase
    passed: bool
    actual: str = ""
    error: str | None = None
    duration_ms: float = 0.0


class EvalHarness:
    """Placeholder eval harness.

    Mirrors the shape of the TS ``packages/evals`` vitest harness.  All
    methods raise ``NotImplementedError`` until a real implementation is
    ported.
    """

    def __init__(self, *, name: str = "default") -> None:
        self.name = name
        self._cases: list[EvalCase] = []

    def add_case(self, case: EvalCase) -> None:
        self._cases.append(case)

    @property
    def cases(self) -> list[EvalCase]:
        return list(self._cases)

    async def run(
        self,
        *,
        on_result: Callable[[EvalResult], None] | None = None,
    ) -> list[EvalResult]:
        raise NotImplementedError(
            "EvalHarness.run() is a placeholder; the TS vitest harness is not ported yet"
        )
