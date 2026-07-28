"""Filesystem and shell context required by the built-in execution tools."""

from __future__ import annotations

from dataclasses import dataclass

from pi_mono.agent.harness.types import ExecutionEnv


@dataclass
class ExecutionToolContext:
    """Context carrying the execution environment for harness tools."""

    env: ExecutionEnv
