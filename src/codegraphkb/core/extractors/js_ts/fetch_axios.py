"""HTTP-client consumer detector — `fetch(...)` and `axios.METHOD(...)`.

Each call emits:

* an ``api_consumer`` symbol  (``http::METHOD URL``) deduped per ``(method, url)``
* a ``FETCHES`` edge from the *enclosing function* (or the file module) to the
  consumer symbol
* a ``CALLS_EXTERNAL`` edge with the same shape, so callers can use either edge
  type without depending on a single ranking convention.

The extractor avoids matching ``fetch`` calls that look like local functions —
e.g. ``fetchUser(...)`` won't match because we anchor on a leading
non-identifier character.
"""
from __future__ import annotations

import re

from codegraphkb.core.extractors.base import (
    EDGE_CALLS_EXTERNAL,
    EDGE_FETCHES,
    FrameworkExtraction,
    find_enclosing_symbol,
)
from codegraphkb.core.parsers.base import ExtractResult, ParsedEdge, ParsedSymbol
from codegraphkb.core.scanner import SourceFile

_FETCH_RE = re.compile(
    r"""(?<![\w$.])fetch\s*\(\s*
        (?:
            ['"`](?P<url1>[^'"`]+)['"`]
          | (?P<expr1>[A-Za-z_$][\w$.\[\]]*)
        )
        (?P<rest>[^)]*)
    """,
    re.VERBOSE,
)
_AXIOS_METHOD_RE = re.compile(
    r"""\baxios\.(?P<method>get|post|put|patch|delete|head|options|request)\s*\(\s*
        (?:
            ['"`](?P<url1>[^'"`]+)['"`]
          | (?P<expr1>[A-Za-z_$][\w$.\[\]]*)
        )
    """,
    re.VERBOSE,
)
_AXIOS_BARE_RE = re.compile(
    r"""\baxios\s*\(\s*
        (?:
            ['"`](?P<url1>[^'"`]+)['"`]
          | (?P<expr1>[A-Za-z_$][\w$.\[\]]*)
        )
    """,
    re.VERBOSE,
)
_METHOD_OPT_RE = re.compile(
    r"""method\s*:\s*['"`](GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)['"`]""",
    re.IGNORECASE,
)


def detect_fetch_axios(source: SourceFile, extract: ExtractResult) -> FrameworkExtraction:
    text = source.content
    if not any(needle in text for needle in ("fetch(", "axios")):
        return FrameworkExtraction()
    out = FrameworkExtraction()
    seen: set[str] = set()
    module_qname = source.rel_path.replace("/", ".").replace("\\", ".")

    for m in _FETCH_RE.finditer(text):
        url = m.group("url1") or m.group("expr1") or ""
        rest = m.group("rest") or ""
        method = _detect_method(rest) or "GET"
        line = text[: m.start()].count("\n") + 1
        _emit(out, extract, module_qname, "fetch", method, url, line, seen)

    for m in _AXIOS_METHOD_RE.finditer(text):
        url = m.group("url1") or m.group("expr1") or ""
        method = m.group("method").upper()
        line = text[: m.start()].count("\n") + 1
        if method == "REQUEST":
            method = "GET"
        _emit(out, extract, module_qname, "axios", method, url, line, seen)

    for m in _AXIOS_BARE_RE.finditer(text):
        url = m.group("url1") or m.group("expr1") or ""
        line = text[: m.start()].count("\n") + 1
        _emit(out, extract, module_qname, "axios", "GET", url, line, seen)

    if out.extra_symbols:
        out.detected_frameworks.append("http_client")
    return out


def _detect_method(opts_chunk: str) -> str | None:
    m = _METHOD_OPT_RE.search(opts_chunk)
    return m.group(1).upper() if m else None


def _emit(out: FrameworkExtraction, extract: ExtractResult, module_qname: str,
          client: str, method: str, url: str, line: int, seen: set[str]) -> None:
    if not url:
        return
    key = f"{method}|{url}|{client}"
    qname = f"http::{method} {url}"
    if key not in seen:
        seen.add(key)
        out.extra_symbols.append(ParsedSymbol(
            kind="api_consumer",
            name=f"{method} {url}",
            qualified_name=qname,
            start_line=line,
            end_line=line,
            signature=f"{client} {method} {url}",
            extras={
                "framework": "http_client",
                "client": client,
                "http_method": method,
                "url": url,
            },
        ))
    caller = find_enclosing_symbol(extract.symbols, line) or module_qname
    metadata = {
        "framework": "http_client",
        "client": client,
        "http_method": method,
        "url": url,
        "consumer_qname": qname,
    }
    out.extra_edges.append(ParsedEdge(
        src_qualified_name=caller,
        dst_name=qname,
        edge_type=EDGE_FETCHES,
        confidence=0.75 if not _looks_dynamic(url) else 0.55,
        extraction_source=f"extractor:{client}",
        line=line,
        metadata=metadata,
    ))
    out.extra_edges.append(ParsedEdge(
        src_qualified_name=caller,
        dst_name=qname,
        edge_type=EDGE_CALLS_EXTERNAL,
        confidence=0.7,
        extraction_source=f"extractor:{client}",
        line=line,
        metadata=metadata,
    ))


def _looks_dynamic(url: str) -> bool:
    # Variable references are recorded but downgraded.
    return not url.startswith("/") and not url.startswith("http")
