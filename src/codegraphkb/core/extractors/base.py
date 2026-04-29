"""Common types for framework-aware extractors."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from codegraphkb.core.parsers.base import ParsedEdge, ParsedSymbol


class FrameworkObjectKind(str, Enum):
    ROUTE = "route"
    HANDLER = "handler"
    COMPONENT = "component"
    HOOK = "hook"
    TEST_BLOCK = "test_block"
    FIXTURE = "fixture"
    MODEL = "model"
    SCHEMA = "schema"
    API_CLIENT = "api_client"
    CONFIG = "config"
    ENV_VAR = "env_var"
    MIDDLEWARE = "middleware"
    PERMISSION = "permission"
    EXTERNAL_CALL = "external_call"
    TASK = "task"


# New edge types introduced by framework extractors.
EDGE_ROUTE_HANDLED_BY = "ROUTE_HANDLED_BY"
EDGE_COMPONENT_USES_HOOK = "COMPONENT_USES_HOOK"
EDGE_TESTS_SYMBOL = "TESTS_SYMBOL"
EDGE_MODEL_USED_BY = "MODEL_USED_BY"
EDGE_CALLS_EXTERNAL_SERVICE = "CALLS_EXTERNAL_SERVICE"
EDGE_READS_ENV_VAR = "READS_ENV_VAR"
EDGE_USES_MIDDLEWARE = "USES_MIDDLEWARE"
EDGE_USES_PERMISSION_CHECK = "USES_PERMISSION_CHECK"


@dataclass
class FrameworkExtraction:
    """Output of a framework extractor — additional symbols and edges to merge."""
    extra_symbols: list[ParsedSymbol] = field(default_factory=list)
    extra_edges: list[ParsedEdge] = field(default_factory=list)
    detected_frameworks: list[str] = field(default_factory=list)


EXTENSION_LANG = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
}
