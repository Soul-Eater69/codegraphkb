"""Process / ProcessStep dataclasses and shared constants.

A *Process* is a workflow trace through the graph that starts at an entrypoint
(Route, FETCHES caller, test_block) and walks edges until it hits a terminal
(QUERIES, CALLS_EXTERNAL, FETCHES) or runs out of high-confidence edges.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Process types written into ``processes.process_type``.
PROCESS_API_FLOW = "api_flow"
PROCESS_UI_TO_API_FLOW = "ui_to_api_flow"
PROCESS_TEST_FLOW = "test_flow"
PROCESS_EXTERNAL_CALL_FLOW = "external_call_flow"


# Edge types treated as terminal: a process stops as soon as it traverses one.
TERMINAL_EDGE_TYPES = frozenset({
    "QUERIES",
    "CALLS_EXTERNAL",
    "FETCHES",
})

# Edge types we follow when extending a chain from the current node.
# Order matters: higher-priority edges are picked first when multiple exist.
FOLLOW_EDGE_TYPES = (
    "CALLS",
    "QUERIES",
    "CALLS_EXTERNAL",
    "FETCHES",
    "ROUTES_TO",
)


# Build-time defaults; tunable via builder kwargs.
DEFAULT_MAX_DEPTH = 8
DEFAULT_MIN_STEP_CONFIDENCE = 0.5


@dataclass
class ProcessStep:
    step: int
    src_qname: str
    dst_qname: str
    edge_type: str
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "step": self.step,
            "src_qname": self.src_qname,
            "dst_qname": self.dst_qname,
            "edge_type": self.edge_type,
            "confidence": self.confidence,
            "metadata": dict(self.metadata),
        }


@dataclass
class Process:
    id: str
    label: str
    process_type: str
    entrypoint_id: str
    terminal_id: str
    steps: list[ProcessStep] = field(default_factory=list)
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def step_count(self) -> int:
        return len(self.steps)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "process_type": self.process_type,
            "entrypoint_id": self.entrypoint_id,
            "terminal_id": self.terminal_id,
            "step_count": self.step_count,
            "confidence": self.confidence,
            "metadata": dict(self.metadata),
            "steps": [s.to_dict() for s in self.steps],
        }
