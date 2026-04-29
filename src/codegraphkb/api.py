"""Public Python API. Friendly entry point for library users."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from codegraphkb.config import DEFAULT_TOKEN_BUDGET, IndexConfig
from codegraphkb.core.indexer import IndexStats, index_repository
from codegraphkb.core.llm import LLMResponse, answer_with_context
from codegraphkb.core.parsers import ParserBackend
from codegraphkb.core.retrieval import (
    ContextPack, Intent, Mode, classify_intent, coerce_mode, retrieve_context,
)
from codegraphkb.core.store import GraphStore, SymbolRow
from codegraphkb.reporting import generate_report


@dataclass
class RetrievalResult:
    """Result of `kb.ask(...)` — answer + the context pack that produced it."""
    question: str
    answer: str
    context: ContextPack
    llm: LLMResponse

    @property
    def estimated_tokens(self) -> int:
        return self.context.estimated_tokens


class CodeGraphKB:
    """Main user-facing class.

    Example:
        kb = CodeGraphKB("./my-repo")
        kb.index(parser="tree-sitter", embed=True)
        result = kb.ask("How does authentication work?", mode="explain")
        print(result.answer)
    """

    def __init__(self, repo_path: str | Path):
        self.config = IndexConfig.for_repo(repo_path)
        self._embedder = None  # lazily built when embeddings are requested
        self._embedder_unavailable = False

    # ---------- indexing ----------
    def index(self, force: bool = False, progress=None,
              parser: ParserBackend | str = ParserBackend.AUTO,
              embed: bool = False,
              embedder=None) -> IndexStats:
        """(Re)build the graph for the repo. Re-indexes only changed files unless `force=True`.

        parser: "auto" (default), "tree-sitter", or "regex".
        embed:  if True (and an embedder is available), also write capsule embeddings.
        embedder: optional pre-built embedder object; takes precedence over `embed`.
        """
        backend = self._coerce_backend(parser)
        active_embedder = embedder
        if active_embedder is None and embed:
            from codegraphkb.core.embeddings import build_embedder
            active_embedder = build_embedder()
            self._embedder = active_embedder
        elif embedder is not None:
            self._embedder = embedder
        stats = index_repository(self.config, force=force, progress=progress,
                                 parser_backend=backend, embedder=active_embedder)
        self.write_report()
        return stats

    def write_report(self) -> Path:
        store = self._open_store()
        try:
            text = generate_report(store)
        finally:
            store.close()
        self.config.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.report_path.write_text(text, encoding="utf-8")
        return self.config.report_path

    # ---------- retrieval ----------
    def retrieve_context(
        self,
        task: str,
        *,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        intent: Intent | str | None = None,
        mode: Mode | str | None = None,
        pinned_files: Iterable[str] | None = None,
        retrieval: str = "auto",
    ) -> ContextPack:
        intent_enum = _coerce_intent(intent)
        embedder = self._embedder_for_query(retrieval)
        store = self._open_store()
        try:
            return retrieve_context(
                store,
                task,
                token_budget=token_budget,
                intent=intent_enum,
                mode=mode,
                pinned_files=list(pinned_files or []),
                embedder=embedder,
                retrieval_mode=retrieval,
            )
        finally:
            store.close()

    def ask(
        self,
        question: str,
        *,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        intent: Intent | str | None = None,
        mode: Mode | str | None = None,
        model: str | None = None,
        pinned_files: Iterable[str] | None = None,
        retrieval: str = "auto",
    ) -> RetrievalResult:
        pack = self.retrieve_context(
            question,
            token_budget=token_budget,
            intent=intent,
            mode=mode,
            pinned_files=pinned_files,
            retrieval=retrieval,
        )
        prompt = pack.to_prompt()
        llm = answer_with_context(
            context_pack_text=prompt + f"\n\n## Question\n{question}\n",
            question=question,
            model=model,
        )
        return RetrievalResult(question=question, answer=llm.answer, context=pack, llm=llm)

    def impact(self, target: str) -> ContextPack:
        return self.retrieve_context(
            f"Impact analysis for {target}: what callers, routes, and tests are affected?",
            intent=Intent.IMPACT,
            mode=Mode.IMPACT,
            pinned_files=[target] if "/" in target or target.endswith((".py", ".ts", ".js", ".tsx", ".jsx")) else None,
        )

    def explain(self, target: str) -> ContextPack:
        return self.retrieve_context(
            f"Explain {target} and how it fits into the system.",
            intent=Intent.EXPLAIN,
            mode=Mode.EXPLAIN,
            pinned_files=[target] if "/" in target else None,
        )

    def related_tests(self, target: str) -> list[SymbolRow]:
        store = self._open_store()
        try:
            hits = store.find_symbols_by_name(target, limit=5)
            if not hits:
                return []
            tests: dict[str, SymbolRow] = {}
            for sym in hits:
                for edge in store.incoming(sym.qualified_name, ["TESTS"]):
                    src = store.find_symbol(edge.src_qname)
                    if src:
                        tests[src.qualified_name] = src
                # also: tests in the same file
                for s in store.symbols_in_file(sym.file_path):
                    if s.kind == "test" or s.name.startswith("test_"):
                        tests[s.qualified_name] = s
            return list(tests.values())
        finally:
            store.close()

    def callers_and_callees(self, symbol: str) -> dict[str, list[SymbolRow]]:
        store = self._open_store()
        try:
            sym = store.find_symbol(symbol)
            if sym is None:
                hits = store.find_symbols_by_name(symbol, limit=1)
                if not hits:
                    return {"callers": [], "callees": []}
                sym = hits[0]
            callers: list[SymbolRow] = []
            callees: list[SymbolRow] = []
            for edge in store.incoming(sym.qualified_name, ["CALLS", "ROUTES_TO"]):
                src = store.find_symbol(edge.src_qname)
                if src:
                    callers.append(src)
            for edge in store.outgoing(sym.qualified_name, ["CALLS"]):
                if edge.dst_qname:
                    target = store.find_symbol(edge.dst_qname)
                else:
                    by_name = store.find_symbols_by_name(edge.dst_name, limit=1)
                    target = by_name[0] if by_name else None
                if target:
                    callees.append(target)
            return {"callers": callers, "callees": callees}
        finally:
            store.close()

    def resolve_symbol(self, name_or_path: str) -> list[SymbolRow]:
        store = self._open_store()
        try:
            if "/" in name_or_path or name_or_path.endswith((".py", ".ts", ".js", ".tsx", ".jsx")):
                return store.symbols_in_file(name_or_path)
            sym = store.find_symbol(name_or_path)
            if sym:
                return [sym]
            return store.find_symbols_by_name(name_or_path)
        finally:
            store.close()

    # ---------- introspection ----------
    def stats(self) -> dict:
        store = self._open_store()
        try:
            return {
                "files": store.file_count(),
                "symbols": store.symbol_count(),
                "edges": store.edge_count(),
                "embeddings": store.embedding_count(),
                "languages": store.file_languages(),
                "last_indexed_at": store.get_meta("last_indexed_at"),
                "schema_version": store.get_meta("schema_version"),
                "capsule_version": store.get_meta("capsule_version"),
                "parser_backend_pref": store.get_meta("parser_backend_pref"),
                "embedding_model": store.get_meta("embedding_model"),
                "repo_path": str(self.config.repo_path),
                "index_dir": str(self.config.index_dir),
            }
        finally:
            store.close()

    def doctor(self) -> dict:
        """Health report — what is present, what is stale, what is missing."""
        from codegraphkb.diagnostics import collect_doctor_report
        return collect_doctor_report(self)

    def object_type_counts(self) -> dict[str, int]:
        """PR 14 — break down symbol counts by `kind` for `codegraph stats --object-types`."""
        store = self._open_store()
        try:
            rows = store._conn.execute(
                "SELECT kind, COUNT(*) AS n FROM symbols GROUP BY kind"
            ).fetchall()
            return {r["kind"]: int(r["n"]) for r in rows}
        finally:
            store.close()

    def detected_frameworks(self) -> dict[str, int]:
        """PR 14 — count files per detected framework (from indexer meta keys)."""
        store = self._open_store()
        try:
            rows = store._conn.execute(
                "SELECT key FROM meta WHERE key LIKE 'framework:%'"
            ).fetchall()
        finally:
            store.close()
        counts: dict[str, int] = {}
        for r in rows:
            parts = r["key"].split(":", 2)
            if len(parts) == 3:
                fw = parts[2]
                counts[fw] = counts.get(fw, 0) + 1
        return counts

    def find_symbol(self, name: str) -> list[SymbolRow]:
        store = self._open_store()
        try:
            sym = store.find_symbol(name)
            if sym:
                return [sym]
            return store.find_symbols_by_name(name)
        finally:
            store.close()

    # ---------- internals ----------
    def _open_store(self) -> GraphStore:
        if not self.config.db_path.exists():
            raise FileNotFoundError(
                f"No index found at {self.config.db_path}. "
                f"Run `codegraph index {self.config.repo_path}` first."
            )
        return GraphStore(self.config.db_path)

    def _embedder_for_query(self, retrieval: str):
        if retrieval == "bm25":
            return None
        # `auto` should not silently use the hash stub — that adds noise without
        # real semantics. Only return the stub when the user explicitly asked
        # for hybrid/vector retrieval.
        allow_stub = retrieval in ("hybrid", "vector")
        if self._embedder is not None:
            if not allow_stub and getattr(self._embedder, "model_id", "").startswith("hash-stub"):
                return None
            return self._embedder
        if self._embedder_unavailable:
            return None
        if retrieval in ("hybrid", "vector") or retrieval == "auto":
            store = self._open_store()
            try:
                model_id = store.get_meta("embedding_model")
                if not model_id:
                    return None
                if not allow_stub and model_id.startswith("hash-stub"):
                    return None
            finally:
                store.close()
            try:
                from codegraphkb.core.embeddings import build_embedder
                if model_id and model_id.startswith("hash-stub"):
                    self._embedder = build_embedder(model=model_id, prefer="hash")
                else:
                    self._embedder = build_embedder()
                return self._embedder
            except Exception:
                self._embedder_unavailable = True
                return None
        return None

    @staticmethod
    def _coerce_backend(value) -> ParserBackend:
        if isinstance(value, ParserBackend):
            return value
        try:
            return ParserBackend(str(value))
        except ValueError:
            return ParserBackend.AUTO


def _coerce_intent(intent: Intent | str | None) -> Intent | None:
    if intent is None or isinstance(intent, Intent):
        return intent
    if isinstance(intent, str):
        try:
            return Intent(intent)
        except ValueError:
            return classify_intent(intent)
    return None
