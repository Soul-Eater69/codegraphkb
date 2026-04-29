"""Optional embeddings layer.

Design goals:
  - zero-infra default (vectors stored in SQLite, brute-force cosine search)
  - cheap: embed only capsules and small strings — never raw files
  - cached by content hash so re-indexing without changes is free
  - pluggable provider (fastembed, sentence-transformers, or a hash-based stub)

Use:
  embedder = build_embedder()           # auto-pick what's installed
  count = embed_symbols(store, ids, embedder)
  hits = vector_search(store, embedder, query, limit=10)
"""
from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Protocol

from codegraphkb.core.store import GraphStore, SymbolRow


class Embedder(Protocol):
    @property
    def model_id(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


@dataclass
class VectorHit:
    symbol_id: int
    score: float


# ---------- builder ----------

def build_embedder(model: str | None = None, prefer: str = "auto") -> Embedder:
    """Pick the best available embedder. Order: fastembed -> sentence-transformers -> hash stub."""
    if prefer == "hash":
        return _HashEmbedder(model_name=model or "hash-stub-128")
    if prefer in ("auto", "fastembed"):
        try:
            return _FastEmbedEmbedder(model_name=model or "BAAI/bge-small-en-v1.5")
        except ImportError:
            if prefer == "fastembed":
                raise
        except Exception:
            if prefer == "fastembed":
                raise
    if prefer in ("auto", "sentence-transformers"):
        try:
            return _SentenceTransformersEmbedder(model_name=model or "sentence-transformers/all-MiniLM-L6-v2")
        except ImportError:
            if prefer == "sentence-transformers":
                raise
        except Exception:
            if prefer == "sentence-transformers":
                raise
    return _HashEmbedder(model_name="hash-stub-128")


# ---------- providers ----------

class _FastEmbedEmbedder:
    def __init__(self, model_name: str):
        from fastembed import TextEmbedding  # type: ignore
        self._model_name = model_name
        self._model = TextEmbedding(model_name=model_name)
        # Warm-call to discover dimension cheaply.
        sample = list(self._model.embed(["__warmup__"]))
        self._dimension = len(sample[0])

    @property
    def model_id(self) -> str:
        return f"fastembed:{self._model_name}"

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, vec)) for vec in self._model.embed(texts)]


class _SentenceTransformersEmbedder:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer  # type: ignore
        self._model_name = model_name
        self._model = SentenceTransformer(model_name)
        self._dimension = int(self._model.get_sentence_embedding_dimension())

    @property
    def model_id(self) -> str:
        return f"st:{self._model_name}"

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        vecs = self._model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
        return [list(map(float, v)) for v in vecs]


class _HashEmbedder:
    """Deterministic feature-hash embedder. Pure-Python, no deps.

    Not as accurate as a real model but useful for tests and as a graceful
    fallback so retrieval still has *some* semantic signal when no embedding
    library is installed.
    """
    def __init__(self, model_name: str = "hash-stub-128", dimension: int = 128):
        self._model_name = model_name
        self._dimension = dimension

    @property
    def model_id(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self._dimension
        for token in _tokenize_for_hash(text):
            h = int.from_bytes(
                hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest(),
                "big", signed=False,
            )
            idx = h % self._dimension
            sign = 1.0 if (h >> 7) & 1 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


# ---------- pipeline ----------

def embed_symbols(store: GraphStore, symbol_ids: Iterable[int],
                  embedder: Embedder, *, progress=None, batch_size: int = 64) -> int:
    """Embed (or refresh) capsules for the given symbols. Cached by content hash."""
    pending: list[tuple[SymbolRow, str, str]] = []
    skipped = 0
    seen: set[int] = set()
    for sid in symbol_ids:
        if sid in seen:
            continue
        seen.add(sid)
        sym = store.get_symbol_by_id(sid)
        if sym is None:
            continue
        text = _capsule_text(sym)
        chash = _content_hash(text)
        existing = store.get_embedding(sid, embedder.model_id)
        if existing is not None and existing[0] == chash:
            skipped += 1
            continue
        pending.append((sym, text, chash))

    if not pending:
        return 0

    if progress:
        progress(f"embedding {len(pending)} symbols ({skipped} cached)")

    now = datetime.now(timezone.utc).isoformat()
    written = 0
    for batch_start in range(0, len(pending), batch_size):
        chunk = pending[batch_start: batch_start + batch_size]
        vectors = embedder.embed_batch([t for _, t, _ in chunk])
        for (sym, _text, chash), vec in zip(chunk, vectors):
            store.upsert_embedding(
                sym.id,
                model=embedder.model_id,
                dim=len(vec),
                content_hash=chash,
                vector=_pack_vector(vec),
                created_at=now,
            )
            written += 1
    return written


def vector_search(store: GraphStore, embedder: Embedder, query: str,
                  *, limit: int = 25) -> list[VectorHit]:
    if not query.strip():
        return []
    if store.embedding_count(embedder.model_id) == 0:
        return []
    q_vec = embedder.embed_batch([query])[0]
    rows = store.all_embeddings(embedder.model_id)
    scored: list[tuple[int, float]] = []
    q_norm = math.sqrt(sum(v * v for v in q_vec)) or 1.0
    for sid, vec_bytes, dim in rows:
        v = _unpack_vector(vec_bytes, dim)
        # Vectors are normalized at write time for FastEmbed/ST/HashEmbedder.
        # Cosine = dot product / (||q|| * ||v||); ||v|| ≈ 1 for normalized models.
        v_norm = math.sqrt(sum(x * x for x in v)) or 1.0
        dot = sum(a * b for a, b in zip(q_vec, v))
        scored.append((sid, dot / (q_norm * v_norm)))
    scored.sort(key=lambda kv: kv[1], reverse=True)
    return [VectorHit(symbol_id=sid, score=s) for sid, s in scored[:limit]]


# ---------- helpers ----------

def _capsule_text(sym: SymbolRow) -> str:
    return "\n".join(filter(None, [
        sym.qualified_name,
        sym.signature,
        sym.docstring[:240],
        sym.capsule,
    ]))


def _content_hash(text: str) -> str:
    return hashlib.blake2b(text.encode("utf-8"), digest_size=16).hexdigest()


def _pack_vector(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack_vector(data: bytes, dim: int) -> list[float]:
    return list(struct.unpack(f"{dim}f", data))


def _tokenize_for_hash(text: str) -> list[str]:
    out: list[str] = []
    cur: list[str] = []
    for ch in text.lower():
        if ch.isalnum() or ch == "_":
            cur.append(ch)
        else:
            if cur:
                out.append("".join(cur))
                cur = []
    if cur:
        out.append("".join(cur))
    # add bigrams for slight context
    for i in range(len(out) - 1):
        out.append(out[i] + "_" + out[i + 1])
    return out
