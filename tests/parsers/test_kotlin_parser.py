from __future__ import annotations

from pathlib import Path

from codegraphkb import CodeGraphKB
from codegraphkb.core.parsers.kotlin_parser import parse_kotlin
from codegraphkb.core.scanner import SourceFile


def _src(rel: str, content: str) -> SourceFile:
    return SourceFile(rel_path=rel, abs_path=Path(rel), language="kotlin",
                      content=content, content_hash="h", size_bytes=len(content))


def test_kotlin_extracts_classes_functions_methods_imports_calls_and_constants() -> None:
    code = """
package com.example.auth

import com.example.jwt.GenerateJwt

data class LoginRequest(val userId: String)

class SessionService {
    companion object {
        const val DEFAULT_TTL: Int = 60
    }

    fun createSession(userId: String): String {
        val token = generateJwt(userId)
        saveSession(userId, token)
        return token
    }
}

fun saveSession(userId: String, token: String) {}
"""
    result = parse_kotlin(_src("src/Auth.kt", code))
    qnames = {s.qualified_name: s.kind for s in result.symbols}
    assert qnames["com.example.auth.LoginRequest"] == "class"
    assert qnames["com.example.auth.SessionService"] == "class"
    assert qnames["com.example.auth.SessionService.createSession"] == "method"
    assert qnames["com.example.auth.saveSession"] == "function"
    assert qnames["com.example.auth.SessionService.DEFAULT_TTL"] == "constant"
    assert any(b.local_name == "GenerateJwt" for b in result.imports)
    calls = {
        e.dst_name for e in result.edges
        if e.edge_type == "CALLS"
        and e.src_qualified_name == "com.example.auth.SessionService.createSession"
    }
    assert {"generateJwt", "saveSession"} <= calls


def test_kotlin_extracts_spring_routes_and_tests() -> None:
    code = """
package com.example.auth

@RestController
@RequestMapping("/api/auth")
class AuthController(
    private val authService: AuthService
) {
    @PostMapping("/login")
    fun login(request: LoginRequest): LoginResponse {
        return authService.login(request)
    }

    @Test
    fun loginTest() {
        login(LoginRequest())
    }
}
"""
    result = parse_kotlin(_src("AuthController.kt", code))
    assert any(s.kind == "route" and s.qualified_name == "route::POST /api/auth/login" for s in result.symbols)
    assert any(
        e.edge_type == "ROUTES_TO"
        and e.src_qualified_name == "route::POST /api/auth/login"
        and e.dst_qname == "com.example.auth.AuthController.login"
        for e in result.edges
    )
    assert any(s.kind == "test_block" and s.qualified_name == "com.example.auth.AuthController.loginTest" for s in result.symbols)
    assert any(e.edge_type == "TESTS" and e.dst_qname == "com.example.auth.AuthController.login" for e in result.edges)


def test_indexer_processes_kotlin_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "App.kt").write_text("package demo\nfun main() { helper() }\nfun helper() {}\n", encoding="utf-8")
    kb = CodeGraphKB(repo)
    kb.index(force=True)
    store = kb._open_store()
    try:
        assert store.find_symbol("demo.main") is not None
        assert store.file_languages().get("kotlin") == 1
    finally:
        store.close()
