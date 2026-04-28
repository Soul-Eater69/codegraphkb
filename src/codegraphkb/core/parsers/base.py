"""Common dataclasses used by parsers and the graph store."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ParsedSymbol:
    kind: str  # function, method, class, component, route, module
    name: str
    qualified_name: str
    start_line: int
    end_line: int
    signature: str = ""
    docstring: str = ""
    parent_qualified_name: str | None = None
    extras: dict = field(default_factory=dict)


@dataclass
class ParsedEdge:
    src_qualified_name: str  # qualified name of source symbol; "<file>" means file-level
    dst_name: str  # raw name (may not yet resolve to a symbol id)
    edge_type: str  # CALLS, IMPORTS, EXTENDS, ROUTES_TO, TESTS, DEFINES
    confidence: float = 0.8
    extraction_source: str = "ast"
    line: int | None = None


@dataclass
class ExtractResult:
    symbols: list[ParsedSymbol]
    edges: list[ParsedEdge]
