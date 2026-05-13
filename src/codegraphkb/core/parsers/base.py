"""Common dataclasses used by parsers and the graph store.

These are the *producer-side* contracts: language providers and parsers emit
``ExtractResult`` instances, and the indexer/store consume them. Every
producer must populate at minimum ``symbols`` and ``edges``; the remaining
fields (``imports``, ``constants``, ``configs``, ``diagnostics``) are typed
empty-by-default so older parsers continue to work while Phase 4.2 / 4.3 land.

Edge semantics:
    ``dst_name``   - raw token the parser saw (e.g. ``"parse"``)
    ``dst_qname``  - resolved fully-qualified target, ``None`` if unresolved
                     (filled by the edge-resolution pass)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from codegraphkb.core.graph_schema import PrecisionLevel


@dataclass
class ParsedParameter:
    name: str
    position: int
    declared_type: str = ""
    inferred_type: str = ""
    default_value: str = ""
    is_optional: bool = False
    is_variadic: bool = False
    confidence: float = 0.7
    precision_level: int = int(PrecisionLevel.SYNTAX)
    extraction_source: str = "syntax"
    metadata: dict = field(default_factory=dict)


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
    parameters: list[ParsedParameter] = field(default_factory=list)


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
    dst_qname: str | None = None  # resolved target; None until edge-resolution runs


@dataclass
class ImportBinding:
    """A single import statement and the alias it introduces in the local file.

    Producers populate ``local_name``, ``imported_name``, and ``source_module``
    from syntax. The import-resolution pass fills ``resolved_file`` and
    ``resolved_qname`` once it can map the source module to a known symbol.
    """
    file_path: str
    local_name: str            # what the name is bound to in this file
    imported_name: str          # what was imported (may equal local_name)
    source_module: str          # the module/path on the right of `from`/`import`
    import_kind: str = "named"  # default | named | namespace | star | require | side_effect
    resolved_file: str | None = None
    resolved_qname: str | None = None
    confidence: float = 0.8
    line: int | None = None
    reason: str = "Extracted from syntax parser"
    metadata: dict = field(default_factory=dict)


@dataclass
class ConstantBinding:
    """A module-level constant (e.g. ``DEFAULT_BUDGET = 6000``)."""
    file_path: str
    qualified_name: str
    name: str
    value_repr: str = ""        # short string form of the literal (may be truncated)
    declared_type: str = ""
    line: int | None = None
    is_exported: bool = False
    confidence: float = 0.9
    metadata: dict = field(default_factory=dict)


@dataclass
class ConfigRead:
    """A read of a config key or environment variable.

    ``kind`` distinguishes ``env_var`` (process env), ``config_key`` (settings
    object / dict-style access), and ``default`` (default value supplied at
    the read site).
    """
    file_path: str
    src_qualified_name: str     # symbol doing the read; "<file>" for module scope
    key: str
    kind: str = "env_var"       # env_var | config_key | default
    default_repr: str = ""
    line: int | None = None
    confidence: float = 0.8
    extraction_source: str = "ast"
    metadata: dict = field(default_factory=dict)


@dataclass
class IndexDiagnostic:
    """A producer- or pass-level diagnostic surfaced in the doctor report.

    ``severity`` is one of ``info`` | ``warning`` | ``error``.
    ``code`` is a short stable identifier (e.g. ``parser_fallback``,
    ``unresolved_import``) suitable for grouping in the doctor output.
    """
    severity: str
    code: str
    message: str
    file_path: str | None = None
    line: int | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class ExtractResult:
    symbols: list[ParsedSymbol]
    edges: list[ParsedEdge]
    imports: list[ImportBinding] = field(default_factory=list)
    constants: list[ConstantBinding] = field(default_factory=list)
    configs: list[ConfigRead] = field(default_factory=list)
    diagnostics: list[IndexDiagnostic] = field(default_factory=list)
