from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from codegraphkb import CodeGraphKB
from codegraphkb.cli import cli
from codegraphkb.core.languages import LanguageProviderRegistry
from codegraphkb.core.parsers.fallback import file_summary_fallback
from codegraphkb.core.scanner import SourceFile


def _src(rel: str, language: str, content: str) -> SourceFile:
    return SourceFile(
        rel_path=rel,
        abs_path=Path(rel),
        language=language,
        content=content,
        content_hash="h",
        size_bytes=len(content),
    )


def test_file_summary_fallback_symbol_shape() -> None:
    result = file_summary_fallback(_src("scripts/bootstrap.py", "python", "print('hi')\n"))
    assert len(result.symbols) == 1
    sym = result.symbols[0]
    assert sym.kind == "file_summary"
    assert sym.qualified_name == "file::scripts/bootstrap.py"
    assert sym.extras["fallback"] is True
    assert sym.extras["language"] == "python"


def test_indexer_adds_file_summary_when_parser_finds_no_symbols(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "bootstrap.py").write_text("print('boot')\nvalue = 1 + 2\n", encoding="utf-8")

    kb = CodeGraphKB(repo)
    stats = kb.index(force=True)
    assert stats.symbols == 1

    store = kb._open_store()
    try:
        syms = store.symbols_in_file("bootstrap.py")
        assert len(syms) == 1
        assert syms[0].kind == "file_summary"
        assert "file-level fallback" in syms[0].capsule
        assert store.get_meta("file_parser_fallback:bootstrap.py") == "true"
    finally:
        store.close()


def test_registry_adds_file_summary_for_unsupported_code_language() -> None:
    src = _src("legacy/tool.rb", "ruby", "puts 'hello'\n")
    result, choice = LanguageProviderRegistry.default().parse_and_extract(src)
    assert choice.provider_id == "none"
    assert choice.parser_backend == "fallback"
    assert choice.fallback_used is True
    assert result.symbols[0].kind == "file_summary"


def test_languages_cli_lists_multilanguage_support() -> None:
    result = CliRunner().invoke(cli, ["languages"])
    assert result.exit_code == 0
    output = result.output
    for lang in ("python", "javascript", "typescript", "java", "go", "csharp", "rust", "kotlin"):
        assert f"- {lang}:" in output
