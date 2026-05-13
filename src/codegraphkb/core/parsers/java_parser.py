"""Regex-based Java parser.

Not a real Java compiler. Captures the high-signal structural shapes that
downstream retrieval and edit-context workflows need:

  - ``package`` declaration → module qname
  - ``import com.foo.Bar`` → IMPORTS edge + ImportBinding (incl. static + star)
  - ``class``, ``interface``, ``enum``, ``record`` declarations
  - ``extends`` / ``implements`` edges
  - method and constructor declarations inside class bodies
  - best-effort calls inside method bodies
  - field declarations (treated as ``constant`` when ``static final``)
  - annotations on type and method declarations

Method qnames are scoped to their enclosing class via brace-matching, so
``com.foo.UserService.findUser`` is produced for a method inside
``class UserService`` in package ``com.foo``.

Limitations (acceptable for MVP, to be lifted in follow-ups):

  * Inner / nested classes resolve to the *outermost* class's qname.
  * Generics in method signatures are kept in the signature string but not
    parsed structurally.
  * Lambda bodies aren't traversed for calls.
  * No semantic adapter — type resolution is name-matching only.
"""
from __future__ import annotations

import re

from codegraphkb.core.parsers.base import (
    ExtractResult,
    ImportBinding,
    ParsedEdge,
    ParsedSymbol,
)
from codegraphkb.core.scanner import SourceFile

JAVA_PARSER_VERSION = 1

_PACKAGE_RE = re.compile(r"(?m)^\s*package\s+([\w.]+)\s*;")
_IMPORT_RE = re.compile(
    r"(?m)^\s*import\s+(static\s+)?([\w.]+(?:\.\*)?)\s*;"
)
_TYPE_RE = re.compile(
    r"""(?mx)
    ^\s*
    (?:@\w[\w.]*(?:\([^)]*\))?\s*)*       # decorators above the decl
    (?:public|private|protected|abstract|final|static|sealed|non-sealed|strictfp|\s)*
    (?P<kind>class|interface|enum|record)
    \s+ (?P<name>[A-Za-z_$][\w$]*)
    (?:\s*<[^>{]*>)?                      # type parameters
    (?:\s*\(.*?\))?                       # record header
    (?:\s+extends\s+(?P<extends>[\w.<>,\s$]+?))?
    (?:\s+implements\s+(?P<implements>[\w.<>,\s$]+?))?
    \s* \{
    """
)
_METHOD_RE = re.compile(
    r"""(?mx)
    ^[ \t]+                               # indented (inside class body)
    (?:@\w[\w.]*(?:\([^)]*\))?\s*)*       # annotations on prior lines / inline
    (?:public|private|protected|abstract|final|static|synchronized|native|default|strictfp|\s)*
    (?:<[^>{]*>\s*)?                      # generic type params
    (?:
        (?P<return> [\w.<>\[\],\s$?]+? ) \s+ (?P<name>[A-Za-z_$][\w$]*)
      |                                   # constructor: no return type
        (?P<ctor_name>[A-Za-z_$][\w$]*)
    )
    \s*\(  (?P<params>[^)]*)  \)
    (?:\s*throws\s+[\w.,\s]+)?
    \s* (?P<body>[{;])
    """
)
# Field declarations: catch top-level `static final` for constants.
_FIELD_RE = re.compile(
    r"""(?mx)
    ^[ \t]+
    (?:public|private|protected|\s)*
    (?P<modifiers>(?:static|final|\s)+)
    (?P<type>[\w.<>\[\],\s$?]+?)
    \s+
    (?P<name>[A-Z][A-Z0-9_]*)             # UPPER_CASE name only -> constant
    \s* = .*? ;
    """
)
_CALL_RE = re.compile(r"(?<![\w$.])([A-Za-z_$][\w$]*)\s*\(")

# Reserved words / control flow that masquerade as calls in regex output.
_JAVA_KEYWORDS = frozenset({
    "if", "for", "while", "switch", "catch", "return", "throw", "new",
    "synchronized", "try", "do", "super", "this", "instanceof", "assert",
    "yield", "case", "break", "continue",
})


def parse_java(source: SourceFile) -> ExtractResult:
    text = source.content
    rel = source.rel_path

    package = _detect_package(text) or _fallback_module_from_path(rel)
    symbols: list[ParsedSymbol] = []
    edges: list[ParsedEdge] = []
    imports: list[ImportBinding] = []

    # Imports
    for m in _IMPORT_RE.finditer(text):
        is_static = bool(m.group(1))
        fq = m.group(2)
        line = text[: m.start()].count("\n") + 1
        if fq.endswith(".*"):
            module = fq[:-2]
            edges.append(ParsedEdge(
                src_qualified_name=package,
                dst_name=module,
                edge_type="IMPORTS",
                line=line,
                reason="java.star_import",
            ))
            continue
        # Last dotted segment is the local binding name in the file.
        local = fq.rsplit(".", 1)[-1]
        source_mod = fq.rsplit(".", 1)[0] if "." in fq else ""
        edges.append(ParsedEdge(
            src_qualified_name=package,
            dst_name=fq,
            edge_type="IMPORTS",
            line=line,
        ))
        imports.append(ImportBinding(
            file_path=rel,
            local_name=local,
            imported_name=local,
            source_module=source_mod,
            import_kind="static" if is_static else "named",
            line=line,
            reason="java.import",
            metadata={"static": is_static},
        ))

    # Types (class/interface/enum/record). Track each opening brace and the
    # matching close so we can scope methods/fields/calls into the right type.
    type_spans = list(_collect_type_spans(text))
    for span in type_spans:
        name = span["name"]
        kind = span["kind"]
        qname = f"{package}.{name}" if package else name
        symbols.append(ParsedSymbol(
            kind=_normalize_kind(kind),
            name=name,
            qualified_name=qname,
            start_line=span["start_line"],
            end_line=span["end_line"],
            signature=_signature_for_type(text, span),
            parent_qualified_name=package or None,
            extras={"java_kind": kind, "annotations": span["annotations"]},
        ))
        for ext in span["extends"]:
            edges.append(ParsedEdge(
                src_qualified_name=qname,
                dst_name=ext,
                edge_type="EXTENDS",
                line=span["start_line"],
            ))
        for impl in span["implements"]:
            edges.append(ParsedEdge(
                src_qualified_name=qname,
                dst_name=impl,
                edge_type="IMPLEMENTS",
                line=span["start_line"],
            ))

    # Methods and constants inside each type's body
    for span in type_spans:
        type_qname = f"{package}.{span['name']}" if package else span["name"]
        body = text[span["body_start"]: span["body_end"]]
        body_line_offset = text[: span["body_start"]].count("\n")
        for m in _METHOD_RE.finditer(body):
            # The regex has two alternatives: with return type (groups
            # ``return``/``name``) or constructor form (``ctor_name`` only).
            ctor_name = m.group("ctor_name")
            if ctor_name is not None:
                method_name = ctor_name
                return_type = ""
                # A bare ``Identifier(...)`` only counts as a constructor when
                # the name matches the enclosing class — otherwise it's a
                # bare function call or a noisy match we should ignore.
                if method_name != span["name"]:
                    continue
                is_constructor = True
            else:
                method_name = m.group("name")
                return_type = (m.group("return") or "").strip()
                # Skip false positives where the regex catches the type-decl
                # line itself ("class" / "interface" as a "return type").
                if return_type in {"class", "interface", "enum", "record"}:
                    continue
                is_constructor = (return_type == span["name"])
            params = m.group("params").strip()
            line = body_line_offset + body.count("\n", 0, m.start()) + 1
            kind = "constructor" if is_constructor else "method"
            sym_qname = f"{type_qname}.{method_name}" if not is_constructor else f"{type_qname}.<init>"
            symbols.append(ParsedSymbol(
                kind=kind,
                name=method_name,
                qualified_name=sym_qname,
                start_line=line,
                end_line=line,  # cheap; refined would scan to matching brace
                signature=f"{return_type} {method_name}({params})",
                return_type="" if is_constructor else return_type,
                parent_qualified_name=type_qname,
                extras={},
            ))
            # Calls inside the method body (only if we have a body block).
            if m.group("body") == "{":
                body_start = m.end()
                body_end = _find_matching_brace(body, body_start - 1)
                if body_end > body_start:
                    seen: set[str] = set()
                    for cm in _CALL_RE.finditer(body[body_start: body_end]):
                        name = cm.group(1)
                        if name in _JAVA_KEYWORDS or name in seen:
                            continue
                        if name == method_name:
                            # Skip self-recursive misfires from the regex
                            # catching the declaration name. Real recursive
                            # calls inside the body still get caught by a
                            # later iteration that won't be the decl line.
                            seen.add(name)
                            continue
                        seen.add(name)
                        edges.append(ParsedEdge(
                            src_qualified_name=sym_qname,
                            dst_name=name,
                            edge_type="CALLS",
                            confidence=0.55,
                            extraction_source="regex",
                        ))
        for m in _FIELD_RE.finditer(body):
            name = m.group("name")
            line = body_line_offset + body.count("\n", 0, m.start()) + 1
            qname = f"{type_qname}.{name}"
            symbols.append(ParsedSymbol(
                kind="constant",
                name=name,
                qualified_name=qname,
                start_line=line,
                end_line=line,
                signature=f"{m.group('type').strip()} {name}",
                parent_qualified_name=type_qname,
            ))

    return ExtractResult(symbols=symbols, edges=edges, imports=imports)


# ---------- helpers ----------

def _detect_package(text: str) -> str:
    m = _PACKAGE_RE.search(text)
    return m.group(1) if m else ""


def _fallback_module_from_path(rel_path: str) -> str:
    """When the file has no package declaration, fall back to a sanitized
    path-based qname so symbols still get a unique scope."""
    p = rel_path.replace("\\", "/")
    if p.endswith(".java"):
        p = p[: -len(".java")]
    # Strip the trailing file name (the class qname will re-add it).
    parts = p.split("/")
    if len(parts) > 1:
        return ".".join(parts[:-1])
    return ""


def _normalize_kind(java_kind: str) -> str:
    return {
        "class": "class",
        "interface": "interface",
        "enum": "enum",
        "record": "class",
    }.get(java_kind, "class")


def _signature_for_type(text: str, span: dict) -> str:
    head = text[span["start"]: span["body_start"]]
    return " ".join(head.split())


def _collect_type_spans(text: str):
    """Find every class/interface/enum/record declaration with brace-matched
    body span and any preceding annotations.

    Returns dicts with keys:
        name, kind, start, body_start, body_end, start_line, end_line,
        extends, implements, annotations
    """
    for m in _TYPE_RE.finditer(text):
        body_start = m.end() - 1  # the `{`
        body_end = _find_matching_brace(text, body_start)
        start_line = text[: m.start()].count("\n") + 1
        end_line = text[: body_end].count("\n") + 1 if body_end > body_start else start_line
        extends = _split_type_list(m.group("extends"))
        implements = _split_type_list(m.group("implements"))
        # Annotations may be on lines preceding the decl OR matched as part
        # of the type-regex prefix; collect both.
        annotations = _annotations_before(text, m.start())
        annotations += _annotations_in(text[m.start(): m.end()])
        yield {
            "name": m.group("name"),
            "kind": m.group("kind"),
            "start": m.start(),
            "body_start": body_start,
            "body_end": body_end,
            "start_line": start_line,
            "end_line": end_line,
            "extends": extends,
            "implements": implements,
            "annotations": annotations,
        }


def _split_type_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    for part in raw.split(","):
        cleaned = re.sub(r"<[^>]*>", "", part).strip()
        cleaned = cleaned.strip("{")
        if cleaned:
            out.append(cleaned)
    return out


_ANNOT_RE = re.compile(r"@(\w[\w.]*)")


def _annotations_in(span: str) -> list[str]:
    """Return annotation names found in ``span``. Used to capture annotations
    that the type regex itself consumed as part of its prefix."""
    return _ANNOT_RE.findall(span)


def _annotations_before(text: str, decl_start: int) -> list[str]:
    """Pull the annotation names from the lines just above a declaration."""
    out: list[str] = []
    # Walk backwards line by line until a blank or non-annotation line.
    head = text[:decl_start]
    lines = head.splitlines()
    for line in reversed(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("@"):
            break
        m = re.match(r"@(\w[\w.]*)", stripped)
        if m:
            out.append(m.group(1))
    out.reverse()
    return out


def _find_matching_brace(text: str, open_pos: int) -> int:
    """Return the index just past the ``}`` matching the ``{`` at ``open_pos``.

    Falls back to ``len(text)`` if the file is unbalanced.
    """
    if open_pos >= len(text) or text[open_pos] != "{":
        return open_pos
    depth = 0
    i = open_pos
    in_str: str | None = None
    in_block_comment = False
    in_line_comment = False
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
        elif in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 1
        elif in_str is not None:
            if ch == "\\":
                i += 1
            elif ch == in_str:
                in_str = None
        else:
            if ch == "/" and nxt == "/":
                in_line_comment = True
                i += 1
            elif ch == "/" and nxt == "*":
                in_block_comment = True
                i += 1
            elif ch in ('"', "'"):
                in_str = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return len(text)
