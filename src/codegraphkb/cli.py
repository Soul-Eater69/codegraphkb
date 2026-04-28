"""CLI entry point — `codegraph` / `codegraphkb`.

Designed to feel like a friendly developer tool:

    codegraph index .
    codegraph ask "How does upload work?"
    codegraph impact src/payments/stripe.ts
    codegraph stats
    codegraph serve mcp
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from codegraphkb import __version__
from codegraphkb.api import CodeGraphKB
from codegraphkb.config import DEFAULT_TOKEN_BUDGET, INDEX_DIR_NAME


def main() -> None:
    cli(prog_name="codegraph")


@click.group(help="CodeGraphKB — index a codebase as a graph and serve minimal context to LLMs.")
@click.version_option(__version__)
def cli() -> None:
    pass


# ---------- index ----------
@cli.command("init", help="Initialize a CodeGraphKB index in the given repo (creates .codegraphkb/).")
@click.argument("repo", type=click.Path(file_okay=False, exists=True), default=".")
def init_cmd(repo: str) -> None:
    kb = CodeGraphKB(repo)
    kb.config.index_dir.mkdir(parents=True, exist_ok=True)
    click.echo(f"✓ Created {kb.config.index_dir}")
    click.echo(f"  Next:  codegraph index {repo}")


@cli.command("index", help="Scan the repo and (re)build the graph index.")
@click.argument("repo", type=click.Path(file_okay=False, exists=True), default=".")
@click.option("--force", is_flag=True, help="Re-index every file, ignoring content hashes.")
@click.option("--quiet", is_flag=True, help="Suppress per-file progress output.")
def index_cmd(repo: str, force: bool, quiet: bool) -> None:
    kb = CodeGraphKB(repo)
    progress = None if quiet else (lambda msg: click.echo(f"  · {msg}", err=True))
    stats = kb.index(force=force, progress=progress)
    click.echo()
    click.echo(click.style("CodeGraphKB index complete", bold=True, fg="green"))
    click.echo(f"  Repo:        {kb.config.repo_path}")
    click.echo(f"  Indexed:     {stats.files_indexed} files (scanned {stats.files_scanned})")
    if stats.files_unchanged:
        click.echo(f"  Unchanged:   {stats.files_unchanged}")
    if stats.files_removed:
        click.echo(f"  Removed:     {stats.files_removed}")
    click.echo(f"  Symbols:     {stats.symbols}")
    click.echo(f"  Edges:       {stats.edges}")
    click.echo(f"  Report:      {kb.config.report_path}")


@cli.command("stats", help="Show counts and metadata for the current index.")
@click.argument("repo", type=click.Path(file_okay=False, exists=True), default=".")
@click.option("--json", "as_json", is_flag=True)
def stats_cmd(repo: str, as_json: bool) -> None:
    kb = CodeGraphKB(repo)
    s = kb.stats()
    if as_json:
        click.echo(json.dumps(s, indent=2))
        return
    click.echo(click.style("Index stats", bold=True))
    click.echo(f"  Repo path:        {s['repo_path']}")
    click.echo(f"  Index dir:        {s['index_dir']}")
    click.echo(f"  Last indexed:     {s.get('last_indexed_at') or 'never'}")
    click.echo(f"  Files:            {s['files']}")
    click.echo(f"  Symbols:          {s['symbols']}")
    click.echo(f"  Edges:            {s['edges']}")
    if s["languages"]:
        click.echo(f"  Languages:        " + ", ".join(f"{k}={v}" for k, v in s["languages"].items()))


# ---------- query ----------
@cli.command("ask", help="Ask a question about the codebase.")
@click.argument("question")
@click.option("--repo", "repo", type=click.Path(file_okay=False, exists=True), default=".")
@click.option("--budget", type=int, default=DEFAULT_TOKEN_BUDGET, show_default=True,
              help="Token budget for assembled context.")
@click.option("--intent", type=str, default=None,
              help="Force an intent: architecture_explanation, bug_fix, feature_implementation, "
                   "refactor, impact_analysis, test_generation, security_review, api_usage, onboarding.")
@click.option("--pin", "pinned", multiple=True,
              help="Pin a file path (relative to repo) into the retrieval seeds.")
@click.option("--model", default=None, help="Override the Claude model id.")
@click.option("--context-only", is_flag=True, help="Print only the assembled context pack.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def ask_cmd(question: str, repo: str, budget: int, intent: str | None,
            pinned: tuple[str, ...], model: str | None, context_only: bool, as_json: bool) -> None:
    kb = CodeGraphKB(repo)
    if context_only:
        pack = kb.retrieve_context(question, token_budget=budget, intent=intent,
                                   pinned_files=list(pinned))
        if as_json:
            click.echo(json.dumps(_pack_to_dict(pack), indent=2))
        else:
            click.echo(pack.to_prompt())
        return

    result = kb.ask(question, token_budget=budget, intent=intent, model=model,
                    pinned_files=list(pinned))
    if as_json:
        click.echo(json.dumps({
            "question": result.question,
            "answer": result.answer,
            "model": result.llm.model,
            "used_llm": result.llm.used_llm,
            "context": _pack_to_dict(result.context),
        }, indent=2))
        return

    click.echo(click.style("Answer", bold=True, fg="cyan"))
    click.echo(result.answer)
    click.echo()
    click.echo(click.style(
        f"[intent={result.context.intent.value}  ~tokens={result.estimated_tokens}  "
        f"model={result.llm.model}]",
        dim=True,
    ))


@cli.command("impact", help="Impact analysis: what depends on this file or symbol?")
@click.argument("target")
@click.option("--repo", "repo", type=click.Path(file_okay=False, exists=True), default=".")
@click.option("--budget", type=int, default=DEFAULT_TOKEN_BUDGET, show_default=True)
def impact_cmd(target: str, repo: str, budget: int) -> None:
    kb = CodeGraphKB(repo)
    pack = kb.impact(target)
    pack.estimated_tokens  # ensure attribute exists
    click.echo(pack.to_prompt())


@cli.command("explain", help="Explain a file or symbol using graph context.")
@click.argument("target")
@click.option("--repo", "repo", type=click.Path(file_okay=False, exists=True), default=".")
def explain_cmd(target: str, repo: str) -> None:
    kb = CodeGraphKB(repo)
    pack = kb.explain(target)
    click.echo(pack.to_prompt())


@cli.command("find", help="Find symbols by name or qualified name.")
@click.argument("name")
@click.option("--repo", "repo", type=click.Path(file_okay=False, exists=True), default=".")
def find_cmd(name: str, repo: str) -> None:
    kb = CodeGraphKB(repo)
    hits = kb.find_symbol(name)
    if not hits:
        click.echo(f"No symbols matched `{name}`.")
        sys.exit(1)
    for sym in hits:
        click.echo(f"{sym.kind:<10} {sym.qualified_name}  {sym.file_path}:{sym.start_line}-{sym.end_line}")


# ---------- servers ----------
@cli.command("serve", help="Run the MCP or HTTP server.")
@click.argument("kind", type=click.Choice(["mcp", "api"]))
@click.option("--repo", "repo", type=click.Path(file_okay=False, exists=True), default=".")
@click.option("--host", default="127.0.0.1")
@click.option("--port", type=int, default=8765)
def serve_cmd(kind: str, repo: str, host: str, port: int) -> None:
    if kind == "mcp":
        from codegraphkb.server.mcp_server import run_stdio
        run_stdio(repo)
    else:
        try:
            from codegraphkb.server.api_server import run_api
        except ImportError as exc:  # pragma: no cover
            click.echo(f"Install codegraphkb[api] first: {exc}", err=True)
            sys.exit(1)
        run_api(repo, host=host, port=port)


def _pack_to_dict(pack) -> dict:
    return {
        "intent": pack.intent.value,
        "estimated_tokens": pack.estimated_tokens,
        "graph_paths": pack.graph_paths,
        "files_likely_to_edit": pack.files_likely_to_edit,
        "items": [
            {
                "kind": it.kind,
                "title": it.title,
                "file_path": it.file_path,
                "start_line": it.start_line,
                "end_line": it.end_line,
                "score": it.score,
                "tokens": it.tokens,
                "body": it.body,
            }
            for it in pack.items
        ],
        "repo_map": pack.repo_map,
    }


if __name__ == "__main__":
    main()
