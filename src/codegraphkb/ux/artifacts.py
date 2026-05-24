"""Generate user-facing artifacts after indexing a repo.

These artifacts go into ``<repo>/.codegraphkb/`` and let users see / share / wire
up CodeGraphKB output without running additional commands:

- ``GRAPH_REPORT.md`` — human-readable summary of the indexed graph
- ``graph.json``     — serialized graph payload (full view)
- ``graph.html``     — standalone interactive graph viewer
- ``mcp.json``       — drop-in MCP config pointing at this repo
- ``edit_plan_example.md`` — sample ``prepare-edit`` output the user can read
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from codegraphkb.config import INDEX_DIR_NAME, REPORT_FILE

if TYPE_CHECKING:  # pragma: no cover
    from codegraphkb.api import CodeGraphKB


DEFAULT_EDIT_PLAN_TASK = "Explain the most important feature flow in this repo"


@dataclass
class ArtifactPaths:
    out_dir: Path
    report: Path
    graph_json: Path
    graph_html: Path
    mcp_config: Path
    edit_plan_example: Path

    @classmethod
    def under(cls, repo: Path, out_dir: Path | None = None) -> "ArtifactPaths":
        base = out_dir if out_dir is not None else (repo / INDEX_DIR_NAME)
        return cls(
            out_dir=base,
            report=base / REPORT_FILE,
            graph_json=base / "graph.json",
            graph_html=base / "graph.html",
            mcp_config=base / "mcp.json",
            edit_plan_example=base / "edit_plan_example.md",
        )


@dataclass
class GeneratedArtifacts:
    """Result of :func:`generate_artifacts` — which files were written and which errored."""

    paths: ArtifactPaths
    written: list[Path] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.skipped


def generate_artifacts(
    kb: "CodeGraphKB",
    *,
    out_dir: Path | None = None,
    include_report: bool = True,
    include_graph_json: bool = True,
    include_graph_html: bool = True,
    include_mcp: bool = True,
    include_edit_plan_example: bool = True,
    edit_plan_task: str = DEFAULT_EDIT_PLAN_TASK,
    view: str = "full",
) -> GeneratedArtifacts:
    """Generate the user-facing artifacts for ``kb``'s repo.

    Failures are recorded in :attr:`GeneratedArtifacts.skipped` rather than raised, so a
    missing optional dependency (e.g. no embeddings for ``prepare-edit``) does not abort
    the whole batch. Always returns a :class:`GeneratedArtifacts`.
    """
    repo = Path(kb.config.repo_path)
    paths = ArtifactPaths.under(repo, out_dir)
    paths.out_dir.mkdir(parents=True, exist_ok=True)

    result = GeneratedArtifacts(paths=paths)

    if include_report:
        _try(
            result,
            "report",
            paths.report,
            lambda: _write_report(kb, paths.report),
        )

    if include_graph_json:
        _try(
            result,
            "graph_json",
            paths.graph_json,
            lambda: _write_graph_json(kb, paths.graph_json, view=view),
        )

    if include_graph_html:
        _try(
            result,
            "graph_html",
            paths.graph_html,
            lambda: _write_graph_html(kb, paths.graph_html, view=view),
        )

    if include_mcp:
        _try(
            result,
            "mcp",
            paths.mcp_config,
            lambda: _write_mcp_config(repo, paths.mcp_config),
        )

    if include_edit_plan_example:
        _try(
            result,
            "edit_plan_example",
            paths.edit_plan_example,
            lambda: _write_edit_plan_example(kb, paths.edit_plan_example, edit_plan_task),
        )

    return result


def _try(result: GeneratedArtifacts, key: str, path: Path, fn) -> None:
    try:
        fn()
    except Exception as exc:  # pragma: no cover - defensive
        result.skipped[key] = f"{type(exc).__name__}: {exc}"
        return
    result.written.append(path)


def _write_report(kb: "CodeGraphKB", out: Path) -> None:
    from codegraphkb.reporting import generate_report

    store = kb._open_store()
    try:
        text = generate_report(store)
    finally:
        store.close()
    out.write_text(text, encoding="utf-8")


def _write_graph_json(kb: "CodeGraphKB", out: Path, *, view: str) -> None:
    payload = kb.export_graph(view=view)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_graph_html(kb: "CodeGraphKB", out: Path, *, view: str) -> None:
    kb.export_graph_html(view=view, out=out)


def _write_mcp_config(repo: Path, out: Path) -> None:
    payload = build_mcp_config(repo)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def build_mcp_config(repo: Path) -> dict:
    return {
        "mcpServers": {
            "codegraphkb": {
                "command": "codegraph",
                "args": ["serve", "mcp", "--repo", str(repo.resolve())],
            }
        }
    }


def _write_edit_plan_example(kb: "CodeGraphKB", out: Path, task: str) -> None:
    from codegraphkb.workflow import prepare_edit_context

    pack = prepare_edit_context(kb, task)
    out.write_text(_render_edit_plan_markdown(pack), encoding="utf-8")


def _render_edit_plan_markdown(pack) -> str:
    lines: list[str] = [
        f"# Edit Plan Example — {pack.task}",
        "",
        "_This file is a snapshot of `codegraph prepare-edit` output. Regenerate with_",
        "_`codegraph export-artifacts` or `codegraph start`._",
        "",
        "## Summary",
        "",
        pack.summary or "_(no summary)_",
        "",
    ]

    def section(title: str, items: list, render) -> None:
        lines.extend([f"## {title}", ""])
        if not items:
            lines.append("_(none)_")
            lines.append("")
            return
        for it in items:
            lines.append(render(it))
        lines.append("")

    section(
        "Files likely to edit",
        pack.files_likely_to_edit,
        lambda it: f"- `{it.file}` — {it.reason} (confidence {it.confidence:.2f})",
    )
    section(
        "Files to read first",
        pack.files_to_read_only,
        lambda it: f"- `{it.file}` — {it.reason} (confidence {it.confidence:.2f})",
    )
    section(
        "Symbols to modify",
        pack.symbols_to_modify,
        lambda it: f"- `{it.symbol}` in `{it.file}` — {it.reason}",
    )
    section(
        "Related tests",
        pack.related_tests,
        lambda it: f"- `{it.file}` — {it.reason} (confidence {it.confidence:.2f})",
    )
    section(
        "Risks",
        pack.risks,
        lambda it: f"- **{it.level.upper()}**: {it.title} — {it.reason}",
    )
    section(
        "Validation commands",
        pack.validation_commands,
        lambda it: f"- `{it.command}` ({it.type}) — {it.reason}",
    )

    return "\n".join(lines).rstrip() + "\n"
