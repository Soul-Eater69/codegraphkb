"""Phase 4.3 — constant/config/env reads end-to-end."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from codegraphkb import CodeGraphKB
from codegraphkb.core.extractors.python.constant_reads import detect_constant_reads
from codegraphkb.core.extractors.python.config_reads import detect_config_reads
from codegraphkb.core.extractors.python.envvar import detect_env_vars
from codegraphkb.core.parsers.python_parser import parse_python
from codegraphkb.core.scanner import SourceFile


def _src(rel: str, content: str) -> SourceFile:
    return SourceFile(
        rel_path=rel, abs_path=Path(rel), language="python",
        content=content, content_hash="h", size_bytes=len(content),
    )


# ---------- constant reads ----------

def test_constant_read_emits_edge_to_module_constant() -> None:
    code = (
        "SECRET_FILES = ['.env']\n"
        "\n"
        "def scan_repo():\n"
        "    return SECRET_FILES\n"
    )
    src = _src("m.py", code)
    extract = parse_python(src)
    out = detect_constant_reads(src, extract)

    reads = [e for e in out.extra_edges if e.edge_type == "READS_CONSTANT"]
    assert len(reads) == 1
    e = reads[0]
    assert e.src_qualified_name == "m.scan_repo"
    assert e.dst_qname == "m.SECRET_FILES"
    assert e.dst_name == "SECRET_FILES"
    assert e.extraction_source == "extractor:constants"


def test_constant_read_skips_undefined_uppercase_names() -> None:
    code = "def f():\n    return SOME_UNDEFINED\n"
    src = _src("m.py", code)
    extract = parse_python(src)
    out = detect_constant_reads(src, extract)
    assert all(e.edge_type != "READS_CONSTANT" for e in out.extra_edges)


def test_constant_read_dedupes_multiple_references_in_one_function() -> None:
    code = (
        "BUDGET = 6000\n"
        "def f():\n"
        "    a = BUDGET\n"
        "    b = BUDGET\n"
        "    return a, b\n"
    )
    src = _src("m.py", code)
    extract = parse_python(src)
    out = detect_constant_reads(src, extract)
    reads = [e for e in out.extra_edges if e.edge_type == "READS_CONSTANT"]
    assert len(reads) == 1


# ---------- config reads ----------

def test_config_read_attribute() -> None:
    code = (
        "def use_settings():\n"
        "    return settings.DEBUG\n"
    )
    src = _src("m.py", code)
    extract = parse_python(src)
    out = detect_config_reads(src, extract)

    reads = [e for e in out.extra_edges if e.edge_type == "READS_CONFIG_KEY"]
    assert len(reads) == 1
    e = reads[0]
    assert e.src_qualified_name == "m.use_settings"
    assert e.dst_qname == "config::DEBUG"
    # Symbol is also synthesized:
    sym_qnames = {s.qualified_name for s in out.extra_symbols}
    assert "config::DEBUG" in sym_qnames


def test_config_read_subscript_and_get() -> None:
    code = (
        "def a():\n"
        "    return app.config['SECRET_KEY']\n"
        "def b():\n"
        "    return config.get('token_budget', 6000)\n"
    )
    src = _src("m.py", code)
    extract = parse_python(src)
    out = detect_config_reads(src, extract)

    dst_qnames = {e.dst_qname for e in out.extra_edges
                  if e.edge_type == "READS_CONFIG_KEY"}
    assert "config::SECRET_KEY" in dst_qnames
    assert "config::token_budget" in dst_qnames


def test_config_read_ignores_unknown_receivers() -> None:
    code = (
        "def f():\n"
        "    return user.email\n"   # `user` not in allowlist
    )
    src = _src("m.py", code)
    extract = parse_python(src)
    out = detect_config_reads(src, extract)
    assert all(e.edge_type != "READS_CONFIG_KEY" for e in out.extra_edges)


# ---------- env reads (regression: src_qname must be fully-qualified) ----------

def test_env_read_uses_qualified_function_name() -> None:
    code = (
        "import os\n"
        "\n"
        "def load_llm_config():\n"
        "    return os.getenv('ANTHROPIC_API_KEY')\n"
    )
    src = _src("settings/llm.py", code)
    extract = parse_python(src)
    out = detect_env_vars(src, extract)

    reads = [e for e in out.extra_edges if e.edge_type == "READS_ENV_VAR"]
    assert len(reads) == 1
    e = reads[0]
    # Before the fix this was the bare 'load_llm_config' — making the edge
    # un-joinable to the actual symbol row.
    assert e.src_qualified_name == "settings.llm.load_llm_config"
    assert e.dst_qname == "env::ANTHROPIC_API_KEY"


def test_env_read_for_environ_subscript() -> None:
    code = (
        "import os\n"
        "def f():\n"
        "    return os.environ['DATABASE_URL']\n"
    )
    src = _src("m.py", code)
    extract = parse_python(src)
    out = detect_env_vars(src, extract)
    reads = [e for e in out.extra_edges if e.edge_type == "READS_ENV_VAR"]
    assert reads and reads[0].dst_qname == "env::DATABASE_URL"


# ---------- end-to-end on a repo ----------

@pytest.fixture()
def constant_repo(tmp_path: Path) -> Path:
    """Repo where a function reads a module-level constant AND an env var."""
    repo = tmp_path / "crepo"
    repo.mkdir()
    (repo / "config.py").write_text(
        "import os\n"
        "\n"
        "SECRET_FILES = ['.env', '.npmrc']\n"
        "DEFAULT_BUDGET = 6000\n"
        "\n"
        "def load_secrets():\n"
        "    api_key = os.getenv('ANTHROPIC_API_KEY')\n"
        "    return SECRET_FILES, DEFAULT_BUDGET, api_key\n",
        encoding="utf-8",
    )
    return repo


def test_index_produces_constant_and_env_edges(constant_repo: Path) -> None:
    kb = CodeGraphKB(constant_repo)
    kb.index()

    store = kb._open_store()
    try:
        # SECRET_FILES read
        row = store._conn.execute("""
            SELECT dst_qname FROM edges
            WHERE src_qname='config.load_secrets' AND edge_type='READS_CONSTANT'
              AND dst_name='SECRET_FILES'
        """).fetchone()
        assert row and row["dst_qname"] == "config.SECRET_FILES"

        # ANTHROPIC_API_KEY env read
        row = store._conn.execute("""
            SELECT dst_qname FROM edges
            WHERE src_qname='config.load_secrets' AND edge_type='READS_ENV_VAR'
        """).fetchone()
        assert row and row["dst_qname"] == "env::ANTHROPIC_API_KEY"
    finally:
        store.close()


def test_doctor_surfaces_constant_and_config_counts(constant_repo: Path) -> None:
    kb = CodeGraphKB(constant_repo)
    kb.index()
    from codegraphkb.diagnostics import collect_doctor_report
    report = collect_doctor_report(kb)
    fo = report["framework_object_counts"]

    assert fo["constants"] >= 2
    assert fo["env_vars"] >= 1
    assert fo["reads_constant_edges"] >= 1
    assert fo["reads_env_var_edges"] >= 1
