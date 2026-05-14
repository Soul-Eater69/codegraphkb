from __future__ import annotations

from pathlib import Path

from codegraphkb import CodeGraphKB


def test_multilanguage_beta_files_index_and_retrieve(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "internal" / "auth").mkdir(parents=True)
    (repo / "src").mkdir()
    (repo / "controllers").mkdir()

    (repo / "internal" / "auth" / "session.go").write_text(
        "package auth\n\n"
        "type SessionService struct {}\n"
        "const DefaultTTL = 60\n"
        "func GenerateJWT(userID string) string { return userID }\n"
        "func (s *SessionService) CreateSession(userID string) string {\n"
        "    token := GenerateJWT(userID)\n"
        "    return token\n"
        "}\n",
        encoding="utf-8",
    )
    (repo / "controllers" / "AuthController.cs").write_text(
        "namespace App.Auth;\n"
        "public class AuthController : ControllerBase\n"
        "{\n"
        "    public const string RouteName = \"auth\";\n"
        "    public IActionResult Login(LoginRequest request)\n"
        "    {\n"
        "        return Ok(_authService.Login(request));\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    (repo / "src" / "session.rs").write_text(
        "pub struct SessionService {}\n"
        "const DEFAULT_TTL: usize = 60;\n"
        "impl SessionService {\n"
        "    pub fn create_session(&self, user_id: &str) -> String {\n"
        "        generate_jwt(user_id)\n"
        "    }\n"
        "}\n"
        "fn generate_jwt(user_id: &str) -> String { user_id.to_string() }\n",
        encoding="utf-8",
    )
    (repo / "src" / "AuthController.kt").write_text(
        "package com.example.auth\n\n"
        "class SessionService {\n"
        "    companion object { const val DEFAULT_TTL: Int = 60 }\n"
        "    fun createSession(userId: String): String {\n"
        "        return generateJwt(userId)\n"
        "    }\n"
        "}\n"
        "fun generateJwt(userId: String): String { return userId }\n",
        encoding="utf-8",
    )

    kb = CodeGraphKB(repo)
    kb.index(force=True)

    stats = kb.stats()
    assert stats["languages"].get("go") == 1
    assert stats["languages"].get("csharp") == 1
    assert stats["languages"].get("rust") == 1
    assert stats["languages"].get("kotlin") == 1
    assert stats["symbols"] >= 12
    assert stats["edges"] >= 4

    store = kb._open_store()
    try:
        assert store.find_symbol("auth.SessionService.CreateSession") is not None
        assert store.find_symbol("App.Auth.AuthController.Login") is not None
        assert store.find_symbol("session::SessionService.create_session") is not None
        assert store.find_symbol("com.example.auth.SessionService.createSession") is not None
    finally:
        store.close()

    pack = kb.retrieve_context("create session login token", retrieval="bm25")
    titles = " ".join(item.title for item in pack.items)
    assert "CreateSession" in titles or "create_session" in titles or "createSession" in titles
