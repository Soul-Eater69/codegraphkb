# CodeGraphKB Agent Instructions

## Project Goal

CodeGraphKB converts a codebase into a graph-powered knowledge base and serves task-specific context packs to LLM coding agents.

## Current Phase

Phase UI-2: React frontend shell for local interactive graph UI.

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
- Do not implement Sigma graph rendering in UI-2.
- Use backend APIs from Phase UI-1.
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
