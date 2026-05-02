"""Schema v4 object-role inference tests."""
from __future__ import annotations

from pathlib import Path

from codegraphkb import CodeGraphKB
from codegraphkb.core.store import GraphStore


def test_python_role_classifier_infers_handler_service_repository_test(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "pyrepo"
    _build_python_role_repo(repo)

    kb = CodeGraphKB(repo)
    stats = kb.index(force=True)

    assert stats.roles_built > 0
    assert stats.roles_by_type.get("handler", 0) >= 1
    assert stats.roles_by_type.get("service", 0) >= 1
    assert stats.roles_by_type.get("repository", 0) >= 1
    assert stats.roles_by_type.get("test", 0) >= 1

    payload = kb.export_graph(view="symbols")
    create_user = _node_by_label(payload, "create_user")
    assert create_user is not None
    roles = create_user.get("metadata", {}).get("roles", [])
    assert any(role["role"] == "service" for role in roles)
    assert all(role["confidence"] > 0 for role in roles)
    assert any(role["reason"] for role in roles)


def test_typescript_role_classifier_infers_service_repository_client(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "tsrepo"
    _build_typescript_role_repo(repo)

    kb = CodeGraphKB(repo)
    kb.index(force=True)
    counts = kb.object_role_counts()

    assert counts.get("handler", 0) >= 1
    assert counts.get("service", 0) >= 1
    assert counts.get("repository", 0) >= 1
    assert counts.get("client", 0) >= 1

    store = GraphStore(kb.config.db_path)
    try:
        service_nodes = [
            node_id
            for node_id, roles in store.object_roles_by_node().items()
            if any(role["role"] == "service" for role in roles)
        ]
    finally:
        store.close()
    assert service_nodes


def test_node_details_and_stats_expose_roles(tmp_path: Path) -> None:
    repo = tmp_path / "pyrepo"
    _build_python_role_repo(repo)
    kb = CodeGraphKB(repo)
    kb.index(force=True)

    stats = kb.stats()
    assert stats["roles"].get("service", 0) >= 1

    store = GraphStore(kb.config.db_path)
    try:
        sym = store.find_symbols_by_name("create_user", limit=1)[0]
        roles = store.roles_for_node(f"symbol:{sym.qualified_name}")
    finally:
        store.close()

    assert roles
    assert roles[0]["role"] == "service"
    assert roles[0]["signals"]


def _build_python_role_repo(repo: Path) -> None:
    (repo / "app" / "routes").mkdir(parents=True, exist_ok=True)
    (repo / "app" / "services").mkdir(parents=True, exist_ok=True)
    (repo / "app" / "repositories").mkdir(parents=True, exist_ok=True)
    (repo / "tests").mkdir(parents=True, exist_ok=True)
    for path in (
        "app/__init__.py",
        "app/routes/__init__.py",
        "app/services/__init__.py",
        "app/repositories/__init__.py",
    ):
        (repo / path).write_text("", encoding="utf-8")
    (repo / "app" / "routes" / "users.py").write_text(
        "from app.services.user_service import create_user\n\n"
        "def create_user_route(payload):\n"
        "    return create_user(payload)\n",
        encoding="utf-8",
    )
    (repo / "app" / "services" / "user_service.py").write_text(
        "from app.repositories.user_repository import save_user\n\n"
        "def create_user(payload):\n"
        "    return save_user(payload)\n",
        encoding="utf-8",
    )
    (repo / "app" / "repositories" / "user_repository.py").write_text(
        "def save_user(user):\n"
        "    return user\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_users.py").write_text(
        "from app.services.user_service import create_user\n\n"
        "def test_create_user():\n"
        "    assert create_user({\"email\": \"a@example.com\"})\n",
        encoding="utf-8",
    )


def _build_typescript_role_repo(repo: Path) -> None:
    (repo / "src" / "routes").mkdir(parents=True, exist_ok=True)
    (repo / "src" / "services").mkdir(parents=True, exist_ok=True)
    (repo / "src" / "repositories").mkdir(parents=True, exist_ok=True)
    (repo / "src" / "clients").mkdir(parents=True, exist_ok=True)
    (repo / "src" / "routes" / "users.ts").write_text(
        "import { createUserService } from '../services/userService';\n"
        "export function createUserHandler(req: any) {\n"
        "  return createUserService(req.body);\n"
        "}\n",
        encoding="utf-8",
    )
    (repo / "src" / "services" / "userService.ts").write_text(
        "import { saveUserRepository } from '../repositories/userRepository';\n"
        "export function createUserService(payload: any) {\n"
        "  return saveUserRepository(payload);\n"
        "}\n",
        encoding="utf-8",
    )
    (repo / "src" / "repositories" / "userRepository.ts").write_text(
        "export function saveUserRepository(user: any) {\n"
        "  return prisma.user.create({ data: user });\n"
        "}\n",
        encoding="utf-8",
    )
    (repo / "src" / "clients" / "paymentClient.ts").write_text(
        "export async function paymentClient() {\n"
        "  return fetch('https://payments.example.test');\n"
        "}\n",
        encoding="utf-8",
    )


def _node_by_label(payload: dict, label: str) -> dict | None:
    for node in payload.get("nodes", []):
        if node.get("label") == label:
            return node
    return None

