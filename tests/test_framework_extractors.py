"""Phase 3.2 — TypeScript / JavaScript framework extractor tests.

Each extractor is exercised via its fixture file. The extractor functions
operate on a single `(source, ExtractResult)` pair, so unit tests don't need
to stand up a full index — but we also run one end-to-end CodeGraphKB index
over the framework fixture tree to confirm the wiring + counts.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from codegraphkb import CodeGraphKB
from codegraphkb.core.extractors.base import (
    EDGE_CALLS_EXTERNAL,
    EDGE_FETCHES,
    EDGE_HANDLES_ROUTE,
    EDGE_QUERIES,
    EDGE_TESTS,
    EDGE_USES_MIDDLEWARE,
)
from codegraphkb.core.extractors.js_ts.express import detect_express
from codegraphkb.core.extractors.js_ts.fastify import detect_fastify
from codegraphkb.core.extractors.js_ts.fetch_axios import detect_fetch_axios
from codegraphkb.core.extractors.js_ts.jest_vitest import detect_jest_vitest
from codegraphkb.core.extractors.js_ts.nextjs import detect_nextjs
from codegraphkb.core.extractors.js_ts.prisma import detect_prisma
from codegraphkb.core.languages import LanguageProviderRegistry
from codegraphkb.core.parsers import ParserBackend
from codegraphkb.core.scanner import SourceFile
from codegraphkb.core.store import GraphStore


REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "examples" / "ts-frameworks"


def _load(rel: str) -> tuple[SourceFile, "ExtractResult"]:
    abs_path = FIXTURES / rel
    content = abs_path.read_text(encoding="utf-8")
    src = SourceFile(
        rel_path=rel.replace("\\", "/"),
        abs_path=abs_path,
        language="typescript" if rel.endswith((".ts", ".tsx")) else "javascript",
        content=content,
        content_hash="hash",
        size_bytes=len(content),
    )
    extract, _ = LanguageProviderRegistry.default(parser_backend=ParserBackend.REGEX) \
        .parse_and_extract(src)
    return src, extract


def _edges_of(extraction, edge_type: str) -> list:
    return [e for e in extraction.extra_edges if e.edge_type == edge_type]


# --------------------------------------------------------------------------
# Express
# --------------------------------------------------------------------------

def test_express_extracts_routes_with_handles_route_and_middleware() -> None:
    src, extract = _load("express/orders.routes.ts")
    out = detect_express(src, extract)

    routes = [s for s in out.extra_symbols if s.kind == "route"]
    paths = sorted(s.extras["path"] for s in routes)
    assert paths == ["/orders", "/orders/:id/cancel"]

    handles = _edges_of(out, EDGE_HANDLES_ROUTE)
    handler_names = sorted(e.dst_name for e in handles)
    assert handler_names == ["cancelOrderHandler", "cancelOrderHandler"]
    for edge in handles:
        assert edge.confidence >= 0.8
        assert edge.metadata.get("framework") == "express"
        assert edge.metadata.get("http_method") in {"GET", "POST"}

    middleware = _edges_of(out, EDGE_USES_MIDDLEWARE)
    assert any(e.dst_name == "authMiddleware" for e in middleware)


def test_express_skips_inline_handlers() -> None:
    code = "router.get('/x', (req, res) => res.json({}))\n"
    src = SourceFile(
        rel_path="x.ts", abs_path=Path("x.ts"), language="typescript",
        content=code, content_hash="h", size_bytes=len(code),
    )
    extract, _ = LanguageProviderRegistry.default(
        parser_backend=ParserBackend.REGEX,
    ).parse_and_extract(src)
    out = detect_express(src, extract)
    assert _edges_of(out, EDGE_HANDLES_ROUTE) == []


# --------------------------------------------------------------------------
# Fastify
# --------------------------------------------------------------------------

def test_fastify_extracts_method_and_route_object_forms() -> None:
    src, extract = _load("fastify/server.ts")
    out = detect_fastify(src, extract)

    routes = sorted((s.extras["http_method"], s.extras["path"])
                    for s in out.extra_symbols if s.kind == "route")
    assert ("GET", "/health") in routes
    assert ("POST", "/orders") in routes

    handles = _edges_of(out, EDGE_HANDLES_ROUTE)
    handler_names = sorted(e.dst_name for e in handles)
    assert handler_names == ["getHealth", "postOrder"]

    middleware = _edges_of(out, EDGE_USES_MIDDLEWARE)
    assert any(e.dst_name == "authPreHandler" for e in middleware)


# --------------------------------------------------------------------------
# Next.js
# --------------------------------------------------------------------------

def test_nextjs_app_route_emits_per_method_with_handler_qname() -> None:
    src, extract = _load("app/api/users/[id]/route.ts")
    out = detect_nextjs(src, extract)

    methods = sorted(s.extras["http_method"] for s in out.extra_symbols if s.kind == "route")
    assert methods == ["DELETE", "GET"]
    handles = _edges_of(out, EDGE_HANDLES_ROUTE)
    for edge in handles:
        # The handler qname stored in metadata must reference the file qname.
        resolved = edge.metadata.get("resolved_handler_qname", "")
        assert "users" in resolved


def test_nextjs_pages_api_emits_any_route() -> None:
    src, extract = _load("pages/api/health.ts")
    out = detect_nextjs(src, extract)
    routes = [s for s in out.extra_symbols if s.kind == "route"]
    assert len(routes) == 1
    assert routes[0].extras["http_method"] == "ANY"
    assert routes[0].extras["path"].endswith("/health")


# --------------------------------------------------------------------------
# Jest / Vitest
# --------------------------------------------------------------------------

def test_jest_vitest_extracts_blocks_and_emits_tests_edges() -> None:
    src, extract = _load("tests/orders.test.ts")
    out = detect_jest_vitest(src, extract)

    blocks = [s for s in out.extra_symbols if s.kind == "test_block"]
    labels = sorted(s.name for s in blocks)
    assert labels == ["cancels an order", "lists orders for a user", "orders service"]

    tests_edges = _edges_of(out, EDGE_TESTS)
    assert tests_edges, "expected TESTS edges from blocks to called targets"
    cancel_targets = {
        e.dst_name for e in tests_edges
        if e.metadata.get("block_label") == "cancels an order"
    }
    assert "cancelOrder" in cancel_targets


# --------------------------------------------------------------------------
# Prisma
# --------------------------------------------------------------------------

def test_prisma_extractor_emits_queries_from_caller_to_model() -> None:
    src, extract = _load("prisma/orders.service.ts")
    out = detect_prisma(src, extract)

    models = sorted(s.name for s in out.extra_symbols if s.kind == "model")
    assert "Order" in models and "Refund" in models

    queries = _edges_of(out, EDGE_QUERIES)
    pairs = {(e.src_qualified_name.rsplit(".", 1)[-1], e.dst_name) for e in queries}
    # cancelOrder QUERIES Order and Refund; listOrders QUERIES Order.
    assert ("cancelOrder", "Order") in pairs
    assert ("cancelOrder", "Refund") in pairs
    assert ("listOrders", "Order") in pairs
    for edge in queries:
        assert edge.metadata.get("framework") == "prisma"
        assert edge.metadata.get("operation") in {
            "findMany", "create", "update", "delete", "upsert",
            "createMany", "updateMany", "deleteMany",
        }


# --------------------------------------------------------------------------
# fetch / axios
# --------------------------------------------------------------------------

def test_fetch_axios_extractor_emits_fetches_and_calls_external() -> None:
    src, extract = _load("fetch/orders.client.ts")
    out = detect_fetch_axios(src, extract)

    consumers = {(s.extras["http_method"], s.extras["url"]) for s in out.extra_symbols
                 if s.kind == "api_consumer"}
    assert ("POST", "/api/orders") in consumers
    assert ("GET", "/api/orders") in consumers
    assert ("POST", "/api/orders/cancel") in consumers

    fetches = _edges_of(out, EDGE_FETCHES)
    assert fetches
    callers = {e.src_qualified_name.rsplit(".", 1)[-1] for e in fetches}
    assert "cancelOrderClient" in callers
    assert "postOrderAxios" in callers

    externals = _edges_of(out, EDGE_CALLS_EXTERNAL)
    assert externals, "expected CALLS_EXTERNAL edges alongside FETCHES"


def test_fetch_axios_skips_local_function_named_fetchUser() -> None:
    code = "function fetchUser(id) { return id }\nfetchUser(1)\n"
    src = SourceFile(
        rel_path="x.ts", abs_path=Path("x.ts"), language="typescript",
        content=code, content_hash="h", size_bytes=len(code),
    )
    extract, _ = LanguageProviderRegistry.default(
        parser_backend=ParserBackend.REGEX,
    ).parse_and_extract(src)
    out = detect_fetch_axios(src, extract)
    assert _edges_of(out, EDGE_FETCHES) == []


# --------------------------------------------------------------------------
# End-to-end: index the whole framework fixture once.
# --------------------------------------------------------------------------

@pytest.fixture()
def framework_repo(tmp_path: Path) -> Path:
    dest = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, dest)
    return dest


def test_index_pipeline_writes_framework_edges(framework_repo: Path) -> None:
    kb = CodeGraphKB(framework_repo)
    kb.index(force=True, parser="regex")

    counts = kb.framework_object_counts()
    assert counts["routes"] >= 4              # express x2 + fastify x2 + next at least 2
    assert counts["test_blocks"] >= 2
    assert counts["models"] >= 2              # Order + Refund
    assert counts["api_consumers"] >= 3
    assert counts["handles_route_edges"] >= 4
    assert counts["queries_edges"] >= 3
    assert counts["fetches_edges"] >= 3
    assert counts["calls_external_edges"] >= 3

    store = GraphStore(kb.config.db_path)
    try:
        # The Express POST /orders/:id/cancel route -> cancelOrderHandler edge
        # must exist as a HANDLES_ROUTE edge.
        row = store._conn.execute(
            "SELECT * FROM edges WHERE edge_type='HANDLES_ROUTE' "
            "AND src_qname=? AND dst_name=?",
            ("express::POST /orders/:id/cancel", "cancelOrderHandler"),
        ).fetchone()
        assert row is not None
    finally:
        store.close()


def test_doctor_reports_framework_object_counts(framework_repo: Path) -> None:
    kb = CodeGraphKB(framework_repo)
    kb.index(force=True, parser="regex")
    report = kb.doctor()
    counts = report.get("framework_object_counts") or {}
    assert counts.get("routes", 0) >= 4
    assert counts.get("queries_edges", 0) >= 3
    edge_types = report.get("edge_type_counts") or {}
    assert "HANDLES_ROUTE" in edge_types
    assert "QUERIES" in edge_types
    assert "FETCHES" in edge_types
