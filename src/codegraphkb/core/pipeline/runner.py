"""Small deterministic phase runner for the production indexing pipeline."""
from __future__ import annotations

import time
from typing import Any

from codegraphkb.core.pipeline.contracts import PhaseResult, PipelinePhase


class PipelineConfigError(ValueError):
    """Raised when the phase set itself is invalid (duplicates, missing deps)."""


class PipelineCycleError(PipelineConfigError):
    """Raised when phase dependencies form a cycle."""


class PhaseRunner:
    def __init__(self, phases: list[PipelinePhase]):
        self.phases = list(phases)
        self._validate(self.phases)
        self.ordered_phases = _topological_sort(self.phases)

    @staticmethod
    def _validate(phases: list[PipelinePhase]) -> None:
        names: set[str] = set()
        for phase in phases:
            if phase.name in names:
                raise PipelineConfigError(f"Duplicate phase name: `{phase.name}`")
            names.add(phase.name)
        for phase in phases:
            for dep in phase.dependencies:
                if dep not in names:
                    raise PipelineConfigError(
                        f"Phase `{phase.name}` depends on unknown phase `{dep}`"
                    )

    def run(self, initial_context: dict[str, Any] | None = None) -> list[PhaseResult]:
        ctx: dict[str, Any] = dict(initial_context or {})
        results: list[PhaseResult] = []
        completed: set[str] = set()
        for phase in self.ordered_phases:
            missing = [dep for dep in phase.dependencies if dep not in completed]
            if missing:
                raise PipelineConfigError(
                    f"Phase `{phase.name}` missing dependencies: {', '.join(missing)}"
                )
            started = time.perf_counter()
            result = phase.run(ctx)
            if result.timing_ms == 0.0:
                result.timing_ms = (time.perf_counter() - started) * 1000.0
            results.append(result)
            ctx[phase.name] = result.output
            completed.add(phase.name)
        return results


def _topological_sort(phases: list[PipelinePhase]) -> list[PipelinePhase]:
    by_name = {p.name: p for p in phases}
    # Kahn's algorithm with deterministic ordering: when several phases are
    # ready we keep them in their original input order so reruns are stable.
    in_deg: dict[str, int] = {p.name: len(p.dependencies) for p in phases}
    ordered: list[PipelinePhase] = []
    # Track input order for stable iteration.
    order_index = {p.name: i for i, p in enumerate(phases)}
    ready = [p.name for p in phases if in_deg[p.name] == 0]
    while ready:
        ready.sort(key=lambda n: order_index[n])
        name = ready.pop(0)
        ordered.append(by_name[name])
        for other in phases:
            if name in other.dependencies and in_deg[other.name] > 0:
                in_deg[other.name] -= 1
                if in_deg[other.name] == 0:
                    ready.append(other.name)
    if len(ordered) != len(phases):
        cycle = _find_cycle(phases)
        raise PipelineCycleError(
            "Pipeline phase graph contains a cycle: " + " -> ".join(cycle)
        )
    return ordered


def _find_cycle(phases: list[PipelinePhase]) -> list[str]:
    by_name = {p.name: p for p in phases}
    WHITE, GREY, BLACK = 0, 1, 2
    color = {p.name: WHITE for p in phases}
    stack: list[str] = []

    def visit(name: str) -> list[str] | None:
        if color[name] == GREY:
            idx = stack.index(name) if name in stack else 0
            return stack[idx:] + [name]
        if color[name] == BLACK:
            return None
        color[name] = GREY
        stack.append(name)
        phase = by_name.get(name)
        if phase is not None:
            for dep in phase.dependencies:
                if dep not in by_name:
                    continue
                found = visit(dep)
                if found is not None:
                    return found
        stack.pop()
        color[name] = BLACK
        return None

    for phase in phases:
        result = visit(phase.name)
        if result is not None:
            return result
    return [phase.name for phase in phases]
