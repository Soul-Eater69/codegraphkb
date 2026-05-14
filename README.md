# CodeGraphKB

> A context compiler for Claude, Cursor, Codex, and other coding agents.

## What is CodeGraphKB?

CodeGraphKB is a graph-powered context compiler for AI coding agents. It indexes
a repo into files, symbols, calls, routes, tests, and config signals, then
produces compact context packs for questions and edit tasks.

Convert a codebase into a graph-powered knowledge base, then serve **only the smallest useful context** to your LLM — or compile a complete edit-context pack (files to edit, files to read, related tests, validation commands, risks) before an agent starts editing.

Instead of pasting whole repos into Claude / Cursor / GPT, CodeGraphKB:

1. Indexes the repo once into a structural graph (files → functions → calls → routes → tests).
2. Generates compact **Context Capsules** for every symbol.
3. On a question, picks seed nodes, expands the graph by *intent*, ranks, and assembles a **token-budgeted Context Pack**.
4. Sends only that pack to the LLM — or returns it as plain text in offline mode.

The engine ships as a **library**, a **CLI**, an **MCP server**, and an optional **HTTP API**. Same core, four front doors.

---

## Status

**Status: local-first alpha**

| Area | Status |
|---|---|
| CLI | Works |
| MCP | Works |
| Product API | Preview |
| ZIP/GitHub import | Preview |
| Web product UI | Preview |
| Python | First-class |
| JS/TS | First-class/Beta |
| Java | Beta |
| Go/C#/Rust/Kotlin | Beta structural parsing |

The beta language providers focus on structural parsing and useful local
retrieval. Do not treat them as deep semantic analyzers yet.

---

## Quick start

```bash
python -m pip install -e ".[all,dev]"
codegraph index . --embed    # one-time scan; re-runs are incremental
codegraph ask "How does the upload flow work?"
codegraph prepare-edit "Add a new endpoint for project upload" --json
codegraph impact src/payments/stripe.ts
codegraph doctor             # diagnose parser/schema/embeddings state
codegraph stats
codegraph eval evals/datasets/self_repo_tasks.yaml
```

Optional extras:

```bash
pip install -e ".[llm]"          # Claude-backed answers (set ANTHROPIC_API_KEY)
pip install -e ".[api]"          # FastAPI HTTP server
pip install -e ".[parser]"       # tree-sitter for accurate JS/TS/JSX/TSX parsing
pip install -e ".[embeddings]"   # fastembed for semantic retrieval
pip install -e ".[all]"
```

Phase 2 / 2.5 capabilities (all opt-in, all backward-compatible):

```bash
codegraph index . --parser tree-sitter --embed
codegraph ask "Add refresh token rotation" --mode edit --retrieval hybrid --budget 6000 --json
codegraph eval evals/datasets/self_repo_tasks.yaml --compare bm25,hybrid --explain
```

Phase 3 — edit-context compiler:

```bash
codegraph prepare-edit "Add a new MCP tool for related tests" --budget 6000 --json
codegraph tests src/codegraphkb/core/retrieval.py
codegraph validate-plan "Add refresh token rotation"
codegraph impact-plan src/codegraphkb/core/store.py
codegraph eval-edit evals/datasets/self_repo_tasks.yaml
```

### Product API and UI preview

```bash
python -m codegraphkb.server.run_product_api
npm --prefix ui run dev
```

Open `http://localhost:5173/projects` to import a public GitHub repo or upload
a ZIP, watch the index job, ask questions, and generate prepare-edit plans.

Phase 4 â€” regression reporting:

```bash
codegraph regression-report \
  --eval evals/datasets/self_repo_tasks.yaml \
  --edit-eval evals/datasets/self_repo_tasks.yaml \
  --compare bm25,hybrid \
  --save reports/latest.json \
  --markdown reports/latest.md \
  --gate-profile release
codegraph doctor --json
scripts/reproduce_phase3_baseline.ps1   # Windows
scripts/reproduce_phase3_baseline.sh    # macOS/Linux
```

### Edit-workflow scoreboard (PR 19)

| Metric | Result | Target |
|---|---:|---:|
| Edit file recall@5 | **1.00** | ≥ 0.80 ✓ |
| Related test recall@5 | **0.80** | ≥ 0.80 ✓ |
| Symbol-to-modify recall@8 | **0.80** | ≥ 0.70 ✓ |
| Validation command recall | **0.80** | — |
| Median workflow latency | **189 ms** | ≤ 700 ms ✓ |

### Quality scoreboard (this repo, 21-task retrieval dataset)

| Metric | BM25-only | Hybrid (real embeddings) | Phase 2.5 target |
|---|---:|---:|---:|
| File recall@8 | 0.78 | **0.87** | ≥ 0.90 |
| Symbol recall@12 | 0.60 | **0.70** | ≥ 0.70 ✓ |
| Irrelevant ratio | 0.48 | **0.43** | ≤ 0.35 |
| Median latency | 21 ms | 43 ms | ≤ 300 ms ✓ |
| Hybrid > BM25 on every metric | ✓ | | |

On the original 6-task focused dataset: **F@8 = 0.94, S@12 = 0.72, irrelevant = 0.25, latency = 44 ms** — every Phase 2.5 target met. Hybrid wins everywhere.

The index lives in `./.codegraphkb/` next to your repo. Delete that folder to start fresh; add it to `.gitignore` (a default rule already does).

---

## Core ideas

| Piece | What it does | Where it lives |
|---|---|---|
| Scanner | gitignore-aware repo walk, secret-file skip, content hashing | `core/scanner.py` |
| Parsers | Python via stdlib `ast`; JS/TS via regex (good-enough MVP) | `core/parsers/` |
| Graph store | SQLite tables for files / symbols / edges / inverted index | `core/store.py` |
| Capsules | Compact markdown summary card per symbol | `core/capsules.py` |
| Search | BM25 over capsules + identifiers (no external deps) | `core/search.py` |
| Retrieval | Intent classifier → seed → graph expansion → rank → token budget | `core/retrieval.py` |
| LLM gateway | Anthropic SDK if available; offline pack-only mode otherwise | `core/llm.py` |

The Token Budget Governor allocates roughly:
- 10 % repo map
- 45 % capsules
- 35 % exact source snippets (only for editing-style intents)
- the rest absorbs overhead

---

## Library API

```python
from codegraphkb import CodeGraphKB

kb = CodeGraphKB("./my-repo")
kb.index()                                          # one-time / incremental

result = kb.ask("Explain the checkout flow", token_budget=6000)
print(result.answer)
print(result.context.graph_paths)
print(result.estimated_tokens)

pack = kb.retrieve_context("Add OAuth login")       # context only, no LLM call
print(pack.to_prompt())

print(kb.impact("backend/services/payments.py").to_prompt())
```

---

## CLI

```text
codegraph init [repo]              create .codegraphkb/
codegraph index [repo]             scan + parse + graph
codegraph stats [repo]             counts and last-indexed timestamp
codegraph find <name>              locate symbols by name / qualified name
codegraph ask "<question>"         retrieve + answer (with --context-only flag)
codegraph impact <target>          callers, routes, tests touched
codegraph explain <target>         architecture-style explanation
codegraph serve mcp                stdio MCP server for Claude / Cursor
codegraph serve api                FastAPI server on 127.0.0.1:8765
```

Useful flags on `ask`:

- `--budget 4000` — cap context tokens
- `--intent feature_implementation` — force a retrieval mode
- `--pin path/to/file.py` — bias seeds toward a file
- `--context-only` — emit the assembled pack, skip the LLM
- `--json` — machine-readable output

---

## MCP integration

Add the server to your Claude Desktop / Cursor / Windsurf MCP config:

```json
{
  "mcpServers": {
    "codegraphkb": {
      "command": "codegraph",
      "args": ["serve", "mcp", "--repo", "/absolute/path/to/your/repo"]
    }
  }
}
```

Tools surfaced to the assistant:

- `search_code_graph(query, limit?)`
- `get_symbol_context(qualified_name, include_source?)`
- `get_minimal_context_for_task(task, token_budget?, intent?, pinned_files?)`
- `get_impact_analysis(target)`
- `get_file_summary(path)`

---

## HTTP API (optional)

```bash
codegraph serve api --port 8765
```

Endpoints: `GET /health`, `GET /stats`, `POST /index`, `POST /ask`, `GET /impact?target=…`.

`POST /ask` body:

```json
{ "question": "...", "token_budget": 6000, "intent": "feature_implementation",
  "pinned_files": [], "context_only": false }
```

## Product API (multi-project preview)

```bash
python -m codegraphkb.server.run_product_api
curl http://localhost:8765/health
```

The product API stores app metadata in `.codegraphkb_app/app.sqlite`, imports
projects into `.codegraphkb_app/workspaces`, and exposes project-scoped
endpoints such as:

```text
POST /projects/github
POST /projects/upload
GET  /projects
GET  /projects/{project_id}/jobs/latest
POST /projects/{project_id}/ask
POST /projects/{project_id}/prepare-edit
GET  /projects/{project_id}/impact
GET  /projects/{project_id}/stats
```

Docker quickstart:

```bash
docker compose up --build
curl http://localhost:8765/health
```

See [docs/PRODUCT_QUICKSTART.md](docs/PRODUCT_QUICKSTART.md) for curl examples,
security guardrails, and current limitations.

---

## Languages

First-class today:
- Python (stdlib `ast`): functions, classes, methods, imports, calls, decorators (FastAPI/Flask routes), pytest test linking.
- JavaScript / TypeScript (regex extractor): imports, named/arrow functions, classes + `extends`, React component shapes, Express/Fastify routes.

Adding a language is one new file under `core/parsers/` returning `ExtractResult`.

---

## What's intentionally **not** here yet

To keep `pip install`-able with zero required infra:

- Neo4j / Postgres / Redis / Qdrant — replaced by SQLite + an in-process BM25 inverted index, plus a SQLite-backed embeddings table with brute-force cosine search. The schema is isomorphic to the production design, so swapping later is mechanical.
- LSP / CodeQL — Tree-sitter is supported via `[parser]` extra (gracefully falls back to `ast`+regex when not installed).
- Hosted/SaaS product UI. The local graph UI exists, and the multi-project
  product API is available as a local-first preview.

## Phase 3 edit-context modules

| Piece | What it does | Where it lives |
|---|---|---|
| `prepare-edit` | Compiles a complete edit-context pack: files-to-edit, files-to-read, related tests, symbols-to-modify, callers/callees, risks, validation commands | [workflow.py](src/codegraphkb/workflow.py) |
| Framework-aware extractors | Detects FastAPI / Flask / Django / Pytest / SQLAlchemy / Pydantic + Express / Next.js / React hooks / Jest / Vitest / Prisma; emits Routes, Components, Models, EnvVars, TestBlocks; new edges `ROUTE_HANDLED_BY`, `TESTS_SYMBOL`, `COMPONENT_USES_HOOK`, `MODEL_USED_BY`, `READS_ENV_VAR` | [core/extractors/](src/codegraphkb/core/extractors/) |
| Validation command planner | Inspects `package.json` / `pyproject.toml` / `pytest.ini` / `Makefile` / `go.mod` / `Cargo.toml` and proposes targeted_test, full_test, typecheck, lint, build commands | `workflow.plan_validation_commands` |
| Patch impact preview | Routes / callers / tests / env-var reads affected by editing a target, plus a `low/medium/high` risk level | `workflow.preview_patch_impact` |
| Related test discovery | Finds tests that import / call / mention a target via direct edges + filename-similarity heuristics | `workflow.get_related_tests` |
| Edit-workflow eval harness | `codegraph eval-edit`: oracle-driven metrics for `prepare-edit` (edit_file_recall@5, related_test_recall@5, symbol_recall@8, validation_command_recall, risk_keyword_recall, latency) | [eval_edit.py](src/codegraphkb/eval_edit.py) |
| Eval failure report | `--explain`, `--save-report`, `suggested_tuning_actions` per task | [eval.py](src/codegraphkb/eval.py) |
| Module-level constant extraction | Python parser now surfaces `UPPER_CASE` constants like `SECRET_FILES` as `constant` symbols | [core/parsers/python_parser.py](src/codegraphkb/core/parsers/python_parser.py) |

## Phase 2.5 retrieval-quality modules

| Piece | What it does | Where it lives |
|---|---|---|
| Eval failure report | `--explain` shows missed-symbol ranks, score breakdowns, and noisy items in each pack | `eval.py` (`MissedSymbol`, `NoiseItem`, `EvalReport.explain_text`) |
| Compare gate | `--compare bm25,hybrid` runs the dataset under multiple retrieval strategies side-by-side | `cli.py` (`eval_cmd`) |
| Symbol alias / concept expansion | augments the BM25 doc with kind concepts, identifier-stem synonyms, neighbor names, route paths | `core/aliases.py` |
| Noise control | per-mode caps: `max_capsules`, `max_per_file`, `max_pure_graph_hits`, `drop_test_files` | `core/noise.py` |
| Reranker Lite | new score channels: `identifier_overlap`, `mode_fit`, `test_proximity`, `generic_penalty` (subtracted) | `core/retrieval.py` |
| Expanded golden dataset | 21 tasks across explain / edit / debug / refactor / impact / test / security / api / onboarding modes; supports `should_exclude_files` / `should_exclude_symbols` | `evals/datasets/self_repo_tasks.yaml` |
| Hybrid quality gate | DoD check via `--compare bm25,hybrid` — hybrid must beat BM25 on every metric | `cli.py` (`_print_compare_table`) |

## Phase 2 modules

| Piece | What it does | Where it lives |
|---|---|---|
| Eval harness | YAML golden tasks; F@k / S@k / irrelevant ratio / utilization / latency | `eval.py` + `evals/datasets/` |
| Parser registry | `auto` / `tree-sitter` / `regex` selection per language | `core/parsers/registry.py` |
| Tree-sitter JS/TS | classes, methods, arrow functions, JSX components, routes, test blocks | `core/parsers/treesitter_js_parser.py` |
| Versioning + doctor | parser/schema/capsule versions, stale-file detection | `versioning.py`, `codegraph doctor` |
| Embeddings | fastembed / sentence-transformers / hash-stub fallback; SQLite-cached by content hash | `core/embeddings.py` |
| Hybrid retrieval | RRF over BM25 / vector / identifier / path / pinned seeds | `core/retrieval.py` |
| Modes | `explain`, `edit`, `debug`, `refactor`, `test`, `impact`, `security`, `onboarding`, `feature` | `Mode` in `core/retrieval.py` |
| Audit metadata | every item carries retrieval sources, score breakdown, graph path, reason | `ContextItem` in `core/retrieval.py` |
| MCP edit tools | `prepare_edit_context`, `get_related_tests`, `get_callers_and_callees`, `resolve_symbol`, `explain_context_selection` | `server/mcp_server.py` |

---

## Project layout

```
src/codegraphkb/
├── api.py                # CodeGraphKB class (library entrypoint)
├── cli.py                # `codegraph` command
├── config.py
├── reporting.py          # GRAPH_REPORT.md generator
├── core/
│   ├── scanner.py
│   ├── ignore.py
│   ├── tokens.py
│   ├── indexer.py        # scan → parse → persist pipeline
│   ├── store.py          # SQLite-backed graph
│   ├── capsules.py
│   ├── search.py         # BM25
│   ├── retrieval.py      # intent + graph expansion + token budget
│   ├── llm.py            # Anthropic + offline mode
│   └── parsers/
│       ├── base.py
│       ├── python_parser.py
│       └── js_parser.py
└── server/
    ├── mcp_server.py     # stdio MCP (no extra deps)
    └── api_server.py     # FastAPI (lazy import)
```

---

## License

MIT.
