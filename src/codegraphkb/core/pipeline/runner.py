"""Small deterministic phase runner for the production indexing pipeline."""
from __future__ import annotations

import time
from typing import Any

from codegraphkb.core.pipeline.contracts import PhaseResult, PipelinePhase


class PhaseRunner:
    def __init__(self, phases: list[PipelinePhase]):
        self.phases = phases

    def run(self, initial_context: dict[str, Any] | None = None) -> list[PhaseResult]:
        ctx: dict[str, Any] = dict(initial_context or {})
        results: list[PhaseResult] = []
        completed: set[str] = set()
        for phase in self.phases:
            missing = [dep for dep in phase.dependencies if dep not in completed]
            if missing:
                raise RuntimeError(
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
