"""Common dataclasses used by parsers and the graph store."""
from __future__ import annotations

from dataclasses import dataclass, field

from codegraphkb.core.graph_schema import PrecisionLevel


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
    return_type: str = ""
    declared_type: str = ""
    visibility: str = ""
    is_exported: bool = False
    parser_backend: str = ""
    parser_version: str = ""
    semantic_backend: str = ""
    semantic_version: str = ""
    content_hash: str = ""
    extras: dict = field(default_factory=dict)


@dataclass
class ParsedEdge:
    src_qualified_name: str  # qualified name of source symbol; "<file>" means file-level
    dst_name: str  # raw name (may not yet resolve to a symbol id)
    edge_type: str  # CALLS, IMPORTS, EXTENDS, ROUTES_TO, TESTS, DEFINES
    confidence: float = 0.8
    extraction_source: str = "ast"
    line: int | None = None
    column: int | None = None
    precision_level: int = int(PrecisionLevel.SYNTAX)
    reason: str = "Extracted from syntax parser"
    metadata: dict = field(default_factory=dict)


@dataclass
class ExtractResult:
    symbols: list[ParsedSymbol]
    edges: list[ParsedEdge]
