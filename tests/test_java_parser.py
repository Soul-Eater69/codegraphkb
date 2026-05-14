"""Java regex parser + end-to-end indexing on a small Java fixture."""
from __future__ import annotations

from pathlib import Path

import pytest

from codegraphkb import CodeGraphKB
from codegraphkb.core.parsers.java_parser import parse_java
from codegraphkb.core.scanner import SourceFile


def _src(rel: str, content: str) -> SourceFile:
    return SourceFile(
        rel_path=rel, abs_path=Path(rel), language="java",
        content=content, content_hash="h", size_bytes=len(content),
    )


# ---------- structural extraction ----------

def test_java_parses_package_class_method() -> None:
    code = (
        "package com.example.service;\n"
        "\n"
        "public class UserService {\n"
        "    public User findUser(String id) {\n"
        "        return new User();\n"
        "    }\n"
        "}\n"
    )
    result = parse_java(_src("UserService.java", code))

    classes = [s for s in result.symbols if s.kind == "class"]
    methods = [s for s in result.symbols if s.kind == "method"]

    assert any(c.qualified_name == "com.example.service.UserService" for c in classes)
    assert any(m.qualified_name == "com.example.service.UserService.findUser" for m in methods)
    find = next(m for m in methods if m.name == "findUser")
    assert find.parent_qualified_name == "com.example.service.UserService"
    assert find.return_type == "User"


def test_java_imports_emit_binding_and_edge() -> None:
    code = (
        "package com.example;\n"
        "import com.foo.Bar;\n"
        "import static com.foo.Util.method;\n"
        "import com.other.*;\n"
        "public class A {}\n"
    )
    result = parse_java(_src("A.java", code))

    # Bindings
    by_local = {b.local_name: b for b in result.imports}
    assert "Bar" in by_local
    assert by_local["Bar"].source_module == "com.foo"
    assert by_local["Bar"].import_kind == "named"
    assert "method" in by_local
    assert by_local["method"].source_module == "com.foo.Util"
    assert by_local["method"].import_kind == "static"

    # Star imports do not produce a binding (no single local name).
    assert all(b.local_name != "*" for b in result.imports)

    # IMPORTS edges exist for non-star too
    import_targets = {e.dst_name for e in result.edges if e.edge_type == "IMPORTS"}
    assert "com.foo.Bar" in import_targets
    assert "com.foo.Util.method" in import_targets


def test_java_extends_and_implements_edges() -> None:
    code = (
        "package com.x;\n"
        "import com.x.lib.BaseService;\n"
        "import com.x.lib.Auditable;\n"
        "import com.x.lib.Loggable;\n"
        "public class TokenService extends BaseService implements Auditable, Loggable {\n"
        "}\n"
    )
    result = parse_java(_src("TokenService.java", code))

    edge_pairs = {(e.edge_type, e.dst_name) for e in result.edges
                  if e.edge_type in {"EXTENDS", "IMPLEMENTS"}}
    assert ("EXTENDS", "BaseService") in edge_pairs
    assert ("IMPLEMENTS", "Auditable") in edge_pairs
    assert ("IMPLEMENTS", "Loggable") in edge_pairs


def test_java_interface_and_enum_symbols() -> None:
    code = (
        "package com.x;\n"
        "public interface Repository<T> { T find(String id); }\n"
        "public enum Status { ACTIVE, INACTIVE; }\n"
    )
    result = parse_java(_src("X.java", code))
    kinds = {s.qualified_name: s.kind for s in result.symbols}
    assert kinds.get("com.x.Repository") == "interface"
    assert kinds.get("com.x.Status") == "enum"


def test_java_constructor_and_static_constant() -> None:
    code = (
        "package com.x;\n"
        "public class Config {\n"
        "    public static final String DEFAULT_KEY = \"abc\";\n"
        "    public Config() {}\n"
        "    public Config(String s) {}\n"
        "}\n"
    )
    result = parse_java(_src("Config.java", code))

    constants = [s for s in result.symbols if s.kind == "constant"]
    ctors = [s for s in result.symbols if s.kind == "constructor"]

    assert any(c.qualified_name == "com.x.Config.DEFAULT_KEY" for c in constants)
    assert len(ctors) >= 2  # two constructors


def test_java_method_calls_inside_body() -> None:
    code = (
        "package com.x;\n"
        "public class Service {\n"
        "    public void doIt() {\n"
        "        helper();\n"
        "        sign(token);\n"
        "    }\n"
        "    public void helper() {}\n"
        "    public void sign(String t) {}\n"
        "}\n"
    )
    result = parse_java(_src("Service.java", code))

    calls = [e for e in result.edges
             if e.edge_type == "CALLS" and e.src_qualified_name == "com.x.Service.doIt"]
    dst = {c.dst_name for c in calls}
    assert "helper" in dst
    assert "sign" in dst


def test_java_extracts_spring_routes() -> None:
    code = (
        "package com.example.auth;\n"
        "import org.springframework.web.bind.annotation.PostMapping;\n"
        "@RestController\n"
        "@RequestMapping(\"/api/auth\")\n"
        "public class AuthController {\n"
        "    @PostMapping(\"/login\")\n"
        "    public LoginResponse login(@RequestBody LoginRequest request) {\n"
        "        return authService.login(request);\n"
        "    }\n"
        "}\n"
    )
    result = parse_java(_src("AuthController.java", code))

    assert any(
        s.kind == "route" and s.qualified_name == "route::POST /api/auth/login"
        for s in result.symbols
    )
    assert any(
        e.edge_type == "ROUTES_TO"
        and e.src_qualified_name == "route::POST /api/auth/login"
        and e.dst_qname == "com.example.auth.AuthController.login"
        for e in result.edges
    )
    calls = {e.dst_name for e in result.edges if e.edge_type == "CALLS"}
    assert "authService.login" in calls


def test_java_extracts_junit_tests() -> None:
    code = (
        "package com.example.auth;\n"
        "public class AuthServiceTest {\n"
        "    @Test\n"
        "    public void loginWorks() {\n"
        "        login();\n"
        "    }\n"
        "    public void login() {}\n"
        "}\n"
    )
    result = parse_java(_src("AuthServiceTest.java", code))
    assert any(
        s.kind == "test_block"
        and s.qualified_name == "com.example.auth.AuthServiceTest.loginWorks"
        for s in result.symbols
    )
    assert any(
        e.edge_type == "TESTS"
        and e.dst_qname == "com.example.auth.AuthServiceTest.login"
        for e in result.edges
    )


def test_java_annotations_captured_on_class() -> None:
    code = (
        "package com.x;\n"
        "@Service\n"
        "@Component\n"
        "public class FooService {}\n"
    )
    result = parse_java(_src("FooService.java", code))
    cls = next(s for s in result.symbols if s.qualified_name == "com.x.FooService")
    assert "Service" in cls.extras["annotations"]
    assert "Component" in cls.extras["annotations"]


def test_java_falls_back_to_path_qname_when_no_package() -> None:
    """Files in package-less default scope still get a unique qname."""
    code = "public class Loose {\n  public void run() {}\n}\n"
    result = parse_java(_src("standalone/Loose.java", code))
    # Module fallback is the dir path joined by dots.
    cls = next(s for s in result.symbols if s.name == "Loose")
    assert cls.qualified_name == "standalone.Loose"


# ---------- end-to-end indexing ----------

@pytest.fixture()
def java_repo(tmp_path: Path) -> Path:
    """A minimal Java repo: service calls a helper in the same class, and
    a separate class extends a base. Verifies indexer picks up Java files
    via the scanner and runs them through the language provider.
    """
    repo = tmp_path / "jrepo"
    pkg = repo / "com" / "example"
    pkg.mkdir(parents=True)
    (pkg / "Base.java").write_text(
        "package com.example;\n"
        "public class Base {\n"
        "    public void log(String msg) {}\n"
        "}\n",
        encoding="utf-8",
    )
    (pkg / "TokenService.java").write_text(
        "package com.example;\n"
        "public class TokenService extends Base {\n"
        "    public String issue() {\n"
        "        return sign();\n"
        "    }\n"
        "    public String sign() {\n"
        "        return \"sig\";\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    return repo


def test_indexer_processes_java_files(java_repo: Path) -> None:
    kb = CodeGraphKB(java_repo)
    stats = kb.index()
    assert stats.files_indexed >= 2
    # symbols include the two classes plus their methods
    assert stats.symbols >= 4

    store = kb._open_store()
    try:
        # Class qnames present
        rows = store._conn.execute(
            "SELECT qualified_name FROM symbols WHERE kind='class' ORDER BY qualified_name"
        ).fetchall()
        qnames = [r["qualified_name"] for r in rows]
        assert "com.example.Base" in qnames
        assert "com.example.TokenService" in qnames

        # EXTENDS edge resolved by unique-name pass
        ext = store._conn.execute(
            "SELECT dst_qname FROM edges WHERE src_qname='com.example.TokenService' "
            "AND edge_type='EXTENDS'"
        ).fetchone()
        assert ext and ext["dst_qname"] == "com.example.Base"

        # The intra-class call TokenService.issue -> sign should resolve to
        # TokenService.sign. Either file_scope or class_scope can produce
        # this — when there's only one ``sign`` in the file, file_scope wins
        # because it runs first; we just want the right target plus a
        # precise resolver tag (not the broad unique-name pass).
        call = store._conn.execute(
            "SELECT dst_qname, extraction_source FROM edges "
            "WHERE src_qname='com.example.TokenService.issue' AND dst_name='sign'"
        ).fetchone()
        assert call and call["dst_qname"] == "com.example.TokenService.sign"
        es = call["extraction_source"] or ""
        assert "edge-resolver:" in es
    finally:
        store.close()


def test_indexer_processes_java_imports(tmp_path: Path) -> None:
    """A Java import of an in-repo class should resolve via the alias resolver."""
    repo = tmp_path / "jrepo2"
    (repo / "com" / "lib").mkdir(parents=True)
    (repo / "com" / "app").mkdir(parents=True)
    (repo / "com" / "lib" / "Logger.java").write_text(
        "package com.lib;\n"
        "public class Logger {\n"
        "    public void info(String m) {}\n"
        "}\n",
        encoding="utf-8",
    )
    (repo / "com" / "app" / "Main.java").write_text(
        "package com.app;\n"
        "import com.lib.Logger;\n"
        "public class Main {\n"
        "    public void run() {\n"
        "        Logger l = new Logger();\n"
        "        l.info(\"hi\");\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )

    kb = CodeGraphKB(repo)
    stats = kb.index()
    assert stats.alias_bindings_resolved >= 1, (
        "Java import of com.lib.Logger should be resolved by the alias resolver"
    )

    store = kb._open_store()
    try:
        row = store._conn.execute(
            "SELECT target_qname FROM imports WHERE file_path LIKE '%Main.java' "
            "AND local_name='Logger'"
        ).fetchone()
        assert row and row["target_qname"] == "com.lib.Logger"
    finally:
        store.close()
