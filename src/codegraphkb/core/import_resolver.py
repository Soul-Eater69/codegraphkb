"""Phase 4.2 — whole-repo import / alias resolution.

The indexer emits per-file ``ImportBinding`` records (``local_name``,
``imported_name``, ``source_module``) but cannot resolve them on its own —
mapping ``from .x import y`` to a concrete symbol qname needs the full set of
files in the index.

This module runs *after* all files have been parsed and persisted. It:

1. Pulls every binding from the ``imports`` table.
2. For each binding, computes a candidate ``target_qname`` by combining the
   binding's source module with the imported name and looking it up in the
   ``symbols`` table.
3. Persists the resolved target back onto the binding row.
4. Rewrites unresolved edges whose ``src_qname`` lives in the binding's file
   and whose ``dst_name`` matches the binding's ``local_name`` — pointing the
   edge at the resolved target qname.

The pass is conservative: ambiguous or unresolved bindings are left alone, and
every rewrite records ``resolution_strategy=import_alias`` in the edge's
metadata so later passes / debuggers can audit it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from codegraphkb.core.graph_schema import PrecisionLevel


@dataclass
class ResolverStats:
    bindings_total: int = 0
    bindings_resolved: int = 0
    edges_rewritten: int = 0


def resolve_imports_and_rewrite_edges(store) -> ResolverStats:
    """Run the alias resolution pass.

    Returns counts the doctor report surfaces; the store is mutated in place.
    """
    stats = ResolverStats()

    package_prefix_map = _detect_python_package_prefix_map(store)
    symbol_index = _build_symbol_index(store, package_prefix_map)
    file_module_qname = _build_file_module_map(store, package_prefix_map)
    bindings_by_file = store.iter_import_bindings_by_file()
    stats.bindings_total = sum(len(v) for v in bindings_by_file.values())

    if not bindings_by_file:
        return stats

    # Pass 1: resolve each binding's target qname against the symbol index.
    resolved_per_file: dict[str, dict[str, str]] = {}
    for file_path, bindings in bindings_by_file.items():
        local_to_qname: dict[str, str] = {}
        for b in bindings:
            existing = b.get("target_qname")
            if existing:
                local_to_qname[b["local_name"]] = existing
                stats.bindings_resolved += 1
                continue
            resolved = _resolve_binding(
                binding=b,
                file_path=file_path,
                symbol_index=symbol_index,
                file_module_qname=file_module_qname,
            )
            if resolved:
                store.update_import_binding_target(
                    file_path, b["local_name"], resolved,
                )
                local_to_qname[b["local_name"]] = resolved
                stats.bindings_resolved += 1
        if local_to_qname:
            resolved_per_file[file_path] = local_to_qname

    # Pass 2: rewrite unresolved edges that originate in a file with bindings.
    if resolved_per_file:
        stats.edges_rewritten = _rewrite_edges(store, resolved_per_file)

    return stats


def _build_symbol_index(
    store, package_prefix_map: dict[str, str] | None = None,
) -> dict[str, str]:
    """Map ``qualified_name`` and ``module.name`` lookups to symbol qnames.

    The base form is the fully-qualified name as stored. When the repo uses a
    ``src/``-layout package, symbols live under e.g. ``src.codegraphkb.x`` on
    disk while user code imports them as ``codegraphkb.x``. The ``package_
    prefix_map`` rewrites disk prefixes to import prefixes so the resolver
    can look up bindings using either form.
    """
    rows = store._conn.execute(
        "SELECT s.qualified_name, s.name, s.parent_qname, f.path "
        "FROM symbols s JOIN files f ON s.file_id = f.id"
    ).fetchall()
    index: dict[str, str] = {}
    prefix_map = package_prefix_map or {}
    for row in rows:
        qname = row["qualified_name"]
        index[qname] = qname
        if prefix_map:
            alt = _apply_prefix_map(qname, prefix_map)
            if alt and alt != qname:
                index.setdefault(alt, qname)
    return index


def _build_file_module_map(
    store, package_prefix_map: dict[str, str] | None = None,
) -> dict[str, str]:
    """Map each file_path to its *import-form* module qname.

    For relative imports inside a ``src/``-layout Python package, the file's
    module qname must be the import form (``codegraphkb.workflow``) — not
    the on-disk form (``src.codegraphkb.workflow``) — so resolving
    ``from .x`` starts from the right base. JS/TS files use the on-disk
    qname directly; their relative imports are resolved by path math, not
    by stripping a package prefix.
    """
    rows = store._conn.execute("SELECT path, language FROM files").fetchall()
    prefix_map = package_prefix_map or {}
    out: dict[str, str] = {}
    for r in rows:
        path = r["path"]
        lang = (r["language"] or "").lower()
        if lang == "python":
            disk_qname = _python_module_qname(path)
            out[path] = _apply_prefix_map(disk_qname, prefix_map) or disk_qname
        elif lang in ("javascript", "typescript"):
            out[path] = _js_module_qname(path)
    return out


_JS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")


def _js_module_qname(rel_path: str) -> str:
    p = rel_path.replace("\\", "/")
    for ext in _JS_EXTS:
        if p.endswith(ext):
            p = p[: -len(ext)]
            break
    # Drop `/index` so an import of "./foo" can match "./foo/index".
    if p.endswith("/index"):
        p = p[: -len("/index")]
    return p.replace("/", ".")


def _detect_python_package_prefix_map(store) -> dict[str, str]:
    """Return ``{disk_prefix: import_prefix}`` for every Python package root.

    A *package root* is a directory containing ``__init__.py`` whose parent
    directory does NOT contain ``__init__.py``. Its on-disk path becomes the
    ``disk_prefix`` (joined by ``.``), and the directory's basename becomes
    the ``import_prefix`` — e.g. ``src/codegraphkb/__init__.py`` gives
    ``{"src.codegraphkb": "codegraphkb"}``.

    For flat-layout repos (``pkg/__init__.py`` at repo root) the mapping is
    an identity rewrite, so we skip those to keep the map small.
    """
    rows = store._conn.execute(
        "SELECT path FROM files WHERE language='python' AND path LIKE '%__init__.py'"
    ).fetchall()
    init_dirs = {
        _strip_init(r["path"]) for r in rows
    }
    out: dict[str, str] = {}
    for d in init_dirs:
        if not d:
            continue
        parent = d.rsplit("/", 1)[0] if "/" in d else ""
        # Also handle Windows-style separators that may have slipped through.
        if "\\" in d:
            parent = d.rsplit("\\", 1)[0]
        if parent in init_dirs:
            continue  # not a root — its parent is also a package
        disk_prefix = d.replace("/", ".").replace("\\", ".")
        import_prefix = d.replace("\\", "/").rsplit("/", 1)[-1]
        if disk_prefix != import_prefix:
            out[disk_prefix] = import_prefix
    return out


def _strip_init(path: str) -> str:
    p = path.replace("\\", "/")
    if p.endswith("/__init__.py"):
        return p[: -len("/__init__.py")]
    if p == "__init__.py":
        return ""
    return p


def _apply_prefix_map(qname: str, prefix_map: dict[str, str]) -> str:
    """Rewrite ``qname`` if it starts with any known disk prefix.

    Returns the rewritten qname, or the original if no prefix matched.
    Longest-match wins so nested package roots stay consistent.
    """
    if not qname or not prefix_map:
        return qname
    best_prefix = ""
    for disk_prefix in prefix_map:
        if qname == disk_prefix or qname.startswith(disk_prefix + "."):
            if len(disk_prefix) > len(best_prefix):
                best_prefix = disk_prefix
    if not best_prefix:
        return qname
    tail = qname[len(best_prefix):]
    return f"{prefix_map[best_prefix]}{tail}"


def _python_module_qname(rel_path: str) -> str:
    p = rel_path
    if p.endswith(".py"):
        p = p[:-3]
    return p.replace("/", ".").replace("\\", ".")


def _resolve_binding(
    *,
    binding: dict,
    file_path: str,
    symbol_index: dict[str, str],
    file_module_qname: dict[str, str],
) -> str | None:
    """Compute a target qname for one ImportBinding, or return None.

    Tries, in order:
        1. JS/TS relative path (``./x``, ``../x/y``) resolved by walking
           directories from the file_path.
        2. Python dotted relative module (``.x``, ``..x``).
        3. ``<source_module>.<imported_name>``                (absolute import)
        4. ``<source_module>`` itself                          (module-as-symbol)
        5. ``<imported_name>`` alone                           (fallback)

    The first candidate that hits ``symbol_index`` wins.
    """
    imported_name = binding.get("imported_name") or ""
    source_module = binding.get("source_module") or ""
    is_default_or_star = imported_name in {"default", "*", ""}

    candidates: list[str] = []

    if source_module.startswith("./") or source_module.startswith("../"):
        # JS/TS relative path — convert to a module qname by walking from the
        # file's directory. ``./util`` from ``src/api/foo.ts`` -> ``src.api.util``.
        target_module = _resolve_js_relative_module(file_path, source_module)
        if target_module:
            if imported_name and not is_default_or_star:
                candidates.append(f"{target_module}.{imported_name}")
            # For default/namespace imports the binding represents the
            # module itself or its default export; the module qname is the
            # best we can do without semantic info.
            candidates.append(target_module)
    elif source_module.startswith("."):
        # Python-style relative module (``.x``, ``..pkg.x``).
        owner_module = file_module_qname.get(file_path, "")
        target_module = _resolve_relative_module(owner_module, source_module)
        if target_module:
            if imported_name and not is_default_or_star:
                candidates.append(f"{target_module}.{imported_name}")
            candidates.append(target_module)
    else:
        if source_module and imported_name and not is_default_or_star:
            candidates.append(f"{source_module}.{imported_name}")
        if source_module:
            candidates.append(source_module)
        if imported_name and not is_default_or_star:
            candidates.append(imported_name)

    for cand in candidates:
        if not cand:
            continue
        if cand in symbol_index:
            return symbol_index[cand]
    return None


def _resolve_js_relative_module(file_path: str, source_module: str) -> str:
    """``./util`` from ``src/api/foo.ts`` -> ``src.api.util``.

    Returns the dotted module qname. The caller looks this up in the symbol
    index — if no symbol matches, the binding stays unresolved.
    """
    file_path = file_path.replace("\\", "/")
    src = source_module.replace("\\", "/")
    parent_parts = file_path.split("/")[:-1]
    spec_parts = [p for p in src.split("/") if p]

    cur = list(parent_parts)
    for part in spec_parts:
        if part == ".":
            continue
        if part == "..":
            if cur:
                cur.pop()
            continue
        cur.append(part)
    if not cur:
        return ""
    # Strip a trailing /index so `./foo` matches a `foo/index.ts` module too.
    if cur[-1] == "index":
        cur = cur[:-1]
    return ".".join(cur)


def _resolve_relative_module(owner_module: str, source_module: str) -> str:
    """``from .x import y`` inside ``pkg.sub.mod`` resolves x to ``pkg.sub.x``."""
    if not source_module.startswith("."):
        return source_module
    dots = 0
    for ch in source_module:
        if ch == ".":
            dots += 1
        else:
            break
    tail = source_module[dots:]
    parts = owner_module.split(".") if owner_module else []
    # `from . import x` inside pkg.sub.mod is parent = pkg.sub, then add tail.
    # One leading dot means "the current package" — for a module `pkg.sub.mod`,
    # the current package is `pkg.sub`, so we drop the last segment once.
    drop = max(dots, 1)
    base_parts = parts[:-drop] if drop <= len(parts) else []
    if tail:
        base_parts = [*base_parts, tail]
    return ".".join(part for part in base_parts if part)


def _rewrite_edges(
    store, resolved_per_file: dict[str, dict[str, str]],
) -> int:
    """Rewrite unresolved edges using each file's local alias table.

    An eligible edge has ``dst_qname IS NULL`` and originates from a symbol
    that lives in a file with at least one resolved binding. ``dst_name``
    must match a local alias in that file.

    Each rewrite stamps:
        * ``dst_qname`` with the resolved target
        * ``precision_level`` raised to ``CODEGRAPH_RESOLVER``
        * ``extraction_source`` appended with ``+import-alias-resolver``
        * ``metadata_json.resolution_strategy = "import_alias"`` plus the
          original ``dst_name`` and selected candidate so the trail is
          auditable.
    """
    # Pull every unresolved edge whose source symbol lives in a file we have
    # bindings for. We fetch each row's existing extraction_source /
    # metadata_json so we can merge cleanly in Python.
    rows = store._conn.execute("""
        SELECT e.id, e.src_qname, e.dst_name,
               e.extraction_source, e.metadata_json,
               f.path AS file_path
        FROM edges e
        JOIN symbols s ON s.qualified_name = e.src_qname
        JOIN files f ON s.file_id = f.id
        WHERE e.dst_qname IS NULL
    """).fetchall()

    updates: list[tuple] = []
    for r in rows:
        local_to_qname = resolved_per_file.get(r["file_path"])
        if not local_to_qname:
            continue
        target = local_to_qname.get(r["dst_name"])
        if not target:
            continue
        # Merge metadata: keep existing keys, layer resolver fields on top.
        try:
            md = json.loads(r["metadata_json"] or "{}")
            if not isinstance(md, dict):
                md = {}
        except json.JSONDecodeError:
            md = {}
        md["resolution_strategy"] = "import_alias"
        md["original_dst_name"] = r["dst_name"]
        md["selected_candidate"] = target

        prior_src = (r["extraction_source"] or "").strip()
        new_src = (
            f"{prior_src}+import-alias-resolver" if prior_src
            else "import-alias-resolver"
        )

        updates.append((
            target,
            int(PrecisionLevel.CODEGRAPH_RESOLVER),
            new_src,
            "Resolved via import alias",
            json.dumps(md),
            r["id"],
        ))

    if not updates:
        return 0

    with store.transaction() as cx:
        cx.executemany(
            "UPDATE edges SET dst_qname=?, "
            "precision_level=MAX(precision_level, ?), "
            "extraction_source=?, reason=?, metadata_json=? "
            "WHERE id=?",
            updates,
        )
    return len(updates)
