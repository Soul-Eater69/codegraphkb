"""BM25 search over symbol capsules and identifiers.

Uses the inverted index built during indexing. No external deps.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from codegraphkb.core.indexer import _tokenize
from codegraphkb.core.store import GraphStore, SymbolRow

_K1 = 1.5
_B = 0.75


@dataclass
class SearchHit:
    symbol: SymbolRow
    score: float


def search_symbols(store: GraphStore, query: str, limit: int = 25) -> list[SearchHit]:
    if not query.strip():
        return []
    term_freqs, _ = _tokenize(query)
    query_terms = list(term_freqs.keys())
    if not query_terms:
        return []
    n_docs = max(1, store.total_docs())
    avgdl = max(1.0, store.avg_doc_length())
    df_map = store.doc_freq(query_terms)
    postings = store.lookup_terms(query_terms)

    scores: dict[int, float] = {}
    for term, symbol_id, tf in postings:
        df = df_map.get(term, 1)
        idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
        dl = store.doc_length(symbol_id)
        denom = tf + _K1 * (1 - _B + _B * dl / avgdl)
        contribution = idf * (tf * (_K1 + 1)) / denom
        scores[symbol_id] = scores.get(symbol_id, 0.0) + contribution

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    hits: list[SearchHit] = []
    for sid, score in ranked:
        sym = store.get_symbol_by_id(sid)
        if sym:
            hits.append(SearchHit(symbol=sym, score=score))
    return hits
