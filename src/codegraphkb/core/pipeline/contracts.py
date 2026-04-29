"""Deterministic pipeline phase contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class PhaseResult:
    name: str
    output: Any = None
    timing_ms: float = 0.0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class PipelinePhase(Protocol):
    name: str
    dependencies: tuple[str, ...]

    def run(self, ctx: dict[str, Any]) -> PhaseResult:
        ...
