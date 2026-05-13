"""Detect config-key reads through well-known settings receivers.

Recognized patterns (all return a ``key`` string):

    settings.DEBUG                    -> DEBUG
    config.token_budget               -> token_budget
    app.config["SECRET_KEY"]          -> SECRET_KEY
    settings.get("token_budget", 6000) -> token_budget

We deliberately keep the receiver allowlist small (``settings``, ``config``,
``app.config``) to avoid flooding the graph with edges for every attribute
access. Frameworks like Django / Flask / Pydantic-Settings all use these
receiver names, so the allowlist covers the high-signal cases.

Each detected read emits:
    * a synthetic ``config_key`` symbol with qname ``config::<KEY>``
    * a ``READS_CONFIG_KEY`` edge from the enclosing function to that symbol
"""
from __future__ import annotations

import ast

from codegraphkb.core.extractors.base import (
    EDGE_READS_CONFIG_KEY, FrameworkExtraction, find_enclosing_symbol,
)
from codegraphkb.core.parsers.base import ExtractResult, ParsedEdge, ParsedSymbol
from codegraphkb.core.scanner import SourceFile

# Receiver names whose attribute / subscript reads we treat as config-key reads.
_CONFIG_RECEIVERS = {"settings", "config"}


def detect_config_reads(source: SourceFile, extract: ExtractResult) -> FrameworkExtraction:
    out = FrameworkExtraction()
    if not any(name in source.content for name in _CONFIG_RECEIVERS):
        return out
    try:
        tree = ast.parse(source.content)
    except SyntaxError:
        return out

    seen_symbols: set[str] = set()
    seen_edges: set[tuple[str, str]] = set()

    for node in ast.walk(tree):
        key = _extract_config_key(node)
        if not key:
            continue
        line = getattr(node, "lineno", 0) or 0
        src_qname = find_enclosing_symbol(extract.symbols, line)
        if not src_qname:
            continue
        dst_qname = f"config::{key}"
        if dst_qname not in seen_symbols:
            seen_symbols.add(dst_qname)
            out.extra_symbols.append(ParsedSymbol(
                kind="config_key",
                name=key,
                qualified_name=dst_qname,
                start_line=line,
                end_line=line,
                signature=f"config key {key}",
                extras={"framework": "config"},
            ))
        edge_key = (src_qname, dst_qname)
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)
        out.extra_edges.append(ParsedEdge(
            src_qualified_name=src_qname,
            dst_name=key,
            dst_qname=dst_qname,
            edge_type=EDGE_READS_CONFIG_KEY,
            confidence=0.8,
            extraction_source="extractor:config",
            line=line or None,
            reason="Function reads attribute / subscript on a config receiver",
        ))
    if out.extra_symbols:
        out.detected_frameworks.append("config")
    return out


def _extract_config_key(node: ast.AST) -> str | None:
    """Return the config key string for a single AST node, or None.

    Receiver matching is conservative: we accept either a bare ``Name`` whose
    id is in the allowlist, or an ``Attribute`` whose final ``.config`` chain
    ends in one of the allowed receivers (handles ``app.config``).
    """
    # settings.X / config.X  (Attribute access on allowed receiver)
    if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
        if _is_config_receiver(node.value) and not node.attr.startswith("_"):
            # Skip the .get / .config attribute itself when nested
            if node.attr in {"get", "config"}:
                return None
            return node.attr
    # settings["X"] / config["X"] / app.config["X"]
    if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load):
        if _is_config_receiver(node.value):
            slc = node.slice
            if isinstance(slc, ast.Constant) and isinstance(slc.value, str):
                return slc.value
    # settings.get("X", default) / config.get("X")
    if isinstance(node, ast.Call):
        fn = node.func
        if (isinstance(fn, ast.Attribute) and fn.attr == "get"
                and _is_config_receiver(fn.value)):
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                return node.args[0].value
    return None


def _is_config_receiver(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id in _CONFIG_RECEIVERS
    if isinstance(node, ast.Attribute):
        # Match ``app.config`` / ``self.config`` / ``current_app.config`` etc.
        return node.attr in _CONFIG_RECEIVERS
    return False
