"""Python eval harness.

Runs named cases against a provided completion callback. This is the Python
equivalent of the TypeScript vitest eval suite's case runner, not a port of
the vitest plugin itself.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvalCase:
    name: str
    prompt: str
    expected: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalResult:
    case: EvalCase
    passed: bool
    actual: str = ""
    error: str | None = None
    duration_ms: float = 0.0


CompleteFn = Callable[[EvalCase], Awaitable[str] | str]


class EvalHarness:
    def __init__(self, complete: CompleteFn | None = None, *, name: str = "evals") -> None:
        self.name = name
        self._complete = complete
        self.cases: list[EvalCase] = []

    def add_case(self, case: EvalCase) -> None:
        self.cases.append(case)

    async def run(self, complete: CompleteFn | None = None) -> list[EvalResult]:
        runner = complete or self._complete
        if runner is None:
            raise ValueError("EvalHarness.run requires a complete callback")
        results: list[EvalResult] = []
        for case in self.cases:
            started = time.perf_counter()
            try:
                actual_value = runner(case)
                if isinstance(actual_value, Awaitable):
                    actual_value = await actual_value
                actual = str(actual_value)
                passed = case.expected is None or case.expected in actual
                results.append(
                    EvalResult(
                        case=case,
                        passed=passed,
                        actual=actual,
                        duration_ms=(time.perf_counter() - started) * 1000,
                    )
                )
            except Exception as error:
                results.append(
                    EvalResult(
                        case=case,
                        passed=False,
                        error=str(error),
                        duration_ms=(time.perf_counter() - started) * 1000,
                    )
                )
        return results
