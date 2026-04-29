"""Extraction-eval fixture contract.

Fixtures are intentionally JSON-compatible dictionaries so language-specific
evals can live under ``evals/languages/<language>/`` without pulling in PyYAML.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ExtractionFixture:
    id: str
    language: str
    source_files: dict[str, str]
    expected_symbols: list[str] = field(default_factory=list)
    expected_imports: list[str] = field(default_factory=list)
    expected_calls: list[str] = field(default_factory=list)
    expected_routes: list[str] = field(default_factory=list)
    expected_tests: list[str] = field(default_factory=list)
    expected_types: list[str] = field(default_factory=list)
    expected_process_traces: list[str] = field(default_factory=list)


def load_extraction_fixture(path: Path) -> ExtractionFixture:
    data = json.loads(path.read_text(encoding="utf-8"))
    return ExtractionFixture(
        id=str(data["id"]),
        language=str(data["language"]),
        source_files={str(k): str(v) for k, v in data.get("source_files", {}).items()},
        expected_symbols=[str(v) for v in data.get("expected_symbols", [])],
        expected_imports=[str(v) for v in data.get("expected_imports", [])],
        expected_calls=[str(v) for v in data.get("expected_calls", [])],
        expected_routes=[str(v) for v in data.get("expected_routes", [])],
        expected_tests=[str(v) for v in data.get("expected_tests", [])],
        expected_types=[str(v) for v in data.get("expected_types", [])],
        expected_process_traces=[str(v) for v in data.get("expected_process_traces", [])],
    )
