"""Phase 3 edit-context compiler — the flagship workflow.

Given a coding task, produce a structured packet that an AI coding agent can
trust before making real edits:

  - files_likely_to_edit  (with reasons)
  - files_to_read_only    (helpful but not modified)
  - related_tests
  - symbols_to_modify
  - callers / callees of those symbols
  - risks (PR 18)
  - validation_commands (PR 17)
  - context_pack (Phase 2 capsules + snippets)
  - audit metadata

The workflow is:

  user task → retrieve_context (hybrid) → classify each candidate as
  edit/read/test/risk/exclude → compute callers+callees → run impact preview →
  detect repo build/test runners → assemble.

This module stays pure-Python and reuses the Phase 2 retrieval pipeline.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codegraphkb.config import DEFAULT_TOKEN_BUDGET
from codegraphkb.core.noise import _GENERIC_NAMES
from codegraphkb.core.retrieval import (
    ContextItem, ContextPack, Mode, RankedCandidate, ScoreBreakdown,
)
from codegraphkb.core.store import GraphStore, SymbolRow


# ---------- output dataclasses ----------

@dataclass
class FileEntry:
    file: str
    reason: str
    confidence: float
    symbols: list[str] = field(default_factory=list)


@dataclass
class TestEntry:
    file: str
    reason: str
    confidence: float
    test_blocks: list[str] = field(default_factory=list)


@dataclass
class SymbolEntry:
    symbol: str
    file: str
    reason: str
    confidence: float


@dataclass
class RiskItem:
    title: str
    level: str        # low | medium | high | unknown
    reason: str
    affected: list[str] = field(default_factory=list)
    task_keywords: list[str] = field(default_factory=list)


@dataclass
class ValidationCommand:
    command: str
    type: str         # targeted_test | full_test | typecheck | lint | build | format_check | security_check
    reason: str
    confidence: float


@dataclass
class EditContextPack:
    task: str
    mode: str
    summary: str
    files_likely_to_edit: list[FileEntry] = field(default_factory=list)
    files_to_read_only: list[FileEntry] = field(default_factory=list)
    related_tests: list[TestEntry] = field(default_factory=list)
    symbols_to_modify: list[SymbolEntry] = field(default_factory=list)
    callers: list[SymbolEntry] = field(default_factory=list)
    callees: list[SymbolEntry] = field(default_factory=list)
    risks: list[RiskItem] = field(default_factory=list)
    validation_commands: list[ValidationCommand] = field(default_factory=list)
    context_pack: list[dict] = field(default_factory=list)
    process_traces: list[dict] = field(default_factory=list)
    audit: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        def _list(items):
            return [vars(it) for it in items]
        return {
            "task": self.task,
            "mode": self.mode,
            "summary": self.summary,
            "files_likely_to_edit": _list(self.files_likely_to_edit),
            "files_to_read_only": _list(self.files_to_read_only),
            "related_tests": _list(self.related_tests),
            "symbols_to_modify": _list(self.symbols_to_modify),
            "callers": _list(self.callers),
            "callees": _list(self.callees),
            "risks": _list(self.risks),
            "validation_commands": _list(self.validation_commands),
            "context_pack": self.context_pack,
            "process_traces": self.process_traces,
            "audit": self.audit,
            "warnings": self.warnings,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


# ---------- core workflow ----------

def prepare_edit_context(
    kb,
    task: str,
    *,
    token_budget: int = 6000,
    pinned_files: list[str] | None = None,
) -> EditContextPack:
    """Build the full edit-context pack for a coding task. (PR 15)"""
    total_started = time.perf_counter()
    timing: dict[str, float] = {
        "intent_classification": 0.0,
        "retrieval": 0.0,
        "test_discovery": 0.0,
        "validation_planning": 0.0,
        "impact_preview": 0.0,
        "risk_generation": 0.0,
        "context_assembly": 0.0,
        "total": 0.0,
    }

    started = time.perf_counter()
    pack = kb.retrieve_context(
        task,
        token_budget=token_budget,
        mode=Mode.EDIT,
        pinned_files=pinned_files or [],
        retrieval="auto",
    )
    timing["retrieval"] = _elapsed_ms(started)

    started = time.perf_counter()
    classification = _classify_candidates(pack, task)
    timing["context_assembly"] += _elapsed_ms(started)

    started = time.perf_counter()
    if not classification["tests"]:
        classification["tests"] = _related_tests_from_task(kb, task)
    timing["test_discovery"] = _elapsed_ms(started)

    started = time.perf_counter()
    out = EditContextPack(
        task=task,
        mode=pack.mode.value,
        summary=_summarize_intent(task, classification),
    )
    out.files_likely_to_edit = classification["edit"]
    out.files_to_read_only = classification["read"]
    out.related_tests = classification["tests"]
    out.symbols_to_modify = classification["symbols_to_modify"]
    out.context_pack = _serialize_pack_items(pack.items)
    out.process_traces = _gather_process_traces(kb, classification, pack)
    timing["context_assembly"] += _elapsed_ms(started)

    # Callers/callees for the top symbols-to-modify (PR 18 input)
    started = time.perf_counter()
    cc = _gather_callers_callees(kb, classification["symbols_to_modify"])
    out.callers = cc["callers"]
    out.callees = cc["callees"]
    timing["impact_preview"] = _elapsed_ms(started)

    # Risk preview (PR 18)
    started = time.perf_counter()
    out.risks = _compute_risks(kb, classification, pack, task)
    timing["risk_generation"] = _elapsed_ms(started)

    # Validation commands (PR 17)
    started = time.perf_counter()
    out.validation_commands = plan_validation_commands(
        kb, task, classification["edit"], classification["tests"]
    )
    timing["validation_planning"] = _elapsed_ms(started)
    timing["total"] = _elapsed_ms(total_started)

    out.audit = {
        "budget": token_budget,
        "estimated_tokens": pack.estimated_tokens,
        "intent": pack.intent.value,
        "retrieval_sources": _aggregate_sources(pack),
        "graph_paths": pack.graph_paths,
        "audit": pack.audit,
        "timing_ms": timing,
    }
    if not classification["edit"]:
        out.warnings.append("No file confidently identified as 'likely to edit' — "
                            "consider pinning a file or refining the task description.")
    if not classification["tests"]:
        out.warnings.append("No related tests detected — coverage may be missing.")
    return out


# ---------- process trace integration ----------

def _gather_process_traces(kb, classification: dict, pack) -> list[dict]:
    """Phase 3.3 — pull process maps relevant to the candidate symbols.

    We collect symbols from ``symbols_to_modify`` plus the top-ranked context
    items, then look up process traces touching any of those symbols. Traces
    are deduped by id and ranked by confidence, capped at five.
    """
    qnames: list[str] = []
    seen: set[str] = set()
    for sym in classification.get("symbols_to_modify", []):
        if sym.symbol and sym.symbol not in seen:
            seen.add(sym.symbol)
            qnames.append(sym.symbol)
    for item in (pack.items or [])[:8]:
        title = getattr(item, "title", "") or ""
        if title and title not in seen:
            seen.add(title)
            qnames.append(title)
    if not qnames:
        return []

    traces_by_id: dict[str, dict] = {}
    for qname in qnames:
        try:
            matches = kb.find_processes_for_symbol(qname, limit=3)
        except Exception:
            continue
        for proc in matches:
            if proc and proc["id"] not in traces_by_id:
                traces_by_id[proc["id"]] = proc
    ranked = sorted(traces_by_id.values(),
                    key=lambda p: p.get("confidence", 0.0), reverse=True)
    return ranked[:5]


# ---------- classification ----------

def _classify_candidates(pack: ContextPack, task: str) -> dict[str, list]:
    """Phase 3 classifier: split pack candidates into edit/read/test/symbols.

    Heuristics:
      - test capsules → tests bucket
      - high-final-score, function/method/route in capsule items → likely_edit
      - same-file siblings of a likely-edit symbol → already in pack → read or edit
      - capsules with low final score but file overlap with edits → read-only
    """
    q_terms = _query_terms(task)
    edit_files: dict[str, FileEntry] = {}
    read_files: dict[str, FileEntry] = {}
    tests: dict[str, TestEntry] = {}
    syms_to_modify: list[SymbolEntry] = []

    seen_sym_qnames: set[str] = set()
    for item in pack.items:
        if item.kind not in {"capsule", "snippet"}:
            continue
        qname = _qname(item.title)
        kind = _kind_from_pack(pack, qname)
        path = item.file_path or ""
        is_test = (
            kind == "test_block" or kind == "fixture" or kind == "test"
            or "/tests/" in "/" + path.lower() + "/"
            or "/test/" in "/" + path.lower() + "/"
            or "/__tests__/" in "/" + path.lower() + "/"
            or path.lower().endswith(("_test.py", ".test.ts", ".test.tsx",
                                       ".test.js", ".test.jsx", ".spec.ts", ".spec.js"))
        )
        score = item.score_breakdown.final
        if is_test:
            existing = tests.get(path)
            reason = f"Test file with score {score:.2f} for `{task[:60]}`"
            if existing is None:
                tests[path] = TestEntry(file=path, reason=reason,
                                        confidence=min(0.95, score),
                                        test_blocks=[item.title.split(":", 1)[-1].strip()])
            else:
                existing.test_blocks.append(item.title.split(":", 1)[-1].strip())
            continue

        # Decide if this is a primary edit symbol or a read-only support.
        identifier_overlap = item.score_breakdown.identifier_overlap
        is_modifiable = kind in {"function", "method", "component", "route", "class"}
        is_high_value = score >= 0.45 or (
            score >= 0.38 and identifier_overlap >= 0.25
        )
        if is_modifiable and is_high_value and not _looks_generic(qname, q_terms):
            entry = edit_files.get(path)
            if entry is None:
                edit_files[path] = FileEntry(
                    file=path,
                    reason=_reason_for_edit(item, q_terms),
                    confidence=min(0.97, score + 0.05),
                    symbols=[qname],
                )
            else:
                if qname not in entry.symbols:
                    entry.symbols.append(qname)
                entry.confidence = max(entry.confidence, min(0.97, score + 0.05))
            if qname not in seen_sym_qnames and len(syms_to_modify) < 8:
                seen_sym_qnames.add(qname)
                syms_to_modify.append(SymbolEntry(
                    symbol=qname, file=path,
                    reason=_reason_for_edit(item, q_terms),
                    confidence=min(0.97, score + 0.05),
                ))
        else:
            entry = read_files.get(path)
            if entry is None:
                read_files[path] = FileEntry(
                    file=path,
                    reason=_reason_for_read(item),
                    confidence=min(0.85, score),
                    symbols=[qname],
                )
            else:
                if qname not in entry.symbols:
                    entry.symbols.append(qname)

    # Files that appear in both buckets — edit wins.
    for path in list(read_files.keys()):
        if path in edit_files:
            del read_files[path]

    return {
        "edit": sorted(edit_files.values(), key=lambda e: e.confidence, reverse=True),
        "read": sorted(read_files.values(), key=lambda e: e.confidence, reverse=True)[:6],
        "tests": sorted(tests.values(), key=lambda e: e.confidence, reverse=True)[:6],
        "symbols_to_modify": syms_to_modify,
    }


def _kind_from_pack(pack: ContextPack, qname: str) -> str:
    for cand in pack.ranked_candidates:
        if cand.qualified_name == qname:
            return cand.kind
    return ""


def _looks_generic(qname: str, q_terms: set[str]) -> bool:
    last = qname.rsplit(".", 1)[-1]
    if last.lower() in _GENERIC_NAMES and last.lower() not in q_terms:
        return True
    return False


def _reason_for_edit(item: ContextItem, q_terms: set[str]) -> str:
    sb = item.score_breakdown
    bits: list[str] = []
    if sb.bm25 > 0.5:
        bits.append("strong lexical match")
    if sb.vector > 0.5:
        bits.append("strong semantic match")
    if sb.identifier_overlap > 0.3:
        bits.append("name overlaps with task")
    if sb.graph > 0.3:
        bits.append("close in call graph")
    if not bits:
        bits.append("retrieved by hybrid pipeline")
    return f"Likely-edit: {'; '.join(bits)} (score {sb.final:.2f})"


def _reason_for_read(item: ContextItem) -> str:
    sb = item.score_breakdown
    return f"Read-only support — reached via {','.join(item.retrieval_sources) or 'graph'} (score {sb.final:.2f})"


# ---------- callers / callees ----------

def _gather_callers_callees(kb, symbols_to_modify: list[SymbolEntry]) -> dict[str, list[SymbolEntry]]:
    out_callers: list[SymbolEntry] = []
    out_callees: list[SymbolEntry] = []
    seen: set[str] = set()
    try:
        store = kb._open_store()
    except FileNotFoundError:
        return {"callers": [], "callees": []}
    try:
        for sym_entry in symbols_to_modify[:5]:
            for edge in store.incoming(sym_entry.symbol, ["CALLS", "ROUTES_TO"]):
                src = store.find_symbol(edge.src_qname)
                if not src or src.qualified_name in seen:
                    continue
                seen.add(src.qualified_name)
                out_callers.append(SymbolEntry(
                    symbol=src.qualified_name,
                    file=src.file_path,
                    reason=f"Calls `{sym_entry.symbol}`",
                    confidence=0.8,
                ))
            for edge in store.outgoing(sym_entry.symbol, ["CALLS"]):
                target = store.find_symbol(edge.dst_qname) if edge.dst_qname else None
                if target is None and edge.dst_name:
                    by_name = store.find_symbols_by_name(edge.dst_name, limit=1)
                    target = by_name[0] if by_name else None
                if not target or target.qualified_name in seen:
                    continue
                seen.add(target.qualified_name)
                out_callees.append(SymbolEntry(
                    symbol=target.qualified_name,
                    file=target.file_path,
                    reason=f"Called from `{sym_entry.symbol}`",
                    confidence=0.7,
                ))
    finally:
        store.close()
    return {"callers": out_callers[:8], "callees": out_callees[:8]}


# ---------- impact / risk preview (PR 18) ----------

def _compute_risks(kb, classification: dict, pack: ContextPack, task: str = "") -> list[RiskItem]:
    risks: list[RiskItem] = []
    edit_files = [fe.file for fe in classification["edit"]]
    support_files = [fe.file for fe in classification["read"]]
    syms_to_modify = classification["symbols_to_modify"]
    task_keywords = _risk_keywords_from_task(task)
    if not task_keywords:
        task_keywords = _risk_keywords_from_entries(classification)
    if task_keywords and (edit_files or support_files or syms_to_modify):
        risks.append(RiskItem(
            title=f"{_keyword_title(task_keywords)} change impact",
            level="medium",
            reason=f"The task is specifically about {_keyword_phrase(task_keywords)}; verify the selected context and nearby tests before editing.",
            affected=(edit_files or support_files)[:5],
            task_keywords=task_keywords,
        ))
    if not syms_to_modify:
        if task_keywords and not classification["tests"]:
            risks.append(RiskItem(
                title=f"{_keyword_title(task_keywords)} changes lack nearby tests",
                level="medium",
                reason=f"The task mentions {_keyword_phrase(task_keywords)} but no related tests were detected.",
                affected=edit_files[:5],
                task_keywords=task_keywords,
            ))
        return risks

    # 1. Auth/security keywords in any symbol-to-modify
    AUTH_RE = re.compile(r"\b(auth|login|session|token|secret|jwt|credential|password|permission)\b", re.I)
    for entry in syms_to_modify:
        if AUTH_RE.search(entry.symbol):
            risks.append(RiskItem(
                title=f"{_keyword_title(task_keywords) or 'Auth/security'} code path",
                level="high",
                reason=f"`{entry.symbol}` matches auth/security keywords for {_keyword_phrase(task_keywords)}.",
                affected=[entry.symbol],
                task_keywords=task_keywords,
            ))
            break

    # 2. Symbols connected to many callers (route exposure / cross-file fan-out)
    store = kb._open_store()
    try:
        many_callers: list[str] = []
        affected_routes: list[str] = []
        for entry in syms_to_modify[:5]:
            inc = store.incoming(entry.symbol, ["CALLS", "ROUTES_TO", "ROUTE_HANDLED_BY"])
            if len(inc) >= 5:
                many_callers.append(f"{entry.symbol} (callers={len(inc)})")
            for edge in inc:
                if edge.edge_type in {"ROUTES_TO", "ROUTE_HANDLED_BY"}:
                    affected_routes.append(edge.src_qname)
        if many_callers:
            risks.append(RiskItem(
                title=f"{_keyword_title(task_keywords) or 'High-fan-out'} symbol",
                level="medium",
                reason=f"Multiple callers depend on {_keyword_phrase(task_keywords)} symbols; downstream regressions are likely.",
                affected=many_callers,
                task_keywords=task_keywords,
            ))
        if affected_routes:
            risks.append(RiskItem(
                title=f"{_keyword_title(task_keywords) or 'HTTP route'} exposure",
                level="medium",
                reason=f"Symbols related to {_keyword_phrase(task_keywords)} are reachable from public route handlers.",
                affected=list(dict.fromkeys(affected_routes))[:5],
                task_keywords=task_keywords,
            ))
    finally:
        store.close()

    # 3. Tests missing
    if not classification["tests"]:
        risks.append(RiskItem(
            title=f"{_keyword_title(task_keywords) or 'No'} related tests detected",
            level="medium",
            reason=f"Edits for {_keyword_phrase(task_keywords)} will land without nearby test coverage to catch regressions.",
            affected=edit_files[:5],
            task_keywords=task_keywords,
        ))
    return risks


def preview_patch_impact(kb, target: str) -> dict:
    """PR 18 — standalone impact preview for a file or symbol."""
    matches = kb.resolve_symbol(target)
    if not matches:
        return {"target": target, "risk": "unknown", "reason": "Target not found."}
    seed = matches[0]
    store = kb._open_store()
    try:
        inc_routes: list[str] = []
        affected_symbols: list[str] = []
        affected_tests: set[str] = set()
        for edge in store.incoming(seed.qualified_name, ["CALLS", "ROUTES_TO",
                                                          "ROUTE_HANDLED_BY", "TESTS",
                                                          "TESTS_SYMBOL"]):
            if edge.edge_type in {"ROUTES_TO", "ROUTE_HANDLED_BY"}:
                inc_routes.append(edge.src_qname)
            elif edge.edge_type in {"TESTS", "TESTS_SYMBOL"}:
                src = store.find_symbol(edge.src_qname)
                if src:
                    affected_tests.add(src.file_path)
            else:
                src = store.find_symbol(edge.src_qname)
                if src:
                    affected_symbols.append(src.qualified_name)
        env_reads = [e.dst_name for e in store.outgoing(seed.qualified_name, ["READS_ENV_VAR"])]
    finally:
        store.close()

    risk_level = _risk_level(seed.qualified_name, len(affected_symbols),
                             len(inc_routes), bool(affected_tests))
    return {
        "target": seed.qualified_name,
        "risk": risk_level,
        "affected_routes": list(dict.fromkeys(inc_routes))[:10],
        "affected_symbols": affected_symbols[:15],
        "affected_tests": sorted(affected_tests)[:8],
        "affected_config": env_reads[:8],
        "reason": _risk_reason(seed.qualified_name, affected_symbols, inc_routes,
                               affected_tests, risk_level),
    }


def _risk_level(qname: str, n_callers: int, n_routes: int, has_tests: bool) -> str:
    qn = qname.lower()
    if any(kw in qn for kw in ("auth", "login", "session", "token", "secret",
                                "credential", "password", "permission", "billing", "payment")):
        return "high"
    if n_routes >= 1 and n_callers >= 5:
        return "high"
    if n_routes >= 1 or n_callers >= 8:
        return "medium"
    if n_callers >= 3:
        return "medium" if not has_tests else "low"
    if n_callers == 0 and n_routes == 0:
        return "low"
    return "low"


def _risk_reason(qname: str, callers: list, routes: list, tests, level: str) -> str:
    parts = []
    if routes:
        parts.append(f"reachable from {len(routes)} route(s)")
    if callers:
        parts.append(f"{len(callers)} caller(s) in graph")
    if tests:
        parts.append(f"{len(tests)} related test file(s)")
    else:
        parts.append("no related tests")
    return f"`{qname}` is {level} risk — " + ", ".join(parts) + "."


# ---------- validation command planner (PR 17) ----------

def plan_validation_commands(kb, task: str, edit_files: list, related_tests: list) -> list[ValidationCommand]:
    """Inspect the repo for build/test runners and propose commands."""
    repo = Path(kb.config.repo_path)
    cmds: list[ValidationCommand] = []
    has_pkg = (repo / "package.json").exists()
    has_pyproject = (repo / "pyproject.toml").exists() or (repo / "setup.cfg").exists()
    has_pytest_ini = (repo / "pytest.ini").exists() or (repo / "tox.ini").exists()
    has_makefile = (repo / "Makefile").exists()

    # Targeted test command using a salient keyword from the task.
    keyword = _task_keyword(task)
    if related_tests and has_pkg:
        cmds.append(ValidationCommand(
            command=f"npm test -- {keyword}" if keyword else "npm test",
            type="targeted_test",
            reason=f"package.json detected; running tests filtered by `{keyword or 'all'}`.",
            confidence=0.82,
        ))
    if related_tests and (has_pyproject or has_pytest_ini):
        if keyword:
            cmds.append(ValidationCommand(
                command=f"pytest -k {keyword}",
                type="targeted_test",
                reason=f"pytest configured; targeted run on `{keyword}`.",
                confidence=0.85,
            ))
        else:
            cmds.append(ValidationCommand(
                command="pytest",
                type="full_test",
                reason="pytest configured; running full test suite.",
                confidence=0.7,
            ))

    if has_pkg:
        scripts = _read_pkg_scripts(repo / "package.json")
        if "typecheck" in scripts:
            cmds.append(ValidationCommand(
                command="npm run typecheck",
                type="typecheck",
                reason="package.json defines a `typecheck` script.",
                confidence=0.8,
            ))
        if "lint" in scripts:
            cmds.append(ValidationCommand(
                command="npm run lint",
                type="lint",
                reason="package.json defines a `lint` script.",
                confidence=0.75,
            ))
        if "build" in scripts:
            cmds.append(ValidationCommand(
                command="npm run build",
                type="build",
                reason="package.json defines a `build` script.",
                confidence=0.65,
            ))

    if has_pyproject:
        cmds.append(ValidationCommand(
            command="python -m mypy .",
            type="typecheck",
            reason="pyproject.toml present — try mypy if configured.",
            confidence=0.55,
        ))
    if has_makefile:
        cmds.append(ValidationCommand(
            command="make test",
            type="targeted_test",
            reason="Makefile present — `make test` is a common entrypoint.",
            confidence=0.6,
        ))
    if (repo / "go.mod").exists():
        cmds.append(ValidationCommand(
            command="go test ./...",
            type="full_test",
            reason="go.mod present.",
            confidence=0.85,
        ))
    if (repo / "Cargo.toml").exists():
        cmds.append(ValidationCommand(
            command="cargo test",
            type="full_test",
            reason="Cargo.toml present.",
            confidence=0.85,
        ))
    if not cmds:
        cmds.append(ValidationCommand(
            command="(no runner detected — verify changes manually)",
            type="full_test",
            reason="No package.json / pyproject.toml / Makefile / go.mod found.",
            confidence=0.2,
        ))
    return cmds


def _read_pkg_scripts(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data.get("scripts", {}) or {}


# ---------- related test discovery (PR 16) ----------

def get_related_tests(kb, target: str, *, limit: int = 5) -> list[TestEntry]:
    matches = kb.resolve_symbol(target)
    if not matches:
        # Treat as a free-form task
        return _related_tests_from_task(kb, target, limit=limit)
    seed = matches[0]
    out: dict[str, TestEntry] = {}
    store = kb._open_store()
    try:
        # 1. Direct TESTS / TESTS_SYMBOL edges into seed
        for edge in store.incoming(seed.qualified_name, ["TESTS", "TESTS_SYMBOL"]):
            src = store.find_symbol(edge.src_qname)
            if src:
                _bump_test(out, src.file_path,
                           f"Test calls `{seed.qualified_name}`", 0.92,
                           src.qualified_name)

        # 2. Same-file or import-based heuristic
        for path in store.known_files():
            if "test" not in path.lower() and "spec" not in path.lower():
                continue
            file = store.get_file(path)
            if not file:
                continue
            short_target = seed.qualified_name.rsplit(".", 1)[-1]
            if short_target in file.content or seed.file_path.split("/")[-1] in file.content:
                conf = 0.78 if short_target in file.content else 0.6
                _bump_test(out, path,
                           f"Test file references `{short_target}`", conf, "")
    finally:
        store.close()
    return sorted(out.values(), key=lambda t: t.confidence, reverse=True)[:limit]


def _related_tests_from_task(kb, task: str, *, limit: int = 5) -> list[TestEntry]:
    keyword = _task_keyword(task) or ""
    out: dict[str, TestEntry] = {}
    fallback_paths: list[str] = []
    store = kb._open_store()
    try:
        for path in store.known_files():
            pl = path.lower()
            if not ("test" in pl or "spec" in pl):
                continue
            fallback_paths.append(path)
            file = store.get_file(path)
            if not file:
                continue
            if keyword and keyword.lower() in file.content.lower():
                _bump_test(out, path,
                           f"Test file mentions `{keyword}`", 0.65, "")
    finally:
        store.close()
    if not out:
        for path in sorted(fallback_paths, key=_test_path_priority)[:limit]:
            _bump_test(out, path, "Fallback test file for edit workflow", 0.35, "")
    return sorted(out.values(), key=lambda t: t.confidence, reverse=True)[:limit]


def _bump_test(into: dict, path: str, reason: str, conf: float, block: str):
    ent = into.get(path)
    if ent is None:
        into[path] = TestEntry(file=path, reason=reason, confidence=conf,
                               test_blocks=[block] if block else [])
    else:
        if conf > ent.confidence:
            ent.confidence = conf
            ent.reason = reason
        if block and block not in ent.test_blocks:
            ent.test_blocks.append(block)


def _test_path_priority(path: str) -> tuple[int, str]:
    name = path.rsplit("/", 1)[-1].lower()
    is_test_file = (
        name.startswith("test_")
        or name.endswith(("_test.py", ".test.ts", ".test.tsx", ".test.js", ".spec.ts", ".spec.js"))
    )
    is_fixture = "/fixtures/" in "/" + path.lower() + "/"
    return (0 if is_test_file else 1, 1 if is_fixture else 0, path)


# ---------- helpers ----------

def _qname(title: str) -> str:
    parts = title.split(":", 1)
    if len(parts) != 2:
        return ""
    return parts[1].strip()


def _query_terms(question: str) -> set[str]:
    return {tok.lower() for tok in re.findall(r"[A-Za-z][A-Za-z0-9_]+", question)}


def _summarize_intent(task: str, classification: dict) -> str:
    n_edit = len(classification["edit"])
    n_test = len(classification["tests"])
    if n_edit == 0:
        return f"Task: {task[:120]} — no high-confidence edit target identified."
    files = ", ".join(f.file for f in classification["edit"][:3])
    return (f"Task: {task[:120]}. Likely edits: {n_edit} file(s), {n_test} related test(s). "
            f"Top files: {files}")


def _task_keyword(task: str) -> str | None:
    # pick the most distinctive identifier-like token from the task
    candidates = re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", task)
    if not candidates:
        return None
    stopwords = {"the", "and", "for", "with", "from", "into", "that", "this",
                 "make", "take", "feature", "implement", "refactor", "debug",
                 "test", "tests", "fix", "add", "modify", "change", "update",
                 "improve", "build", "create", "file", "files", "code", "logic"}
    best = None
    for tok in candidates:
        if tok.lower() in stopwords:
            continue
        if best is None or len(tok) > len(best):
            best = tok
    return best


def _aggregate_sources(pack: ContextPack) -> list[str]:
    counts: dict[str, int] = {}
    for it in pack.items:
        for s in it.retrieval_sources:
            counts[s] = counts.get(s, 0) + 1
    return [f"{src}:{n}" for src, n in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)]


def _serialize_pack_items(items: list[ContextItem]) -> list[dict]:
    out: list[dict] = []
    for it in items:
        out.append({
            "kind": it.kind,
            "title": it.title,
            "file_path": it.file_path,
            "start_line": it.start_line,
            "end_line": it.end_line,
            "tokens": it.tokens,
            "score": it.score_breakdown.final,
            "retrieval_sources": it.retrieval_sources,
        })
    return out


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


def _risk_keywords_from_task(task: str, *, limit: int = 5) -> list[str]:
    words = [tok.lower() for tok in re.findall(r"[A-Za-z][A-Za-z0-9_+-]{2,}", task)]
    stop = {"add", "new", "the", "and", "for", "with", "from", "into", "that",
            "this", "change", "update", "modify", "fix", "make", "more", "less",
            "include", "returns", "return", "code", "file", "files", "logic"}
    out: list[str] = []
    for word in words:
        normalized = word.strip("`'\"").replace("_", "-")
        if normalized in stop or normalized in out:
            continue
        out.append(normalized)
        if len(out) >= limit:
            break
    if any(w in words for w in ("ignore", "scanner", "secret", "credential")) and "secret" not in out:
        out.insert(0, "secret")
    return out


def _risk_keywords_from_entries(classification: dict, *, limit: int = 5) -> list[str]:
    text = " ".join(
        [s.symbol for s in classification.get("symbols_to_modify", [])]
        + [f.file for f in classification.get("edit", [])]
    )
    return _risk_keywords_from_task(text, limit=limit)


def _keyword_title(keywords: list[str]) -> str:
    if not keywords:
        return ""
    return " / ".join(k.replace("-", " ") for k in keywords[:3]).title()


def _keyword_phrase(keywords: list[str]) -> str:
    if not keywords:
        return "the task"
    return ", ".join(k.replace("-", " ") for k in keywords[:4])
