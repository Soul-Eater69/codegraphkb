"""React: detect `useXxx()` calls inside components and emit COMPONENT_USES_HOOK edges."""
from __future__ import annotations

import re

from codegraphkb.core.extractors.base import (
    EDGE_COMPONENT_USES_HOOK, FrameworkExtraction,
)
from codegraphkb.core.parsers.base import ExtractResult, ParsedEdge
from codegraphkb.core.scanner import SourceFile

_HOOK_CALL_RE = re.compile(r"\b(use[A-Z][A-Za-z0-9_]*)\s*\(")


def detect_react_hooks(source: SourceFile, extract: ExtractResult) -> FrameworkExtraction:
    if "use" not in source.content:
        return FrameworkExtraction()
    out = FrameworkExtraction()
    components = [s for s in extract.symbols if s.kind == "component"]
    if not components:
        return FrameworkExtraction()
    text = source.content
    lines = text.splitlines()
    detected = False
    for component in components:
        slice_text = "\n".join(lines[component.start_line - 1: component.end_line])
        seen: set[str] = set()
        for m in _HOOK_CALL_RE.finditer(slice_text):
            hook = m.group(1)
            if hook in seen:
                continue
            seen.add(hook)
            out.extra_edges.append(ParsedEdge(
                src_qualified_name=component.qualified_name,
                dst_name=hook,
                edge_type=EDGE_COMPONENT_USES_HOOK,
                confidence=0.85,
                extraction_source="extractor:react_hooks",
            ))
            detected = True
    if detected:
        out.detected_frameworks.append("react_hooks")
    return out
