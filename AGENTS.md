# CodeGraphKB Agent Instructions

## Project Goal

CodeGraphKB converts a codebase into a graph-powered knowledge base and serves task-specific context packs to LLM coding agents.

## Current Phase

Phase UI-3: Sigma.js + Graphology interactive graph canvas.

## Commands

```bash
pip install -e ".[dev,api]"
codegraph index . --force
codegraph serve ui
```

Frontend:

```bash
cd ui
npm install
npm run build
```

## Constraints

- Do not migrate to Neo4j.
- Do not add SaaS/auth/GitHub OAuth.
- Do not break existing CLI commands.
- Keep UI local-first.
- Use backend APIs from Phase UI-1.
- Preserve UI shell behavior from UI-2 while replacing placeholder with real canvas.
- Preserve static graph export.

## Testing

Run relevant tests when possible:

```bash
pytest tests/test_ui_api.py tests/test_exporters.py
```

If pytest is blocked by environment permissions, run targeted API smoke tests and document the blocker in `docs/agent_handoff.md`.

## Handoff Requirement

Before stopping, update `docs/agent_handoff.md` with:
- files changed
- commands run
- tests run
- blockers
- next step
