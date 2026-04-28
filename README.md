# CodeGraphKB

Convert a codebase into a graph-powered knowledge base, then serve **only the smallest useful context** to your LLM.

Instead of pasting whole repos into Claude / Cursor / GPT, CodeGraphKB:

1. Indexes the repo once into a structural graph (files → functions → calls → routes → tests).
2. Generates compact **Context Capsules** for every symbol.
3. On a question, picks seed nodes, expands the graph by *intent*, ranks, and assembles a **token-budgeted Context Pack**.
4. Sends only that pack to the LLM — or returns it as plain text in offline mode.

The engine ships as a **library**, a **CLI**, an **MCP server**, and an optional **HTTP API**. Same core, four front doors.

---

## Quick start

```bash
pip install -e .             # MVP needs no infra (SQLite-only)
codegraph index .            # one-time scan; re-runs are incremental
codegraph ask "How does the upload flow work?"
codegraph impact src/payments/stripe.ts
codegraph stats
```

Optional extras:

```bash
pip install -e ".[llm]"      # Claude-backed answers (set ANTHROPIC_API_KEY)
pip install -e ".[api]"      # FastAPI HTTP server
pip install -e ".[all]"
```

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

---

## Languages

First-class today:
- Python (stdlib `ast`): functions, classes, methods, imports, calls, decorators (FastAPI/Flask routes), pytest test linking.
- JavaScript / TypeScript (regex extractor): imports, named/arrow functions, classes + `extends`, React component shapes, Express/Fastify routes.

Adding a language is one new file under `core/parsers/` returning `ExtractResult`.

---

## What's intentionally **not** here yet

To keep the MVP `pip install`-able with zero infra, this build leaves out:

- Neo4j / Postgres / Redis / Qdrant — replaced by SQLite + a built-in BM25 inverted index. The schema is isomorphic, so swapping later is mechanical.
- Tree-sitter / LSP / CodeQL — replaced by `ast` + regex. Confidence values on edges already mark inferred relationships.
- Embeddings — BM25 + identifier-aware tokenization handles the MVP retrieval load.
- Web UI — designed in `codegraphkb_architecture.md`, not built yet.

These are the natural follow-ups in roughly that order.

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
