"""Phase 5A structured parameter tests."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from codegraphkb import CodeGraphKB
from codegraphkb.core.graph_schema import PrecisionLevel
from codegraphkb.core.semantic.merge import SEMANTIC_BACKEND_ID, merge_semantic_result
from codegraphkb.core.semantic.protocol import (
    SemanticFileResult,
    SemanticParameter,
    SemanticResult,
    SemanticSymbol,
)
from codegraphkb.core.store import GraphStore


REPO_ROOT = Path(__file__).resolve().parent.parent
HELPER_DIST = REPO_ROOT / "helpers" / "ts-semantic" / "dist" / "index.js"
HELPER_BUILT = HELPER_DIST.exists() and shutil.which("node") is not None
HELPER_SKIP = "TypeScript semantic helper not built or Node unavailable"


def test_python_parameters_are_indexed_and_exported(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text(
        "def get_session():\n"
        "    return None\n\n"
        "def create_user(payload: UserCreate, notify: bool = True, "
        "*tags: str, session: Session = get_session(), **extra: str) -> UserOut:\n"
        "    return payload\n\n"
        "def edge_case(a, b: int = 1, *args, c: str, d=None, **kwargs) -> bool:\n"
        "    return True\n\n"
        "class UserService:\n"
        "    def save(self, user: UserCreate, retries: int = 3) -> UserOut:\n"
        "        return user\n",
        encoding="utf-8",
    )

    kb = CodeGraphKB(repo)
    kb.index(force=True)

    store = GraphStore(kb.config.db_path)
    try:
        params = store.parameters_for_symbol("app.create_user")
        edge_case_params = store.parameters_for_symbol("app.edge_case")
        method_params = store.parameters_for_symbol("app.UserService.save")
    finally:
        store.close()

    assert [p["name"] for p in params] == ["payload", "notify", "tags", "session", "extra"]
    assert params[0]["declared_type"] == "UserCreate"
    assert params[1]["default_value"] == "True"
    assert params[1]["is_optional"] is True
    assert params[2]["is_variadic"] is True
    assert params[4]["metadata"]["param_kind"] == "kwarg"
    assert [p["name"] for p in edge_case_params] == [
        "a",
        "b",
        "args",
        "c",
        "d",
        "kwargs",
    ]
    assert edge_case_params[1]["declared_type"] == "int"
    assert edge_case_params[1]["default_value"] == "1"
    assert edge_case_params[1]["is_optional"] is True
    assert edge_case_params[2]["is_variadic"] is True
    assert edge_case_params[3]["declared_type"] == "str"
    assert edge_case_params[3]["is_optional"] is False
    assert edge_case_params[4]["default_value"] == "None"
    assert edge_case_params[4]["is_optional"] is True
    assert edge_case_params[5]["metadata"]["param_kind"] == "kwarg"
    assert [p["name"] for p in method_params] == ["user", "retries"]

    payload = kb.export_graph(view="symbols")
    node = _node(payload, "app.create_user")
    assert node is not None
    assert node["metadata"]["parameters"][0]["name"] == "payload"


def test_typescript_syntax_parameters_are_indexed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "users.ts").write_text(
        "export function createUser(payload: UserCreate, notify = true, "
        "...tags: string[]): Promise<UserOut> {\n"
        "  return Promise.resolve({} as UserOut);\n"
        "}\n\n"
        "export const updateUser = (id: string, patch?: UserPatch): UserOut => {\n"
        "  return {} as UserOut;\n"
        "};\n",
        encoding="utf-8",
    )

    kb = CodeGraphKB(repo)
    kb.index(force=True, parser="regex")

    store = GraphStore(kb.config.db_path)
    try:
        create_params = store.parameters_for_symbol("users.createUser")
        update_params = store.parameters_for_symbol("users.updateUser")
    finally:
        store.close()

    assert [p["name"] for p in create_params] == ["payload", "notify", "tags"]
    assert create_params[0]["declared_type"] == "UserCreate"
    assert create_params[1]["default_value"] == "true"
    assert create_params[2]["is_variadic"] is True
    assert create_params[2]["declared_type"] == "string[]"
    assert [p["declared_type"] for p in update_params] == ["string", "UserPatch"]
    assert update_params[1]["is_optional"] is True


def test_semantic_merge_replaces_syntax_parameters_with_semantic_precision(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "module.py").write_text(
        "def helper(payload):\n"
        "    return payload\n",
        encoding="utf-8",
    )
    kb = CodeGraphKB(repo)
    kb.index(force=True)

    semantic = SemanticResult(
        language="typescript",
        adapter=SEMANTIC_BACKEND_ID,
        adapter_version="0.2.0",
        repo_path=str(repo),
        files=[
            SemanticFileResult(
                path="module.py",
                symbols=[
                    SemanticSymbol(
                        id="module.py::module.helper",
                        name="helper",
                        kind="function",
                        qualified_name="module.helper",
                        signature="helper(payload: UserCreate): UserOut",
                        return_type="UserOut",
                        parameters=[
                            SemanticParameter(
                                owner_symbol="module.helper",
                                name="payload",
                                position=0,
                                declared_type="UserCreate",
                                inferred_type="UserCreate",
                                confidence=0.95,
                            )
                        ],
                    )
                ],
            )
        ],
    )

    store = GraphStore(kb.config.db_path)
    try:
        stats = merge_semantic_result(store, semantic, backend_version="0.2.0")
        params = store.parameters_for_symbol("module.helper")
    finally:
        store.close()

    assert stats.parameters_merged == 1
    assert params[0]["declared_type"] == "UserCreate"
    assert params[0]["precision_level"] == int(PrecisionLevel.LANGUAGE_SEMANTIC)
    assert params[0]["extraction_source"] == SEMANTIC_BACKEND_ID


def test_empty_semantic_parameters_do_not_wipe_syntax_parameters(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "module.py").write_text(
        "def helper(payload: UserCreate) -> UserOut:\n"
        "    return payload\n",
        encoding="utf-8",
    )
    kb = CodeGraphKB(repo)
    kb.index(force=True)

    semantic = SemanticResult(
        language="typescript",
        adapter=SEMANTIC_BACKEND_ID,
        adapter_version="0.2.0",
        repo_path=str(repo),
        files=[
            SemanticFileResult(
                path="module.py",
                symbols=[
                    SemanticSymbol(
                        id="module.py::module.helper",
                        name="helper",
                        kind="function",
                        qualified_name="module.helper",
                        signature="helper(payload: UserCreate): UserOut",
                        return_type="UserOut",
                        parameters=[],
                    )
                ],
            )
        ],
    )

    store = GraphStore(kb.config.db_path)
    try:
        before = store.parameters_for_symbol("module.helper")
        stats = merge_semantic_result(store, semantic, backend_version="0.2.0")
        after = store.parameters_for_symbol("module.helper")
    finally:
        store.close()

    assert before
    assert stats.parameters_merged == 0
    assert after == before


def test_semantic_parameters_are_not_stored_for_missing_symbol(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "module.py").write_text(
        "def helper(payload):\n"
        "    return payload\n",
        encoding="utf-8",
    )
    kb = CodeGraphKB(repo)
    kb.index(force=True)

    semantic = SemanticResult(
        language="typescript",
        adapter=SEMANTIC_BACKEND_ID,
        adapter_version="0.2.0",
        repo_path=str(repo),
        files=[
            SemanticFileResult(
                path="module.py",
                symbols=[
                    SemanticSymbol(
                        id="module.py::module.helper",
                        name="helper",
                        kind="function",
                        qualified_name="module.helper",
                        parameters=[
                            SemanticParameter(
                                owner_symbol="module.helper",
                                name="payload",
                                position=0,
                                declared_type="UserCreate",
                            )
                        ],
                    ),
                    SemanticSymbol(
                        id="module.py::module.missing",
                        name="missing",
                        kind="function",
                        qualified_name="module.missing",
                        parameters=[
                            SemanticParameter(
                                owner_symbol="module.missing",
                                name="ghost",
                                position=0,
                                declared_type="Ghost",
                            )
                        ],
                    ),
                ],
            )
        ],
    )

    store = GraphStore(kb.config.db_path)
    try:
        stats = merge_semantic_result(store, semantic, backend_version="0.2.0")
        existing = store.parameters_for_symbol("module.helper")
        missing = store.parameters_for_symbol("module.missing")
    finally:
        store.close()

    assert stats.parameters_merged == 1
    assert existing[0]["name"] == "payload"
    assert missing == []


def test_incremental_reindex_removes_parameters_for_renamed_symbol(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "app.py"
    source.write_text(
        "def old_name(x: int):\n"
        "    return x\n",
        encoding="utf-8",
    )
    kb = CodeGraphKB(repo)
    kb.index(force=True)

    source.write_text(
        "def new_name(y: str):\n"
        "    return y\n",
        encoding="utf-8",
    )
    kb.index(force=True)

    store = GraphStore(kb.config.db_path)
    try:
        old_params = store.parameters_for_symbol("app.old_name")
        new_params = store.parameters_for_symbol("app.new_name")
    finally:
        store.close()

    assert old_params == []
    assert [p["name"] for p in new_params] == ["y"]
    assert new_params[0]["declared_type"] == "str"


def test_index_prunes_legacy_orphan_parameters(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text(
        "def kept(x: int):\n"
        "    return x\n",
        encoding="utf-8",
    )
    kb = CodeGraphKB(repo)
    kb.index(force=True)

    store = GraphStore(kb.config.db_path)
    try:
        store.replace_parameters_for_symbol(
            "app.ghost",
            [{"name": "ghost", "position": 0, "declared_type": "Ghost"}],
        )
        assert store.parameters_for_symbol("app.ghost")
    finally:
        store.close()

    kb.index(force=True)

    store = GraphStore(kb.config.db_path)
    try:
        assert store.parameters_for_symbol("app.ghost") == []
        assert store.parameters_for_symbol("app.kept")
    finally:
        store.close()


@pytest.mark.skipif(not HELPER_BUILT, reason=HELPER_SKIP)
def test_typescript_helper_emits_structured_parameters(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "service.ts").write_text(
        "export function createUser(payload: UserCreate, notify?: boolean): Promise<UserOut> {\n"
        "  return Promise.resolve({} as UserOut);\n"
        "}\n"
        "export class S {\n"
        "  constructor(private repo: Repo) {}\n"
        "  async create(payload: UserCreate): Promise<UserOut> {\n"
        "    return Promise.resolve({} as UserOut);\n"
        "  }\n"
        "}\n"
        "export function f(a: string, b?: number, c = true, ...rest: string[]): Promise<User> {\n"
        "  return Promise.resolve({} as User);\n"
        "}\n",
        encoding="utf-8",
    )

    proc = subprocess.run(
        ["node", str(HELPER_DIST), "--repo", str(repo), "--json"],
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    symbols = [
        sym
        for file_result in data["files"]
        for sym in file_result["symbols"]
        if sym["qualified_name"] == "service.createUser"
    ]
    assert symbols
    assert symbols[0]["return_type"] == "Promise<UserOut>"
    assert [p["name"] for p in symbols[0]["parameters"]] == ["payload", "notify"]
    assert symbols[0]["parameters"][0]["declared_type"] == "UserCreate"
    assert symbols[0]["parameters"][1]["is_optional"] is True

    by_qname = {
        sym["qualified_name"]: sym
        for file_result in data["files"]
        for sym in file_result["symbols"]
    }
    constructor_params = by_qname["service.S.constructor"]["parameters"]
    method_params = by_qname["service.S.create"]["parameters"]
    f_params = by_qname["service.f"]["parameters"]
    assert constructor_params[0]["name"] == "repo"
    assert constructor_params[0]["declared_type"] == "Repo"
    assert method_params[0]["name"] == "payload"
    assert method_params[0]["declared_type"] == "UserCreate"
    assert by_qname["service.S.create"]["return_type"] == "Promise<UserOut>"
    assert [p["name"] for p in f_params] == ["a", "b", "c", "rest"]
    assert f_params[1]["is_optional"] is True
    assert f_params[2]["default_value"] == "true"
    assert f_params[2]["is_optional"] is True
    assert f_params[3]["is_variadic"] is True


def _node(payload: dict, qname: str) -> dict | None:
    node_id = f"symbol:{qname}"
    for node in payload.get("nodes", []):
        if node.get("id") == node_id:
            return node
    return None
