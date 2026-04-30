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
from codegraphkb import eval as eval_mod
from codegraphkb import regression as regression_mod
from codegraphkb import workflow as workflow_mod


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
@click.option("--force-parser-refresh", is_flag=True,
              help="Re-run the parser even when content hashes match.")
@click.option("--quiet", is_flag=True, help="Suppress per-file progress output.")
@click.option("--parser", "parser_choice", type=click.Choice(["auto", "tree-sitter", "regex"]),
              default="auto", show_default=True,
              help="Parser backend selection. Tree-sitter requires `codegraphkb[parser]`.")
@click.option("--embed", is_flag=True,
              help="Embed symbol capsules. Requires `codegraphkb[embeddings]` for real models; "
                   "falls back to a hash-based stub embedder otherwise.")
@click.option("--semantic", "semantic_choice",
              type=click.Choice(["none", "auto", "typescript"]),
              default="none", show_default=True,
              help="Run a language semantic adapter after the syntax pass to "
                   "enrich CALLS/types. Requires the helper to be built.")
def index_cmd(repo: str, force: bool, force_parser_refresh: bool, quiet: bool,
              parser_choice: str, embed: bool, semantic_choice: str) -> None:
    kb = CodeGraphKB(repo)
    progress = None if quiet else (lambda msg: click.echo(f"  · {msg}", err=True))
    # `--force-parser-refresh` is a softer rebuild than `--force`: just bumps parser sigs.
    effective_force = force or force_parser_refresh
    stats = kb.index(force=effective_force, progress=progress,
                     parser=parser_choice, embed=embed,
                     semantic=None if semantic_choice == "none" else semantic_choice)
    click.echo()
    click.echo(click.style("CodeGraphKB index complete", bold=True, fg="green"))
    click.echo(f"  Repo:        {kb.config.repo_path}")
    click.echo(f"  Indexed:     {stats.files_indexed} files (scanned {stats.files_scanned})")
    if stats.files_unchanged:
        click.echo(f"  Unchanged:   {stats.files_unchanged}")
    if stats.files_reparsed_for_version:
        click.echo(f"  Re-parsed:   {stats.files_reparsed_for_version} (parser version bump)")
    if stats.files_removed:
        click.echo(f"  Removed:     {stats.files_removed}")
    click.echo(f"  Symbols:     {stats.symbols}")
    click.echo(f"  Edges:       {stats.edges}")
    if stats.parser_backends:
        used = ", ".join(f"{k}={v}" for k, v in stats.parser_backends.items()
                         if not k.startswith("embedded:"))
        if used:
            click.echo(f"  Parsers:     {used}")
        embedded_keys = [k for k in stats.parser_backends if k.startswith("embedded:")]
        if embedded_keys:
            n = stats.parser_backends[embedded_keys[0]]
            click.echo(f"  Embedded:    {n} symbol capsules")
    if stats.semantic_backends:
        for lang, info in stats.semantic_backends.items():
            status = "ok" if info.get("available") else "unavailable"
            click.echo(
                f"  Semantic[{lang}]: {status}  "
                f"upgraded={info.get('edges_upgraded', 0)} "
                f"inserted={info.get('edges_inserted', 0)} "
                f"types={info.get('types_inserted', 0)}"
            )
            for warn in info.get("warnings", []) or []:
                click.echo(click.style(f"        ! {warn}", fg="yellow"))
    if stats.processes_built:
        by_type = ", ".join(f"{k}={v}" for k, v in stats.processes_by_type.items())
        click.echo(f"  Processes:   {stats.processes_built}  ({by_type})")
    click.echo(f"  Report:      {kb.config.report_path}")


@cli.command("doctor", help="Diagnose the index: parser version, schema, embeddings, stale files.")
@click.argument("repo", type=click.Path(file_okay=False, exists=True), default=".")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable diagnostics.")
def doctor_cmd(repo: str, as_json: bool) -> None:
    kb = CodeGraphKB(repo)
    from codegraphkb.diagnostics import collect_doctor_report
    report = collect_doctor_report(kb)
    if as_json:
        click.echo(json.dumps(report, indent=2))
        return
    click.echo(click.style("CodeGraphKB doctor", bold=True))
    click.echo(f"  Tree-sitter installed:     {report['tree_sitter_available']}")
    click.echo(f"  Preferred parser backend:  {report['parser_backend_preferred']}")
    click.echo(f"  Schema version (current):  {report['schema_version_current']}")
    click.echo(f"  Schema version (indexed):  {report['schema_version_indexed']}")
    click.echo(f"  Capsule version (current): {report['capsule_version_current']}")
    click.echo(f"  Capsule version (indexed): {report['capsule_version_indexed']}")
    click.echo(f"  Embedding provider:        {report['embedding_provider']}")
    click.echo(f"  Embedding model:           {report['embedding_model'] or '(none)'}")
    click.echo(f"  Embedding load state:      {report['embedding_load_state']}")
    click.echo(f"  Embeddings stored:         {report['embeddings']}")
    click.echo(f"  Semantic backends:         " + ", ".join(
        f"{lang}={'yes' if meta.get('available') else 'no'}"
        for lang, meta in report.get("semantic_backends", {}).items()
    ))
    click.echo(f"  Indexed files:             {report['indexed_file_count']}")
    click.echo(f"  Symbols:                   {report['symbol_count']}")
    click.echo(f"  Edges:                     {report['edge_count']}")
    click.echo(f"  Stale files for parser:    {report['stale_file_count']}")
    if report["stale_files_for_parser"]:
        for p in report["stale_files_for_parser"]:
            click.echo(f"    · {p}")
        click.echo("  Hint:  codegraph index <repo> --force-parser-refresh")


@cli.command("stats", help="Show counts and metadata for the current index.")
@click.argument("repo", type=click.Path(file_okay=False, exists=True), default=".")
@click.option("--json", "as_json", is_flag=True)
@click.option("--object-types", "object_types", is_flag=True,
              help="Break down symbol counts by kind (PR 14: routes, components, "
                   "models, env_vars, schemas, test_blocks, fixtures, ...).")
def stats_cmd(repo: str, as_json: bool, object_types: bool) -> None:
    kb = CodeGraphKB(repo)
    s = kb.stats()
    if object_types:
        s["object_types"] = kb.object_type_counts()
        s["frameworks"] = kb.detected_frameworks()
        s["framework_objects"] = kb.framework_object_counts()
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
    if object_types:
        click.echo()
        click.echo(click.style("Object types", bold=True))
        for kind, n in sorted(s["object_types"].items(), key=lambda kv: kv[1], reverse=True):
            click.echo(f"  {kind:<14} {n}")
        if s["frameworks"]:
            click.echo()
            click.echo(click.style("Detected frameworks", bold=True))
            for fw, n in sorted(s["frameworks"].items(), key=lambda kv: kv[1], reverse=True):
                click.echo(f"  {fw:<20} {n} files")
        if s.get("framework_objects"):
            click.echo()
            click.echo(click.style("Framework objects", bold=True))
            for label, n in s["framework_objects"].items():
                if n:
                    click.echo(f"  {label:<24} {n}")


# ---------- query ----------
@cli.command("ask", help="Ask a question about the codebase.")
@click.argument("question")
@click.option("--repo", "repo", type=click.Path(file_okay=False, exists=True), default=".")
@click.option("--budget", type=int, default=DEFAULT_TOKEN_BUDGET, show_default=True,
              help="Token budget for assembled context.")
@click.option("--intent", type=str, default=None,
              help="Force an intent: architecture_explanation, bug_fix, feature_implementation, "
                   "refactor, impact_analysis, test_generation, security_review, api_usage, onboarding.")
@click.option("--mode", type=click.Choice(
    ["explain", "edit", "debug", "refactor", "test", "impact", "security", "onboarding", "feature"]),
    default=None, help="Retrieval mode — controls graph expansion and tier allocation.")
@click.option("--retrieval", type=click.Choice(["auto", "bm25", "hybrid", "vector"]),
              default="auto", show_default=True,
              help="Retrieval strategy. `auto` uses hybrid when embeddings exist, BM25 otherwise.")
@click.option("--pin", "pinned", multiple=True,
              help="Pin a file path (relative to repo) into the retrieval seeds.")
@click.option("--model", default=None, help="Override the Claude model id.")
@click.option("--context-only", is_flag=True, help="Print only the assembled context pack.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def ask_cmd(question: str, repo: str, budget: int, intent: str | None, mode: str | None,
            retrieval: str, pinned: tuple[str, ...], model: str | None,
            context_only: bool, as_json: bool) -> None:
    kb = CodeGraphKB(repo)
    if context_only:
        pack = kb.retrieve_context(question, token_budget=budget, intent=intent, mode=mode,
                                   pinned_files=list(pinned), retrieval=retrieval)
        if as_json:
            click.echo(json.dumps(_pack_to_dict(pack), indent=2))
        else:
            click.echo(pack.to_prompt())
        return

    result = kb.ask(question, token_budget=budget, intent=intent, mode=mode, model=model,
                    pinned_files=list(pinned), retrieval=retrieval)
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


# ---------- eval ----------
@cli.command("eval", help="Run a golden-task dataset and report retrieval metrics.")
@click.argument("dataset", type=click.Path(dir_okay=False, exists=True))
@click.option("--repo", "repo", type=click.Path(file_okay=False, exists=True), default=".")
@click.option("--mode", "retrieval_mode", default="default", show_default=True,
              help="Retrieval strategy: bm25, hybrid, vector, or a free-form label.")
@click.option("--explain", is_flag=True,
              help="Show per-task failure report: missed oracle symbols' ranks, scores, "
                   "and noisy items in the pack.")
@click.option("--compare", default=None,
              help="Comma-separated retrieval modes to compare side-by-side, e.g. "
                   "`--compare bm25,hybrid`.")
@click.option("--json", "as_json", is_flag=True, help="Emit the full report as JSON.")
@click.option("--out", type=click.Path(dir_okay=False), default=None,
              help="Optional path to write the JSON report.")
@click.option("--save-report", "save_report", type=click.Path(dir_okay=False), default=None,
              help="PR 13 — write a structured JSON failure report to this path "
                   "(includes suggested_tuning_actions per task).")
def eval_cmd(dataset: str, repo: str, retrieval_mode: str, explain: bool,
             compare: str | None, as_json: bool, out: str | None,
             save_report: str | None) -> None:
    if compare:
        modes = [m.strip() for m in compare.split(",") if m.strip()]
        reports = {m: eval_mod.evaluate(repo, Path(dataset), retrieval_mode=m) for m in modes}
        if save_report:
            payload = {
                "dataset": str(dataset),
                "retrieval_modes": modes,
                "reports": {m: r.to_dict() for m, r in reports.items()},
            }
            Path(save_report).parent.mkdir(parents=True, exist_ok=True)
            Path(save_report).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if as_json:
            click.echo(json.dumps({m: r.to_dict() for m, r in reports.items()}, indent=2))
            return
        _print_compare_table(reports)
        if explain:
            for m, r in reports.items():
                click.echo()
                click.echo(click.style(f"--- failure report ({m}) ---", bold=True))
                click.echo(r.explain_text() or "  (no failures)")
                actions = _collect_tuning_actions(r)
                if actions:
                    click.echo()
                    click.echo(click.style(f"--- suggested tuning actions ({m}) ---", bold=True))
                    for a in actions[:15]:
                        click.echo(f"  · {a}")
        return

    report = eval_mod.evaluate(repo, Path(dataset), retrieval_mode=retrieval_mode)
    if save_report:
        Path(save_report).parent.mkdir(parents=True, exist_ok=True)
        Path(save_report).write_text(eval_mod.report_to_json(report), encoding="utf-8")
    if out:
        Path(out).write_text(eval_mod.report_to_json(report), encoding="utf-8")
    if as_json:
        click.echo(eval_mod.report_to_json(report))
        return
    click.echo(click.style("CodeGraphKB Eval", bold=True))
    click.echo(report.summary_text())
    click.echo()
    click.echo(click.style("Per-task results", bold=True))
    click.echo(f"{'id':<32} {'mode':<10} {'F@8':>5} {'S@12':>5} {'irr':>5} "
               f"{'excl':>5} {'util':>5} {'lat':>7}")
    for r in report.tasks:
        click.echo(
            f"{r.id:<32} {r.mode:<10} "
            f"{r.file_recall_at_8:>5.2f} {r.symbol_recall_at_12:>5.2f} "
            f"{r.irrelevant_ratio:>5.2f} {r.exclusion_violations:>5d} "
            f"{r.budget_utilization:>5.2f} "
            f"{r.latency_ms:>5.0f}ms"
        )
    if explain:
        text = report.explain_text()
        if text:
            click.echo()
            click.echo(click.style("Failure report", bold=True))
            click.echo(text)
    elif any(r.missing_files or r.missing_symbols or r.excluded_violations for r in report.tasks):
        click.echo()
        click.echo(click.style("Misses (use --explain for full report)", dim=True))
        for r in report.tasks:
            if r.missing_files:
                click.echo(f"  · [{r.id}] missing files:   {', '.join(r.missing_files)}")
            if r.missing_symbols:
                click.echo(f"  · [{r.id}] missing symbols: {', '.join(r.missing_symbols)}")
            if r.excluded_violations:
                click.echo(f"  · [{r.id}] should-exclude violations: {', '.join(r.excluded_violations)}")


def _collect_tuning_actions(report) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for r in report.tasks:
        for action in r.suggested_tuning_actions:
            if action in seen:
                continue
            seen.add(action)
            out.append(f"[{r.id}] {action}")
    return out


def _print_compare_table(reports: dict) -> None:
    click.echo(click.style("CodeGraphKB Eval — comparison", bold=True))
    headers = ["mode", "F@8", "S@12", "irr", "excl", "util", "med ms"]
    click.echo(f"{headers[0]:<10}  {headers[1]:>5}  {headers[2]:>5}  {headers[3]:>5}  "
               f"{headers[4]:>5}  {headers[5]:>5}  {headers[6]:>7}")
    for mode, r in reports.items():
        click.echo(
            f"{mode:<10}  "
            f"{r.file_recall_at_8:>5.2f}  {r.symbol_recall_at_12:>5.2f}  "
            f"{r.irrelevant_ratio:>5.2f}  {r.exclusion_violation_rate:>5.2f}  "
            f"{r.budget_utilization:>5.2f}  {r.median_latency_ms:>5.0f}"
        )


# ---------- Phase 3 edit-context workflow ----------
@cli.command("prepare-edit", help="Compile a focused edit-context pack for an AI coding agent.")
@click.argument("task")
@click.option("--repo", "repo", type=click.Path(file_okay=False, exists=True), default=".")
@click.option("--budget", type=int, default=6000, show_default=True)
@click.option("--pin", "pinned", multiple=True,
              help="Pin a file path into the retrieval seeds.")
@click.option("--json", "as_json", is_flag=True)
def prepare_edit_cmd(task: str, repo: str, budget: int,
                     pinned: tuple[str, ...], as_json: bool) -> None:
    kb = CodeGraphKB(repo)
    pack = workflow_mod.prepare_edit_context(
        kb, task, token_budget=budget, pinned_files=list(pinned),
    )
    if as_json:
        click.echo(pack.to_json())
        return
    click.echo(click.style(f"Edit context for: {task}", bold=True, fg="cyan"))
    click.echo(f"  mode={pack.mode}  est_tokens={pack.audit.get('estimated_tokens')}/{budget}")
    click.echo()
    if pack.summary:
        click.echo(pack.summary)
    if pack.warnings:
        click.echo()
        for w in pack.warnings:
            click.echo(click.style(f"  ! {w}", fg="yellow"))
    if pack.files_likely_to_edit:
        click.echo()
        click.echo(click.style("Files likely to edit", bold=True))
        for fe in pack.files_likely_to_edit:
            click.echo(f"  {fe.confidence:.2f}  {fe.file}")
            click.echo(f"        {fe.reason}")
            if fe.symbols:
                click.echo(f"        symbols: {', '.join(fe.symbols[:4])}")
    if pack.files_to_read_only:
        click.echo()
        click.echo(click.style("Files to read only", bold=True))
        for fe in pack.files_to_read_only:
            click.echo(f"  {fe.confidence:.2f}  {fe.file}  ({fe.reason})")
    if pack.related_tests:
        click.echo()
        click.echo(click.style("Related tests", bold=True))
        for te in pack.related_tests:
            click.echo(f"  {te.confidence:.2f}  {te.file}  ({te.reason})")
    if pack.symbols_to_modify:
        click.echo()
        click.echo(click.style("Symbols to modify", bold=True))
        for se in pack.symbols_to_modify:
            click.echo(f"  {se.confidence:.2f}  {se.symbol}  ({se.file})")
    if pack.callers:
        click.echo()
        click.echo(click.style("Callers", bold=True))
        for se in pack.callers[:6]:
            click.echo(f"  - {se.symbol}  ({se.file})")
    if pack.risks:
        click.echo()
        click.echo(click.style("Risks", bold=True))
        for r in pack.risks:
            click.echo(f"  [{r.level}] {r.title} — {r.reason}")
    if pack.validation_commands:
        click.echo()
        click.echo(click.style("Suggested validation commands", bold=True))
        for vc in pack.validation_commands:
            click.echo(f"  {vc.confidence:.2f}  {vc.command:<40}  ({vc.type}) — {vc.reason}")
    if pack.process_traces:
        click.echo()
        click.echo(click.style("Process traces", bold=True))
        for trace in pack.process_traces:
            click.echo(
                f"  {trace.get('confidence', 0):.2f}  "
                f"[{trace.get('process_type', '?')}]  {trace.get('label', '')}"
            )
            for step in (trace.get("steps") or [])[:6]:
                edge = (step.get("metadata") or {}).get("edge_type", "?")
                click.echo(
                    f"        {step['step']}. {step['src_qname']}  "
                    f"--{edge}-->  {step['dst_qname']}"
                )


@cli.command("tests", help="Find tests related to a file, symbol, or task.")
@click.argument("target")
@click.option("--repo", "repo", type=click.Path(file_okay=False, exists=True), default=".")
@click.option("--task", "as_task", is_flag=True,
              help="Treat TARGET as a free-form task description rather than a file/symbol.")
@click.option("--json", "as_json", is_flag=True)
def tests_cmd(target: str, repo: str, as_task: bool, as_json: bool) -> None:
    kb = CodeGraphKB(repo)
    if as_task:
        results = workflow_mod._related_tests_from_task(kb, target)
    else:
        results = workflow_mod.get_related_tests(kb, target)
    if as_json:
        click.echo(json.dumps([vars(r) for r in results], indent=2))
        return
    if not results:
        click.echo("No related tests found.")
        return
    for te in results:
        click.echo(f"  {te.confidence:.2f}  {te.file}  ({te.reason})")
        for blk in te.test_blocks[:3]:
            if blk:
                click.echo(f"        block: {blk}")


@cli.command("validate-plan", help="Suggest commands to run after editing.")
@click.argument("task")
@click.option("--repo", "repo", type=click.Path(file_okay=False, exists=True), default=".")
@click.option("--json", "as_json", is_flag=True)
def validate_plan_cmd(task: str, repo: str, as_json: bool) -> None:
    kb = CodeGraphKB(repo)
    cmds = workflow_mod.plan_validation_commands(kb, task, [], [])
    if as_json:
        click.echo(json.dumps([vars(c) for c in cmds], indent=2))
        return
    for c in cmds:
        click.echo(f"  {c.confidence:.2f}  [{c.type:<14}]  {c.command}")
        click.echo(f"            {c.reason}")


@cli.command("impact-plan", help="Preview what could break if a file or symbol is edited.")
@click.argument("target")
@click.option("--repo", "repo", type=click.Path(file_okay=False, exists=True), default=".")
@click.option("--task", "as_task", is_flag=True,
              help="Treat TARGET as a free-form task description.")
@click.option("--json", "as_json", is_flag=True)
def impact_plan_cmd(target: str, repo: str, as_task: bool, as_json: bool) -> None:
    kb = CodeGraphKB(repo)
    if as_task:
        # Resolve the task to a likely symbol first
        pack = workflow_mod.prepare_edit_context(kb, target, token_budget=4000)
        if not pack.symbols_to_modify:
            click.echo("Could not resolve task to a concrete symbol.")
            return
        target = pack.symbols_to_modify[0].symbol
    result = workflow_mod.preview_patch_impact(kb, target)
    if as_json:
        click.echo(json.dumps(result, indent=2))
        return
    click.echo(click.style(f"Impact preview: {result['target']}", bold=True))
    click.echo(f"  Risk: {result['risk']}")
    click.echo(f"  Reason: {result.get('reason', '')}")
    if result.get("affected_routes"):
        click.echo("  Affected routes:")
        for r in result["affected_routes"]:
            click.echo(f"    - {r}")
    if result.get("affected_symbols"):
        click.echo("  Affected symbols:")
        for s in result["affected_symbols"][:10]:
            click.echo(f"    - {s}")
    if result.get("affected_tests"):
        click.echo("  Affected test files:")
        for t in result["affected_tests"]:
            click.echo(f"    - {t}")
    if result.get("affected_config"):
        click.echo("  Affected env / config:")
        for c in result["affected_config"]:
            click.echo(f"    - {c}")


@cli.command("eval-edit", help="Evaluate prepare-edit quality on a golden dataset (PR 19).")
@click.argument("dataset", type=click.Path(dir_okay=False, exists=True))
@click.option("--repo", "repo", type=click.Path(file_okay=False, exists=True), default=".")
@click.option("--json", "as_json", is_flag=True)
@click.option("--save", "save_json", type=click.Path(dir_okay=False), default=None,
              help="Write the edit-eval JSON report.")
def eval_edit_cmd(dataset: str, repo: str, as_json: bool, save_json: str | None) -> None:
    from codegraphkb import eval_edit as eval_edit_mod
    report = eval_edit_mod.evaluate_edit(repo, Path(dataset))
    if save_json:
        Path(save_json).parent.mkdir(parents=True, exist_ok=True)
        Path(save_json).write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    if as_json:
        click.echo(json.dumps(report.to_dict(), indent=2))
        return
    click.echo(click.style("CodeGraphKB Edit-Workflow Eval", bold=True))
    click.echo(report.summary_text())
    if report.tasks:
        click.echo()
        click.echo(click.style("Per-task", bold=True))
        click.echo(f"{'id':<32} {'edit@5':>7} {'test@5':>7} {'sym@8':>7} "
                   f"{'val':>5} {'risk':>5} {'lat':>6}")
        for r in report.tasks:
            click.echo(
                f"{r.id:<32} {r.edit_file_recall_at_5:>7.2f} "
                f"{r.related_test_recall_at_5:>7.2f} {r.symbol_recall_at_8:>7.2f} "
                f"{r.validation_command_recall:>5.2f} {r.risk_keyword_recall:>5.2f} "
                f"{r.workflow_latency_ms:>5.0f}ms"
            )


@cli.command("regression-report", help="Run evals and emit the Phase 4 regression report.")
@click.option("--repo", "repo", type=click.Path(file_okay=False, exists=True), default=".")
@click.option("--eval", "eval_dataset", type=click.Path(dir_okay=False, exists=True),
              default=None, help="Golden retrieval dataset to evaluate.")
@click.option("--edit-eval", "edit_eval_dataset", type=click.Path(dir_okay=False, exists=True),
              default=None, help="Golden edit-workflow dataset to evaluate.")
@click.option("--compare", default="bm25,hybrid", show_default=True,
              help="Comma-separated retrieval modes to compare.")
@click.option("--save", "save_json", type=click.Path(dir_okay=False), default=None,
              help="Write machine-readable JSON report.")
@click.option("--markdown", "save_markdown", type=click.Path(dir_okay=False), default=None,
              help="Write Markdown summary report.")
@click.option("--json", "as_json", is_flag=True, help="Print the full report as JSON.")
@click.option("--gate-profile", type=click.Choice(["advisory", "dev", "release"]),
              default="release", show_default=True,
              help="Gate strictness profile. Advisory never hard-fails.")
@click.option("--fail/--no-fail", "fail_on_hard_regression", default=True, show_default=True,
              help="Exit non-zero when a hard regression gate fails.")
def regression_report_cmd(repo: str, eval_dataset: str | None,
                          edit_eval_dataset: str | None, compare: str,
                          save_json: str | None, save_markdown: str | None,
                          as_json: bool, gate_profile: str,
                          fail_on_hard_regression: bool) -> None:
    if not eval_dataset and not edit_eval_dataset:
        raise click.UsageError("Provide --eval, --edit-eval, or both.")
    modes = [m.strip() for m in compare.split(",") if m.strip()]
    report = regression_mod.build_regression_report(
        repo,
        eval_dataset=Path(eval_dataset) if eval_dataset else None,
        edit_eval_dataset=Path(edit_eval_dataset) if edit_eval_dataset else None,
        compare_modes=modes,
        gate_profile=gate_profile,
    )
    regression_mod.write_report_files(
        report,
        json_path=Path(save_json) if save_json else None,
        markdown_path=Path(save_markdown) if save_markdown else None,
    )
    if as_json:
        click.echo(report.to_json())
    else:
        click.echo(regression_mod.summary_text(report))
        if save_json:
            click.echo(f"  json:          {save_json}")
        if save_markdown:
            click.echo(f"  markdown:      {save_markdown}")
    if fail_on_hard_regression and not report.passed:
        sys.exit(1)


# ---------- processes (Phase 3.3) ----------
@cli.group("process", help="Inspect process maps built from the indexed graph.")
def process_group() -> None:
    pass


@process_group.command("list", help="List discovered processes.")
@click.option("--repo", "repo", type=click.Path(file_okay=False, exists=True), default=".")
@click.option("--type", "process_type", type=str, default=None,
              help="Filter by process type (api_flow, ui_to_api_flow, test_flow).")
@click.option("--limit", type=int, default=50, show_default=True)
@click.option("--json", "as_json", is_flag=True)
def process_list_cmd(repo: str, process_type: str | None,
                     limit: int, as_json: bool) -> None:
    kb = CodeGraphKB(repo)
    procs = kb.list_processes(process_type=process_type, limit=limit)
    if as_json:
        click.echo(json.dumps(procs, indent=2))
        return
    if not procs:
        click.echo("No processes found. Re-run `codegraph index <repo>`.")
        return
    click.echo(click.style(f"Processes ({len(procs)})", bold=True))
    click.echo(f"{'type':<18} {'conf':>5} {'steps':>6}  label")
    for p in procs:
        click.echo(
            f"{p['process_type']:<18} {p['confidence']:>5.2f} "
            f"{p['step_count']:>6}  {p['label']}  ({p['id']})"
        )


@process_group.command("show", help="Render the ordered steps of a process.")
@click.argument("process_id")
@click.option("--repo", "repo", type=click.Path(file_okay=False, exists=True), default=".")
@click.option("--json", "as_json", is_flag=True)
def process_show_cmd(process_id: str, repo: str, as_json: bool) -> None:
    kb = CodeGraphKB(repo)
    proc = kb.get_process(process_id)
    if proc is None:
        # Try a relaxed lookup by label/entrypoint substring.
        all_procs = kb.list_processes()
        matches = [
            p for p in all_procs
            if process_id in p["id"] or process_id in p.get("label", "")
            or process_id in p.get("entrypoint_id", "")
        ]
        if matches:
            proc = kb.get_process(matches[0]["id"])
    if proc is None:
        click.echo(f"No process matched `{process_id}`.")
        sys.exit(1)
    if as_json:
        click.echo(json.dumps(proc, indent=2))
        return
    click.echo(click.style(f"{proc['label']}", bold=True))
    click.echo(f"  type:        {proc['process_type']}")
    click.echo(f"  id:          {proc['id']}")
    click.echo(f"  confidence:  {proc['confidence']:.2f}")
    click.echo(f"  entrypoint:  {proc['entrypoint_id']}")
    click.echo(f"  terminal:    {proc['terminal_id']}")
    click.echo(f"  steps ({proc['step_count']}):")
    for step in proc.get("steps", []):
        edge = step["metadata"].get("edge_type", "?")
        click.echo(
            f"    {step['step']:>2}. {step['src_qname']}  "
            f"--{edge}-->  {step['dst_qname']}  "
            f"({step['confidence']:.2f})"
        )


# ---------- exporters (Phase 3.4) ----------
@cli.group("export", help="Export graph/process/impact views as JSON or static HTML.")
def export_group() -> None:
    pass


@export_group.command("graph", help="Export the graph as JSON or static HTML.")
@click.option("--repo", "repo", type=click.Path(file_okay=False, exists=True), default=".")
@click.option("--format", "fmt", type=click.Choice(["json", "html"]),
              default="json", show_default=True)
@click.option("--view", type=click.Choice(
    ["full", "repo", "symbols", "calls", "processes", "framework"]),
    default="full", show_default=True)
@click.option("--out", type=click.Path(dir_okay=False), required=True)
def export_graph_cmd(repo: str, fmt: str, view: str, out: str) -> None:
    from codegraphkb.core.exporters import VIEWS, render_graph_html

    kb = CodeGraphKB(repo)
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "json":
        payload = kb.export_graph(view=view)
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    else:
        views = {v: kb.export_graph(view=v) for v in VIEWS}
        render_graph_html(
            views[view],
            out=out_path,
            title="CodeGraphKB Graph",
            views=views,
            default_view=view,
        )
    click.echo(str(out_path))


@export_group.command("process", help="Export process maps as JSON or static HTML.")
@click.option("--repo", "repo", type=click.Path(file_okay=False, exists=True), default=".")
@click.option("--format", "fmt", type=click.Choice(["json", "html"]),
              default="json", show_default=True)
@click.option("--out", type=click.Path(dir_okay=False), required=True)
def export_process_cmd(repo: str, fmt: str, out: str) -> None:
    from codegraphkb.core.exporters import render_graph_html

    kb = CodeGraphKB(repo)
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = kb.export_processes()

    if fmt == "json":
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    else:
        graph = {
            "metadata": payload["metadata"],
            "nodes": payload["nodes"],
            "edges": payload["edges"],
        }
        render_graph_html(graph, out=out_path, title="CodeGraphKB Processes")
    click.echo(str(out_path))


@export_group.command("impact", help="Export impact graph for a file/symbol target.")
@click.argument("target")
@click.option("--repo", "repo", type=click.Path(file_okay=False, exists=True), default=".")
@click.option("--format", "fmt", type=click.Choice(["json", "html"]),
              default="json", show_default=True)
@click.option("--out", type=click.Path(dir_okay=False), required=True)
def export_impact_cmd(target: str, repo: str, fmt: str, out: str) -> None:
    from codegraphkb.core.exporters import render_graph_html

    kb = CodeGraphKB(repo)
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = kb.export_impact_graph(target)

    if fmt == "json":
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    else:
        render_graph_html(payload, out=out_path, title=f"CodeGraphKB Impact: {target}")
    click.echo(str(out_path))


# ---------- servers ----------
@cli.command("serve", help="Run the MCP or HTTP server.")
@click.argument("kind", type=click.Choice(["mcp", "api", "ui"]))
@click.option("--repo", "repo", type=click.Path(file_okay=False, exists=True), default=".")
@click.option("--host", default="127.0.0.1")
@click.option("--port", type=int, default=8765)
def serve_cmd(kind: str, repo: str, host: str, port: int) -> None:
    if kind == "mcp":
        from codegraphkb.server.mcp_server import run_stdio
        run_stdio(repo)
    elif kind == "api":
        try:
            from codegraphkb.server.api_server import run_api
        except ImportError as exc:  # pragma: no cover
            click.echo(f"Install codegraphkb[api] first: {exc}", err=True)
            sys.exit(1)
        run_api(repo, host=host, port=port)
    else:
        try:
            from codegraphkb.server.ui_server import run_ui
        except ImportError as exc:  # pragma: no cover
            click.echo(f"Install codegraphkb[api] first: {exc}", err=True)
            sys.exit(1)
        run_ui(repo, host=host, port=port)


def _pack_to_dict(pack) -> dict:
    return {
        "intent": pack.intent.value,
        "mode": pack.mode.value,
        "retrieval_mode": pack.retrieval_mode,
        "estimated_tokens": pack.estimated_tokens,
        "graph_paths": pack.graph_paths,
        "files_likely_to_edit": pack.files_likely_to_edit,
        "related_tests": pack.related_tests,
        "audit": pack.audit,
        "items": [
            {
                "kind": it.kind,
                "title": it.title,
                "file_path": it.file_path,
                "start_line": it.start_line,
                "end_line": it.end_line,
                "score": it.score,
                "tokens": it.tokens,
                "retrieval_sources": it.retrieval_sources,
                "score_breakdown": it.score_breakdown.as_dict(),
                "graph_path": it.graph_path,
                "confidence": it.confidence,
                "reason": it.reason,
                "body": it.body,
            }
            for it in pack.items
        ],
        "repo_map": pack.repo_map,
    }


if __name__ == "__main__":
    main()
