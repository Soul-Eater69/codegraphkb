from __future__ import annotations

from pathlib import Path

from codegraphkb import CodeGraphKB
from codegraphkb.core.parsers.rust_parser import parse_rust
from codegraphkb.core.scanner import SourceFile


def _src(rel: str, content: str) -> SourceFile:
    return SourceFile(rel_path=rel, abs_path=Path(rel), language="rust",
                      content=content, content_hash="h", size_bytes=len(content))


def test_rust_extracts_types_impl_methods_imports_calls_and_constants() -> None:
    code = """
use crate::jwt::generate_jwt;
mod storage;

pub struct SessionService {}
pub enum Status { Active }
pub trait Store { fn save(&self); }
const DEFAULT_TTL: usize = 60;

impl SessionService {
    pub fn create_session(&self, user_id: &str) -> String {
        let token = generate_jwt(user_id);
        save_session(user_id, &token);
        token
    }
}
"""
    result = parse_rust(_src("src/session.rs", code))
    qnames = {s.qualified_name: s.kind for s in result.symbols}
    assert qnames["session::SessionService"] == "struct"
    assert qnames["session::Status"] == "enum"
    assert qnames["session::Store"] == "trait"
    assert qnames["session::DEFAULT_TTL"] == "constant"
    assert qnames["session::SessionService.create_session"] == "method"
    assert any(b.local_name == "generate_jwt" for b in result.imports)
    calls = {
        e.dst_name for e in result.edges
        if e.edge_type == "CALLS"
        and e.src_qualified_name == "session::SessionService.create_session"
    }
    assert {"generate_jwt", "save_session"} <= calls


def test_rust_extracts_tests_and_test_edges() -> None:
    code = """
fn create_session() -> String {
    "ok".to_string()
}

#[test]
fn test_create_session() {
    create_session();
}
"""
    result = parse_rust(_src("session.rs", code))
    assert any(s.kind == "function" and s.qualified_name == "session::create_session" for s in result.symbols)
    assert any(s.kind == "test_block" and s.qualified_name == "session::test_create_session" for s in result.symbols)
    assert any(e.edge_type == "TESTS" and e.dst_qname == "session::create_session" for e in result.edges)


def test_indexer_processes_rust_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.rs").write_text("fn main() { helper(); }\nfn helper() {}\n", encoding="utf-8")
    kb = CodeGraphKB(repo)
    kb.index(force=True)
    store = kb._open_store()
    try:
        assert store.find_symbol("main") is None
        assert store.find_symbol("crate::main") is not None
        assert store.file_languages().get("rust") == 1
    finally:
        store.close()
