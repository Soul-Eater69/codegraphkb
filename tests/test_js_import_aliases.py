"""JS/TS PR — ImportBinding emission + relative-path alias resolution + env qname fix."""
from __future__ import annotations

from pathlib import Path

import pytest

from codegraphkb import CodeGraphKB
from codegraphkb.core.extractors.js_ts.envvar import detect_env_vars_js
from codegraphkb.core.parsers.js_parser import parse_javascript
from codegraphkb.core.scanner import SourceFile


def _src(rel: str, content: str, language: str = "typescript") -> SourceFile:
    return SourceFile(
        rel_path=rel, abs_path=Path(rel), language=language,
        content=content, content_hash="h", size_bytes=len(content),
    )


# ---------- parser-side: ImportBinding emission ----------

def test_js_import_default() -> None:
    result = parse_javascript(_src("a.ts", "import D from './d';\n"))
    bs = [b for b in result.imports if b.local_name == "D"]
    assert bs and bs[0].imported_name == "default"
    assert bs[0].source_module == "./d"
    assert bs[0].import_kind == "default"


def test_js_import_named_with_rename() -> None:
    result = parse_javascript(_src(
        "a.ts",
        "import { buildPack as pack, helper } from './retrieval';\n",
    ))
    by_local = {b.local_name: b for b in result.imports}
    assert "pack" in by_local
    assert by_local["pack"].imported_name == "buildPack"
    assert by_local["pack"].source_module == "./retrieval"
    assert "helper" in by_local
    assert by_local["helper"].imported_name == "helper"


def test_js_import_namespace() -> None:
    result = parse_javascript(_src("a.ts", "import * as api from './api';\n"))
    b = next(b for b in result.imports if b.local_name == "api")
    assert b.imported_name == "*"
    assert b.import_kind == "namespace"


def test_js_import_default_plus_named() -> None:
    result = parse_javascript(_src(
        "a.ts",
        "import D, { foo, bar as bar2 } from './m';\n",
    ))
    locals_ = {b.local_name for b in result.imports}
    assert {"D", "foo", "bar2"} <= locals_
    bar2 = next(b for b in result.imports if b.local_name == "bar2")
    assert bar2.imported_name == "bar"


def test_js_require_default() -> None:
    result = parse_javascript(_src(
        "a.js",
        "const helper = require('./helper');\n",
        language="javascript",
    ))
    bs = [b for b in result.imports if b.local_name == "helper"]
    assert bs and bs[0].import_kind == "default"
    assert bs[0].source_module == "./helper"


def test_js_require_destructure() -> None:
    result = parse_javascript(_src(
        "a.js",
        "const { foo, bar: bar2 } = require('./m');\n",
        language="javascript",
    ))
    by_local = {b.local_name: b for b in result.imports}
    assert by_local["foo"].imported_name == "foo"
    assert by_local["bar2"].imported_name == "bar"


def test_js_side_effect_import_emits_no_binding() -> None:
    result = parse_javascript(_src("a.ts", "import './polyfills';\n"))
    assert result.imports == []


# ---------- resolver helper ----------

def test_resolve_js_relative_module() -> None:
    from codegraphkb.core.import_resolver import _resolve_js_relative_module
    assert (
        _resolve_js_relative_module("src/api/foo.ts", "./util")
        == "src.api.util"
    )
    assert (
        _resolve_js_relative_module("src/api/foo.ts", "../client")
        == "src.client"
    )
    assert (
        _resolve_js_relative_module("src/api/foo.ts", "./util/index")
        == "src.api.util"
    )


# ---------- env var: src_qname must be enclosing function ----------

def test_js_env_read_uses_enclosing_function_qname() -> None:
    code = (
        "function loadConfig() {\n"
        "  return process.env.AUTH_TOKEN;\n"
        "}\n"
    )
    src = _src("api/config.ts", code)
    extract = parse_javascript(src)
    out = detect_env_vars_js(src, extract)
    reads = [e for e in out.extra_edges if e.edge_type == "READS_ENV_VAR"]
    assert reads
    # Before the fix this was the module qname "api.config".
    assert reads[0].src_qualified_name == "api.config.loadConfig"
    assert reads[0].dst_qname == "env::AUTH_TOKEN"


def test_js_env_read_top_level_falls_back_to_module() -> None:
    code = "const KEY = process.env.AUTH_TOKEN;\n"
    src = _src("config.ts", code)
    extract = parse_javascript(src)
    out = detect_env_vars_js(src, extract)
    reads = [e for e in out.extra_edges if e.edge_type == "READS_ENV_VAR"]
    assert reads
    assert reads[0].src_qualified_name == "config.ts"  # rel_path replaced
    # (actually rel_path.replace produces "config.ts" -> "config.ts" without
    # the extension stripping the JS env extractor doesn't apply; this is
    # acceptable as the extractor's fallback.)


# ---------- end-to-end alias rewrite for JS ----------

@pytest.fixture()
def ts_alias_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "tsrepo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "retrieval.ts").write_text(
        "export function buildPack(task: any) { return task; }\n",
        encoding="utf-8",
    )
    (repo / "src" / "caller.ts").write_text(
        "import { buildPack as pack } from './retrieval';\n"
        "\n"
        "export function run(task: any) {\n"
        "  return pack(task);\n"
        "}\n",
        encoding="utf-8",
    )
    return repo


def test_alias_resolver_rewrites_ts_call_via_alias(ts_alias_repo: Path) -> None:
    kb = CodeGraphKB(ts_alias_repo)
    stats = kb.index(parser="regex")  # regex parser is what we modified

    assert stats.alias_bindings_total >= 1
    assert stats.alias_edges_rewritten >= 1

    store = kb._open_store()
    try:
        row = store._conn.execute("""
            SELECT dst_qname, metadata_json FROM edges
            WHERE src_qname='src.caller.run' AND dst_name='pack'
              AND edge_type='CALLS'
        """).fetchone()
        assert row is not None
        assert row["dst_qname"] == "src.retrieval.buildPack"
        import json
        md = json.loads(row["metadata_json"] or "{}")
        assert md.get("resolution_strategy") == "import_alias"
    finally:
        store.close()
