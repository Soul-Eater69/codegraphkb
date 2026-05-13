"""Per-edge-type resolution breakdown in the doctor report."""
from __future__ import annotations

from pathlib import Path

import pytest

from codegraphkb import CodeGraphKB


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Repo whose CALLS edge is resolvable but IMPORTS edges aren't.

    The import targets ``os`` and ``json`` won't exist as symbols in the
    index — they're stdlib. The call ``helper()`` should resolve via
    file_scope.
    """
    r = tmp_path / "etrepo"
    r.mkdir()
    (r / "m.py").write_text(
        "import os\n"
        "import json\n"
        "\n"
        "def helper():\n"
        "    return 1\n"
        "\n"
        "def use():\n"
        "    return helper()\n",
        encoding="utf-8",
    )
    return r


def test_doctor_reports_per_edge_type_breakdown(repo: Path) -> None:
    kb = CodeGraphKB(repo)
    kb.index()
    from codegraphkb.diagnostics import collect_doctor_report
    report = collect_doctor_report(kb)

    by_type = report["edge_resolution_by_type"]
    assert "CALLS" in by_type
    assert "IMPORTS" in by_type

    calls = by_type["CALLS"]
    imports = by_type["IMPORTS"]

    # Each entry has the expected shape.
    for entry in (calls, imports):
        assert {"total", "resolved", "unresolved", "resolution_rate"} <= set(entry.keys())
        assert entry["total"] >= 0
        assert 0.0 <= entry["resolution_rate"] <= 1.0
        assert entry["resolved"] + entry["unresolved"] == entry["total"]

    # The CALLS rate should be meaningfully better than the IMPORTS rate
    # since CALLS go to in-repo symbols and IMPORTS go to stdlib here.
    assert calls["resolved"] >= 1
    assert imports["resolution_rate"] <= calls["resolution_rate"]


def test_empty_db_returns_empty_breakdown(tmp_path: Path) -> None:
    from codegraphkb.core.store import GraphStore
    store = GraphStore(tmp_path / "g.sqlite")
    try:
        assert store.edge_resolution_by_type() == {}
    finally:
        store.close()
