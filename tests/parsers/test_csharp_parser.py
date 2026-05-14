from __future__ import annotations

from pathlib import Path

from codegraphkb import CodeGraphKB
from codegraphkb.core.parsers.csharp_parser import parse_csharp
from codegraphkb.core.scanner import SourceFile


def _src(rel: str, content: str) -> SourceFile:
    return SourceFile(rel_path=rel, abs_path=Path(rel), language="csharp",
                      content=content, content_hash="h", size_bytes=len(content))


def test_csharp_extracts_types_methods_properties_constants_and_calls() -> None:
    code = """
using App.Auth.Services;

namespace App.Auth;

public interface IAuthService {}
public class AuthController : ControllerBase, IAuthController
{
    public const string RouteName = "auth";
    public string Name { get; set; }

    public AuthController() {}

    public IActionResult Login(LoginRequest request)
    {
        return Ok(_authService.Login(request));
    }
}
"""
    result = parse_csharp(_src("AuthController.cs", code))
    qnames = {s.qualified_name: s.kind for s in result.symbols}
    assert qnames["App.Auth.IAuthService"] == "interface"
    assert qnames["App.Auth.AuthController"] == "class"
    assert qnames["App.Auth.AuthController.Login"] == "method"
    assert qnames["App.Auth.AuthController.Name"] == "property"
    assert qnames["App.Auth.AuthController.RouteName"] == "constant"
    assert any(b.local_name == "Services" for b in result.imports)
    assert ("EXTENDS", "ControllerBase") in {(e.edge_type, e.dst_name) for e in result.edges}
    assert ("IMPLEMENTS", "IAuthController") in {(e.edge_type, e.dst_name) for e in result.edges}
    calls = {e.dst_name for e in result.edges if e.edge_type == "CALLS"}
    assert "_authService.Login" in calls


def test_csharp_extracts_aspnet_routes_and_tests() -> None:
    code = """
namespace App.Auth;

[ApiController]
[Route("api/auth")]
public class AuthController : ControllerBase
{
    [HttpPost("login")]
    public IActionResult Login(LoginRequest request)
    {
        return Ok(_authService.Login(request));
    }

    [Fact]
    public void LoginReturnsOk()
    {
        Login(new LoginRequest());
    }
}
"""
    result = parse_csharp(_src("AuthController.cs", code))
    assert any(s.kind == "route" and s.qualified_name == "route::POST /api/auth/login" for s in result.symbols)
    assert any(
        e.edge_type == "ROUTES_TO"
        and e.src_qualified_name == "route::POST /api/auth/login"
        and e.dst_qname == "App.Auth.AuthController.Login"
        for e in result.edges
    )
    assert any(s.kind == "test_block" and s.qualified_name == "App.Auth.AuthController.LoginReturnsOk" for s in result.symbols)
    assert any(e.edge_type == "TESTS" and e.dst_qname == "App.Auth.AuthController.Login" for e in result.edges)


def test_indexer_processes_csharp_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Program.cs").write_text(
        "namespace Demo;\npublic class Program { public void Run() {} }\n",
        encoding="utf-8",
    )
    kb = CodeGraphKB(repo)
    kb.index(force=True)
    store = kb._open_store()
    try:
        assert store.find_symbol("Demo.Program") is not None
        assert store.file_languages().get("csharp") == 1
    finally:
        store.close()
