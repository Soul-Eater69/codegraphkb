"""SQLAlchemy / SQLModel ORM model detector."""
from __future__ import annotations

import ast

from codegraphkb.core.extractors.base import FrameworkExtraction
from codegraphkb.core.parsers.base import ExtractResult, ParsedSymbol
from codegraphkb.core.scanner import SourceFile

_BASE_HINTS = {"Base", "DeclarativeBase", "Model", "SQLModel", "BaseModel"}


def detect_sqlalchemy(source: SourceFile, extract: ExtractResult) -> FrameworkExtraction:
    text = source.content
    if not any(needle in text for needle in
               ("sqlalchemy", "SQLAlchemy", "SQLModel", "declarative_base", "Column(")):
        return FrameworkExtraction()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return FrameworkExtraction()
    out = FrameworkExtraction()
    detected = False
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if not _looks_like_orm_model(node):
            continue
        table = _table_name(node) or node.name.lower()
        qname = f"orm::{node.name}"
        out.extra_symbols.append(ParsedSymbol(
            kind="model",
            name=node.name,
            qualified_name=qname,
            start_line=node.lineno,
            end_line=getattr(node, "end_lineno", node.lineno),
            signature=f"ORM model {node.name}(table={table})",
            extras={"framework": "sqlalchemy", "table": table},
        ))
        detected = True
    if detected:
        out.detected_frameworks.append("sqlalchemy")
    return out


def _looks_like_orm_model(cls: ast.ClassDef) -> bool:
    for base in cls.bases:
        text = _safe_unparse(base)
        if any(hint in text for hint in _BASE_HINTS):
            return True
    # Has a Column(...) or mapped_column(...) somewhere in the class body.
    for child in cls.body:
        if isinstance(child, ast.Assign) or isinstance(child, ast.AnnAssign):
            value = getattr(child, "value", None)
            if isinstance(value, ast.Call):
                fn = value.func
                if isinstance(fn, ast.Name) and fn.id in {"Column", "mapped_column"}:
                    return True
                if isinstance(fn, ast.Attribute) and fn.attr in {"Column", "mapped_column"}:
                    return True
    return False


def _table_name(cls: ast.ClassDef) -> str | None:
    for child in cls.body:
        if isinstance(child, ast.Assign):
            for target in child.targets:
                if isinstance(target, ast.Name) and target.id == "__tablename__":
                    if isinstance(child.value, ast.Constant) and isinstance(child.value.value, str):
                        return child.value.value
    return None


def _safe_unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return ""
