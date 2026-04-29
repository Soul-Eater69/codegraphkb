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


def test_doctor_reports_versions(repo: Path) -> None:
    kb = CodeGraphKB(repo)
    kb.index()
    report = kb.doctor()
    assert "schema_version_current" in report
    assert "stale_file_count" in report
    assert report["stale_file_count"] == 0


def test_audit_metadata_attached_to_items(repo: Path) -> None:
    kb = CodeGraphKB(repo)
    kb.index()
    pack = kb.retrieve_context("How does idea card upload work?", mode="explain")
    assert pack.items
    item = pack.items[0]
    assert item.retrieval_sources, "expected at least one retrieval source"
    assert item.score_breakdown.final >= 0.0
    assert item.reason, "items should carry a human-readable reason"
    # graph_path always at least includes the symbol itself
    assert item.graph_path


def test_eval_harness_runs(repo: Path, tmp_path: Path) -> None:
    from codegraphkb import eval as eval_mod
    kb = CodeGraphKB(repo)
    kb.index()
    dataset = tmp_path / "tasks.yaml"
    dataset.write_text(
        "- id: smoke\n"
        "  task: \"How does idea card upload work?\"\n"
        "  mode: explain\n"
        "  budget: 3000\n"
        "  oracle_files:\n"
        "    - services.py\n"
        "  oracle_symbols:\n"
        "    - process_upload\n",
        encoding="utf-8",
    )
    report = eval_mod.evaluate(repo, dataset, retrieval_mode="bm25")
    assert report.n_tasks == 1
    assert report.tasks[0].file_recall_at_8 > 0
    assert report.median_latency_ms > 0


def test_embedder_stub_caches_by_hash(repo: Path) -> None:
    kb = CodeGraphKB(repo)
    first = kb.index(embed=True)
    # Re-running shouldn't re-embed unchanged capsules.
    second = kb.index(embed=True)
    assert second.symbols == 0  # nothing reparsed when nothing changed
    embed_keys = [k for k in first.parser_backends if k.startswith("embedded:")]
    assert embed_keys, "first index should have written embeddings"
