"""Public Python API. Friendly entry point for library users."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from codegraphkb.config import DEFAULT_TOKEN_BUDGET, IndexConfig
from codegraphkb.core.indexer import IndexStats, index_repository
from codegraphkb.core.llm import LLMResponse, answer_with_context
from codegraphkb.core.retrieval import ContextPack, Intent, classify_intent, retrieve_context
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
        kb.index()
        result = kb.ask("How does authentication work?")
        print(result.answer)
    """

    def __init__(self, repo_path: str | Path):
        self.config = IndexConfig.for_repo(repo_path)

    # ---------- indexing ----------
    def index(self, force: bool = False, progress=None) -> IndexStats:
        """(Re)build the graph for the repo. Re-indexes only changed files unless `force=True`."""
        stats = index_repository(self.config, force=force, progress=progress)
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
        pinned_files: Iterable[str] | None = None,
    ) -> ContextPack:
        intent_enum = _coerce_intent(intent)
        store = self._open_store()
        try:
            return retrieve_context(
                store,
                task,
                token_budget=token_budget,
                intent=intent_enum,
                pinned_files=list(pinned_files or []),
            )
        finally:
            store.close()

    def ask(
        self,
        question: str,
        *,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        intent: Intent | str | None = None,
        model: str | None = None,
        pinned_files: Iterable[str] | None = None,
    ) -> RetrievalResult:
        pack = self.retrieve_context(
            question,
            token_budget=token_budget,
            intent=intent,
            pinned_files=pinned_files,
        )
        prompt = pack.to_prompt()
        llm = answer_with_context(
            context_pack_text=prompt + f"\n\n## Question\n{question}\n",
            question=question,
            model=model,
        )
        return RetrievalResult(question=question, answer=llm.answer, context=pack, llm=llm)

    def impact(self, target: str) -> ContextPack:
        """Impact analysis: what depends on this file or symbol?"""
        return self.retrieve_context(
            f"Impact analysis for {target}: what callers, routes, and tests are affected?",
            intent=Intent.IMPACT,
            pinned_files=[target] if "/" in target or target.endswith((".py", ".ts", ".js", ".tsx", ".jsx")) else None,
        )

    def explain(self, target: str) -> ContextPack:
        return self.retrieve_context(
            f"Explain {target} and how it fits into the system.",
            intent=Intent.EXPLAIN,
            pinned_files=[target] if "/" in target else None,
        )

    # ---------- introspection ----------
    def stats(self) -> dict:
        store = self._open_store()
        try:
            return {
                "files": store.file_count(),
                "symbols": store.symbol_count(),
                "edges": store.edge_count(),
                "languages": store.file_languages(),
                "last_indexed_at": store.get_meta("last_indexed_at"),
                "repo_path": str(self.config.repo_path),
                "index_dir": str(self.config.index_dir),
            }
        finally:
            store.close()

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


def _coerce_intent(intent: Intent | str | None) -> Intent | None:
    if intent is None or isinstance(intent, Intent):
        return intent
    if isinstance(intent, str):
        try:
            return Intent(intent)
        except ValueError:
            return classify_intent(intent)
    return None
