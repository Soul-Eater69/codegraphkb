"""End-to-end smoke test: index the fixture, retrieve, sanity-check the pack."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from codegraphkb import CodeGraphKB
from codegraphkb.core.retrieval import Intent

FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo"


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    dest = tmp_path / "repo"
    shutil.copytree(FIXTURE, dest)
    return dest


def test_index_and_stats(repo: Path) -> None:
    kb = CodeGraphKB(repo)
    stats = kb.index()
    assert stats.files_indexed >= 2
    assert stats.symbols >= 4

    info = kb.stats()
    assert info["files"] >= 2
    assert info["symbols"] >= 4


def test_incremental_reindex_skips_unchanged(repo: Path) -> None:
    kb = CodeGraphKB(repo)
    first = kb.index()
    second = kb.index()
    assert second.files_indexed == 0
    assert second.files_unchanged == first.files_indexed


def test_retrieval_returns_relevant_symbol(repo: Path) -> None:
    kb = CodeGraphKB(repo)
    kb.index()
    pack = kb.retrieve_context("How does idea card upload work?")
    assert pack.items, "expected at least one capsule"
    titles = " ".join(it.title for it in pack.items)
    assert "process_upload" in titles or "upload_idea_card" in titles
    assert pack.estimated_tokens > 0


def test_impact_includes_caller(repo: Path) -> None:
    kb = CodeGraphKB(repo)
    kb.index()
    pack = kb.impact("process_upload")
    assert pack.intent == Intent.IMPACT
    bodies = " ".join(it.body for it in pack.items)
    assert "upload_idea_card" in bodies or "process_upload" in bodies


def test_offline_ask_returns_pack(repo: Path, monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    kb = CodeGraphKB(repo)
    kb.index()
    result = kb.ask("Explain process_upload")
    assert result.llm.used_llm is False
    assert "process_upload" in result.answer or "Capsule" in result.answer
