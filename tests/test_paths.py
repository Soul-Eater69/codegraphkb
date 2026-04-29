"""Path normalization tests for eval/report boundaries."""
from __future__ import annotations

from pathlib import Path

from codegraphkb.eval import _any_file_match
from codegraphkb.eval_edit import _file_recall
from codegraphkb.paths import normalize_path


def test_normalize_path_handles_windows_and_posix_forms() -> None:
    repo = r"C:\repo"
    expected = "src/core/workflow.py"
    assert normalize_path("src/core/workflow.py", repo) == expected
    assert normalize_path(r"src\core\workflow.py", repo) == expected
    assert normalize_path(r"C:\repo\src\core\workflow.py", repo) == expected
    assert normalize_path("./src/core/workflow.py", repo) == expected


def test_eval_file_match_handles_absolute_windows_path() -> None:
    repo = Path(r"C:\repo")
    retrieved = [r"C:\repo\src\core\workflow.py"]
    assert _any_file_match(retrieved, "src/core/workflow.py", repo)
    assert _file_recall(retrieved, [r"src\core\workflow.py"], 5, repo) == 1.0
