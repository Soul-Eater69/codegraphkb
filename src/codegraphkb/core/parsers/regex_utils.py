"""Shared helpers for lightweight regex parsers."""
from __future__ import annotations

import re


def line_number(text: str, index: int) -> int:
    return text[:index].count("\n") + 1


def end_line_number(text: str, index: int) -> int:
    if index <= 0:
        return 1
    return text[:index].count("\n") + 1


def find_matching_brace(text: str, open_pos: int) -> int:
    """Return the index just past the matching closing brace.

    This is deliberately lightweight, but it skips common string and comment
    forms well enough for indexing-oriented parsers.
    """
    if open_pos < 0 or open_pos >= len(text) or text[open_pos] != "{":
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
            elif ch in ('"', "'", "`"):
                in_str = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return len(text)


def spans_contain(spans: list[tuple[int, int]], index: int) -> bool:
    return any(start <= index < end for start, end in spans)


def module_from_path(rel_path: str, suffix: str, sep: str = ".") -> str:
    path = rel_path.replace("\\", "/")
    if path.endswith(suffix):
        path = path[: -len(suffix)]
    parts = [p for p in path.split("/") if p]
    if not parts:
        return ""
    stem = parts[-1]
    if stem in {"mod", "lib", "main", "__init__"} and len(parts) > 1:
        parts = parts[:-1]
    return sep.join(_sanitize_identifier(p) for p in parts if p)


def split_type_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    for part in raw.split(","):
        cleaned = re.sub(r"<[^>]*>", "", part).strip()
        cleaned = cleaned.strip("{}()")
        if cleaned:
            out.append(cleaned)
    return out


def normalize_route_path(*parts: str) -> str:
    segments: list[str] = []
    for part in parts:
        if not part:
            continue
        cleaned = part.strip().strip('"').strip("'")
        if not cleaned:
            continue
        segments.append(cleaned.strip("/"))
    joined = "/".join(s for s in segments if s)
    return "/" + joined if joined else "/"


def first_string_literal(raw: str | None) -> str:
    if not raw:
        return ""
    match = re.search(r"""["']([^"']*)["']""", raw)
    return match.group(1) if match else ""


def _sanitize_identifier(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", value)
    if cleaned and cleaned[0].isdigit():
        cleaned = "_" + cleaned
    return cleaned
