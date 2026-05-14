from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest


@pytest.fixture()
def workspace_tmp() -> Path:
    root = Path.cwd() / "tmp_work" / "pytest_manual"
    path = root / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path

