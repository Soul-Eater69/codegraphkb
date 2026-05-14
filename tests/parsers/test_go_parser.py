from __future__ import annotations

from pathlib import Path

from codegraphkb import CodeGraphKB
from codegraphkb.core.parsers.go_parser import parse_go
from codegraphkb.core.scanner import SourceFile


def _src(rel: str, content: str) -> SourceFile:
    return SourceFile(rel_path=rel, abs_path=Path(rel), language="go",
                      content=content, content_hash="h", size_bytes=len(content))


def test_go_extracts_struct_functions_methods_imports_and_calls() -> None:
    code = """
package auth

import (
    "net/http"
    jwt "example.com/app/jwt"
)

type SessionService struct {}
type Store interface { Save(id string) }

const DefaultTTL = 60

func GenerateJWT(userID string) string { return jwt.Sign(userID) }

func (s *SessionService) CreateSession(userID string) string {
    token := GenerateJWT(userID)
    SaveSession(userID, token)
    return token
}
"""
    result = parse_go(_src("internal/auth/session.go", code))
    qnames = {s.qualified_name: s.kind for s in result.symbols}
    assert qnames["auth.SessionService"] == "struct"
    assert qnames["auth.Store"] == "interface"
    assert qnames["auth.GenerateJWT"] == "function"
    assert qnames["auth.SessionService.CreateSession"] == "method"
    assert qnames["auth.DefaultTTL"] == "constant"
    assert any(b.local_name == "http" and b.source_module == "net/http" for b in result.imports)
    assert any(b.local_name == "jwt" for b in result.imports)

    calls = {
        e.dst_name for e in result.edges
        if e.edge_type == "CALLS" and e.src_qualified_name == "auth.SessionService.CreateSession"
    }
    assert {"GenerateJWT", "SaveSession"} <= calls


def test_go_extracts_http_routes_and_tests() -> None:
    code = """
package auth

import "testing"

func LoginHandler(w http.ResponseWriter, r *http.Request) {}
func CreateUser(w http.ResponseWriter, r *http.Request) {}
func HealthHandler(w http.ResponseWriter, r *http.Request) {}

func routes(router Router) {
    router.GET("/login", LoginHandler)
    router.POST("/users", CreateUser)
    http.HandleFunc("/health", HealthHandler)
}

func TestCreateUser(t *testing.T) {
    CreateUser(nil, nil)
}
"""
    result = parse_go(_src("auth/routes.go", code))
    routes = {s.qualified_name for s in result.symbols if s.kind == "route"}
    assert "route::GET /login" in routes
    assert "route::POST /users" in routes
    assert "route::ANY /health" in routes
    assert any(
        e.edge_type == "ROUTES_TO"
        and e.src_qualified_name == "route::POST /users"
        and e.dst_qname == "auth.CreateUser"
        for e in result.edges
    )
    assert any(s.kind == "test_block" and s.qualified_name == "auth.TestCreateUser" for s in result.symbols)
    assert any(e.edge_type == "TESTS" and e.dst_qname == "auth.CreateUser" for e in result.edges)


def test_indexer_processes_go_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.go").write_text("package main\nfunc main() { helper() }\nfunc helper() {}\n", encoding="utf-8")

    kb = CodeGraphKB(repo)
    kb.index(force=True)
    store = kb._open_store()
    try:
        assert store.find_symbol("main.main") is not None
        assert store.file_languages().get("go") == 1
    finally:
        store.close()
