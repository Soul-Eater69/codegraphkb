## Handoff - 2026-04-30 00:05 America/Chicago

### Agent
Codex

### Task
Implemented Phase UI-2 frontend shell scaffolding (`ui/`), wired UI-1 backend APIs into React client components, and updated backend UI serving behavior to serve `ui/dist` when present.

### Files Changed
- `AGENTS.md`
- `docs/agent_handoff.md`
- `src/codegraphkb/server/ui_server.py`
- `src/codegraphkb/api.py`
- `src/codegraphkb/cli.py`
- `ui/package.json`
- `ui/tsconfig.json`
- `ui/vite.config.ts`
- `ui/index.html`
- `ui/src/main.tsx`
- `ui/src/App.tsx`
- `ui/src/styles.css`
- `ui/src/api/client.ts`
- `ui/src/types/graph.ts`
- `ui/src/components/TopBar.tsx`
- `ui/src/components/Sidebar.tsx`
- `ui/src/components/GraphCanvasPlaceholder.tsx`
- `ui/src/components/DetailsPanel.tsx`
- `ui/src/components/FiltersPanel.tsx`
- `ui/src/components/ProcessPanel.tsx`
- `ui/src/components/ImpactPanel.tsx`
- `ui/src/components/AskPanel.tsx`

### Commands Run
```bash
py -3 -m codegraphkb serve --help
python/fastapi TestClient smoke calls for:
  /api/summary
  /api/graph
  /api/search
  /api/node/{id}
  /api/neighborhood
  /api/processes
  /api/impact
  /api/context
```

### Tests Run
```bash
AST parse check for edited Python files
API smoke tests via FastAPI TestClient
```

### What Passed
- `codegraph serve` now advertises `ui` mode.
- `/api/*` UI routes respond with expected payload shapes in smoke tests.
- UI server now serves `ui/dist` when built, otherwise fallback page.
- Frontend shell structure and API client are implemented per UI-2 scope.

### What Failed / Blocked
- Environment has recurring filesystem permission issues with temp/cache directories and some generated folders, which blocked reliable `pytest` runs.
- `npm install` / `npm run build` has not been executed yet in this handoff entry.

### Next Recommended Step
```text
Run:
1) cd ui && npm install && npm run build
2) codegraph serve ui
3) open http://localhost:8765 and complete the UI-2 manual verification checklist.

If npm/network is blocked in this environment, rerun with elevated network permissions and document outcome.
```

## Handoff - 2026-04-30 00:35 America/Chicago

### Agent
Codex

### Task
Completed UI-2 shell implementation and validated frontend build + UI serving from `ui/dist`.

### Files Changed
- `src/codegraphkb/server/ui_server.py`
- `ui/package.json`
- `ui/tsconfig.json`
- `ui/vite.config.ts`
- `ui/index.html`
- `ui/src/main.tsx`
- `ui/src/App.tsx`
- `ui/src/styles.css`
- `ui/src/api/client.ts`
- `ui/src/types/graph.ts`
- `ui/src/components/TopBar.tsx`
- `ui/src/components/Sidebar.tsx`
- `ui/src/components/GraphCanvasPlaceholder.tsx`
- `ui/src/components/DetailsPanel.tsx`
- `ui/src/components/FiltersPanel.tsx`
- `ui/src/components/ProcessPanel.tsx`
- `ui/src/components/ImpactPanel.tsx`
- `ui/src/components/AskPanel.tsx`

### Commands Run
```bash
cd ui
npm install
npm run build
npm run build
```

### Tests Run
```bash
Python AST parse:
  src/codegraphkb/server/ui_server.py
  src/codegraphkb/cli.py
  src/codegraphkb/api.py

FastAPI TestClient smoke:
  GET /
  GET /api/summary
  GET /api/graph
  GET /api/search
  GET /api/node/{id}
  GET /api/neighborhood
  GET /api/processes
  GET /api/impact
  POST /api/context
```

### What Passed
- `npm install` succeeded.
- `npm run build` succeeded and produced `ui/dist`.
- `build_ui_app` serves built `ui/dist/index.html` at `/`.
- UI-1 endpoints remained reachable in smoke tests.

### What Failed / Blocked
- Initial `npm install` needed network escalation.
- Initial build attempt failed under sandbox (`spawn EPERM`) and required elevated execution.

### Next Recommended Step
```text
Run `codegraph serve ui` and execute the UI-2 manual browser checklist.
Then proceed to phase4/ui-sigma-graph once shell behavior is accepted.
```

## Handoff - 2026-04-30 01:10 America/Chicago

### Phase
phase4/ui-sigma-graph

### Agent
Codex

### Task
Replaced placeholder-centric center panel with a real Sigma.js + Graphology graph canvas, including layout control, node/edge selection behavior, reducer-based filtering/highlighting, and neighborhood fallback from search/process selection.

### Files Changed
- `AGENTS.md`
- `docs/agent_handoff.md`
- `ui/package.json`
- `ui/package-lock.json`
- `ui/src/App.tsx`
- `ui/src/styles.css`
- `ui/src/components/GraphCanvas.tsx`
- `ui/src/graph/adapter.ts`
- `ui/src/graph/styles.ts`
- `ui/src/graph/layout.ts`
- `ui/src/graph/filters.ts`
- `ui/src/hooks/useSigma.ts`

### Commands Run
```bash
cd ui
npm install sigma graphology graphology-layout-forceatlas2 graphology-layout-noverlap graphology-layout-force graphology-utils @sigma/edge-curve
npm run build
npm run build
```

### Tests Run
```bash
Frontend:
  cd ui
  npm run build
```

### What Passed
- Sigma/Graphology dependencies installed.
- TypeScript build passed.
- Vite production build passed.
- App now uses `GraphCanvas` instead of `GraphCanvasPlaceholder`.
- Search selection now supports neighborhood fallback if selected node is not in current slice.
- Node and edge selection paths update Details panel data.
- Canvas reducers apply node kind / edge type filter visibility and selection-based dim/highlight.

### What Failed / Blocked
- Initial dependency install needed network escalation due cache-only sandbox mode.
- No full browser manual checklist was executed in this handoff entry.

### Next Recommended Step
```text
Run:
1) codegraph index . --force
2) codegraph serve ui
3) Manual UI-3 browser checklist:
   - verify repo/symbols/calls/framework/processes render
   - verify node click and edge click details
   - verify search focus + neighborhood fallback
   - verify filters affect rendered graph
   - verify layout controls and large-graph warning behavior
```

## Handoff - 2026-04-30 14:20 America/Chicago

### Phase
phase4/ui-production-graph-explorer

### Agent
Codex

### Task
Executed a production UX pass over the local graph UI: canvas-first layout, enterprise dark theme refresh, collapsible side panels, legend overlay, inspector tab system, worker-based ForceAtlas2 layout, curved edge program wiring, grouped search workflow, and backend helper endpoints for file tree + node relations.

### Files Changed
- `src/codegraphkb/server/ui_server.py`
- `ui/src/App.tsx`
- `ui/src/styles.css`
- `ui/src/api/client.ts`
- `ui/src/types/graph.ts`
- `ui/src/components/TopBar.tsx`
- `ui/src/components/Sidebar.tsx`
- `ui/src/components/GraphCanvas.tsx`
- `ui/src/components/DetailsPanel.tsx`
- `ui/src/components/FiltersPanel.tsx`
- `ui/src/components/ProcessPanel.tsx`
- `ui/src/components/ImpactPanel.tsx`
- `ui/src/components/AskPanel.tsx`
- `ui/src/hooks/useSigma.ts`
- `ui/src/graph/adapter.ts`
- `ui/src/graph/layout.ts`
- `ui/src/graph/styles.ts`
- `docs/agent_handoff.md`

### Commands Run
```bash
Get-Content / rg scans across ui/src and src/codegraphkb/server
py -3 -m py_compile src/codegraphkb/server/ui_server.py
py -3 -c "import ast, pathlib; ast.parse(pathlib.Path('src/codegraphkb/server/ui_server.py').read_text(encoding='utf-8')); print('ok')"
cd ui
npm run build
py -3 -c "from fastapi.testclient import TestClient; from codegraphkb.server.ui_server import build_ui_app; app=build_ui_app('.'); c=TestClient(app); print(c.get('/api/summary').status_code, c.get('/api/files/tree').status_code); print(c.get('/api/processes').status_code);"
```

### Tests Run
```bash
Frontend build:
  cd ui
  npm run build

Backend syntax:
  ast.parse of src/codegraphkb/server/ui_server.py

API smoke:
  GET /api/summary
  GET /api/files/tree
  GET /api/processes
```

### What Passed
- `npm run build` passed after redesign and Sigma worker/edge updates.
- UI now uses a canvas-dominant layout with floating graph controls and legend overlay.
- Left and right panels are collapsible.
- Inspector panel now has practical tabs (`Details`, `Relations`, `Processes`, `Impact`, `Context`, `Raw`).
- Graph controls and interaction behaviors are preserved and polished.
- Process selection now supports `node_id` from backend payloads.
- New backend endpoints respond:
  - `GET /api/files/tree`
  - `GET /api/node/{node_id}/relations`
- `/api/summary` now includes `node_kinds` and `edge_types` counts.

### What Failed / Blocked
- `py_compile` failed due local filesystem permission on `__pycache__` write (`WinError 5`), so syntax verification used `ast.parse` fallback.
- The FastAPI smoke command returned expected status codes but the shell timed out after printing results; no endpoint failures were observed in output.

### Next Recommended Step
```text
Manual browser QA for production UX:
1) codegraph index . --force
2) codegraph serve ui
3) Verify:
   - canvas-first experience and panel collapse behavior
   - grouped search -> node focus / neighborhood fallback
   - node & edge click details in inspector tabs
   - process selection / impact slice workflows
   - large graph action overlay pivot buttons

Optional follow-up:
- Add GET /api/files/tree and /api/node/{id}/relations API tests.
- Add scene export button wiring (currently UI control layer is ready for it).
```

## Handoff - 2026-04-30 16:05 America/Chicago

### Phase
phase4/ui-reset-clean-shell + phase4/ui-controlled-graph-scene (query-first rebuild)

### Agent
Codex

### Task
Rebuilt the frontend UX around a query-first enterprise graph explorer model. Replaced the dashboard-centric flow with a stable empty workspace, perspective/query-driven loading, deterministic per-view layouts, manual-only force layout, collapsed legend, and collapsed-by-default inspector.

### Files Changed
- `ui/src/App.tsx`
- `ui/src/styles.css`
- `ui/src/types/graph.ts`
- `ui/src/design/tokens.css`
- `ui/src/design/theme.ts`
- `ui/src/features/search/commandParser.ts`
- `ui/src/graph/GraphScene.tsx`
- `ui/src/graph/SigmaCanvas.tsx`
- `ui/src/graph/graphAdapter.ts`
- `ui/src/graph/graphStyles.ts`
- `ui/src/graph/interactions.ts`
- `ui/src/graph/layouts.ts`
- `ui/src/layout/TopQueryBar.tsx`
- `ui/src/layout/LeftRail.tsx`
- `ui/src/layout/InspectorDrawer.tsx`
- `ui/src/layout/StatusBar.tsx`
- `ui/src/panels/GraphInfoPanel.tsx`
- `ui/src/panels/PerspectivesPanel.tsx`
- `ui/src/panels/FilterPanel.tsx`
- `ui/src/panels/FileTreePanel.tsx`
- `ui/src/panels/ProcessPanel.tsx`
- `ui/src_legacy/*` (archived copy of prior `ui/src`)
- `docs/agent_handoff.md`

### Commands Run
```bash
Copy old UI:
  Copy-Item -Path ui/src/* -Destination ui/src_legacy -Recurse -Force

Build:
  cd ui
  npm run build

Syntax/API smoke:
  py -3 -c "import ast, pathlib; ast.parse(pathlib.Path('src/codegraphkb/server/ui_server.py').read_text(encoding='utf-8')); print('ok')"
  py -3 -c "from fastapi.testclient import TestClient; from codegraphkb.server.ui_server import build_ui_app; app=build_ui_app('.'); c=TestClient(app); print(c.get('/api/summary').status_code, c.get('/api/graph?view=repo').status_code, c.get('/api/files/tree').status_code)"
```

### Tests Run
```bash
Frontend:
  cd ui
  npm run build

Backend sanity:
  ast.parse ui_server.py
  FastAPI TestClient smoke: /api/summary /api/graph?view=repo /api/files/tree
```

### What Passed
- `npm run build` passed for the rebuilt UI.
- Initial screen is stable and does not auto-render/jiggle graph.
- Graph renders only after perspective/query action.
- Deterministic layouts applied by perspective:
  - repo (ringed deterministic map)
  - symbols (file-grouped)
  - processes (ordered step chain)
  - impact (target-centered)
  - neighborhood (seed-centered)
- Force layout is manual-only via control button and auto-stops quickly.
- Inspector starts collapsed and opens on selection.
- Raw JSON is only in the `Raw` tab.
- Legend is collapsed by default.
- Search fallback flow implemented: if node not in current scene, load neighborhood.

### What Failed / Blocked
- `Move-Item ui/src -> ui/src_legacy` failed with filesystem permission denied; used full copy to `ui/src_legacy` instead.
- One TestClient smoke command hit session timeout after printing success codes (`200 200 200`), so output confirms success but command ended with timeout status.

### Next Recommended Step
```text
1) Run manual browser validation:
   - codegraph serve ui
   - confirm query commands:
     repo / symbols / calls / framework / processes / impact <target> / neighborhood <node_id>
2) Polish deterministic repo layout into stricter parent-child tree bands.
3) Add grouped search dropdown in top query bar (currently results list in left rail).
4) Add focused API tests for query command flows and neighborhood fallback.
```

## Handoff - 2026-04-30 16:45 America/Chicago

### Phase
phase4/ui-reset-shell (strict bounded flow adjustments)

### Agent
Codex

### Task
Applied strict interaction constraints to prevent global graph hairballs and enforce target-first investigation flows.

### Files Changed
- `ui/src/App.tsx`
- `ui/src/api/client.ts`
- `ui/src/features/search/commandParser.ts`
- `ui/src/graph/GraphScene.tsx`
- `ui/src/layout/TopQueryBar.tsx`
- `ui/src/panels/PerspectivesPanel.tsx`
- `docs/agent_handoff.md`

### Commands Run
```bash
cd ui
npm run build
```

### Tests Run
```bash
Frontend build:
  npm run build
```

### What Passed
- Build passed after strict gating changes.
- `full` is blocked in UI flows.
- Top bar view selector now only exposes bounded baseline views (`repo`, `processes`).
- Parser no longer treats `full/calls/symbols/framework` as direct global graph loads.
- Calls/symbols/framework now require target-first behavior (search-driven pivot).
- Process perspective defaults to "select one process first" instead of loading global process blob.
- Neighborhood/impact fetches now use explicit bounded params (`depth`, `max_nodes`, `max_edges`).
- Repo view enforces bounded API request + repo-focused filters (`CONTAINS`, repo/folder/file node kinds).
- Empty scene now communicates guided investigation actions rather than dumping graphs.

### What Failed / Blocked
- None in this sub-pass.

### Next Recommended Step
```text
1) Add grouped search result buckets in the left rail (Files/Functions/Classes/Routes/Processes/Tests).
2) Implement explicit "calls target layout" vs generic neighborhood for symbol selections.
3) Add framework target picker panel before framework graph render.
4) Add backend tests for bounded params and target-first guards.
```

## Handoff - 2026-04-30 23:14 America/Chicago

### Phase
phase4/ui-reset-shell / broken UI recovery

### Agent
Codex

### Task
Fixed the query-first graph UI after the desktop layout collapsed and non-repo perspective actions fell back to the empty menu.

### Files Changed
- `ui/src/App.tsx`
- `ui/src/design/tokens.css`
- `ui/src/graph/GraphScene.tsx`
- `ui/src/graph/SigmaCanvas.tsx`
- `ui/src/graph/graphAdapter.ts`
- `ui/src/graph/graphStyles.ts`
- `ui/src/graph/layouts.ts`
- `ui/src/styles.css`
- `docs/agent_handoff.md`

### Commands Run
```bash
cd ui
npm run build
```

Manual browser smoke used `codegraph serve ui --port 8766` and opened `http://127.0.0.1:8766/`.

### Tests Run
```bash
Frontend build:
  npm run build

Browser smoke:
  initial workspace at 1200x900
  Repo Map perspective
  Symbols perspective
```

### What Passed
- Build passed.
- Desktop layout no longer stacks the left rail above the graph at 1200px width.
- Initial screen remains stable and renders no graph until the user chooses a perspective/query.
- Repo Map opens a bounded repo-only scene and collapses stale inspector state.
- Symbols now auto-selects a file with symbols when available instead of returning to the quick-action menu.
- Processes now auto-selects the first loaded process when available; if none exist, it shows a scoped empty state.
- Repo layout is deterministic/frozen and uses a hierarchy-style placement rather than force layout.
- CONTAINS edges are quieter and straight instead of curved by default.
- Inspector still defaults to Summary, with Raw JSON only on the Raw tab.

### What Failed / Blocked
- The local indexed repo used for smoke testing currently has zero process flows, so process auto-selection was validated by code path/build rather than visual process rendering.
- Browser smoke artifacts were generated locally for verification.
- Cleanup of `.playwright-mcp/` and screenshot artifacts was denied by the filesystem sandbox, so they may appear as untracked files.

### Next Recommended Step
```text
1) Validate on a repo/index that has process flows to confirm the first process opens automatically.
2) Add frontend tests for perspective buttons so Symbols/Processes cannot regress to the empty menu.
3) Add a focused backend repo-map endpoint with true folder->folder CONTAINS edges to make the hierarchy even cleaner.
```

## Handoff - 2026-04-30 23:31 America/Chicago

### Phase
phase4/ui-gitnexus-inspired-visual-pass

### Agent
Codex

### Task
Moved the UI closer to the GitNexus-style graph explorer: black canvas-first workspace, compact top search/header, slimmer left explorer, brighter graph palette, and bounded repo graph auto-load.

### Files Changed
- `ui/src/App.tsx`
- `ui/src/design/tokens.css`
- `ui/src/graph/GraphScene.tsx`
- `ui/src/graph/graphStyles.ts`
- `ui/src/layout/InspectorDrawer.tsx`
- `ui/src/layout/TopQueryBar.tsx`
- `ui/src/panels/GraphInfoPanel.tsx`
- `ui/src/panels/ProcessPanel.tsx`
- `ui/src/styles.css`
- `docs/agent_handoff.md`

### Commands Run
```bash
cd ui
npm run build
```

Browser smoke used `http://127.0.0.1:8766/?v=gitnexus1`.

### Tests Run
```bash
Frontend build:
  npm run build

Browser smoke:
  auto-loaded Repo Map
  Symbols perspective
```

### What Passed
- Build passed.
- UI now auto-loads a bounded GitNexus-style Overview instead of landing on a dead quick-action menu.
- Top bar is closer to GitNexus: logo mark, centered search/query input, compact counts, view selector, status, and Nexus AI button.
- Left rail is slimmer and denser; graph canvas dominates the viewport.
- Graph stage uses a near-black background, subtle dot field, floating legend, and bottom-right controls.
- Labels are off by default so the graph reads more like a clean visual scene.
- Node colors are more saturated and GitNexus-like.
- Overview loads a capped mixed graph (`full` view, max 900 nodes / 1800 edges) for a colorful graph galaxy.
- Nodes have a lightweight breathing animation via Sigma reducers and a requestAnimationFrame refresh loop for graphs up to 1200 nodes.
- Inspector mojibake was cleaned up.

### What Failed / Blocked
- ForceAtlas2 worker animation is not wired yet; current layout is deterministic/static with breathing node motion.
- Screenshot/snapshot artifacts from Playwright still could not be removed due filesystem permission denial.

### Next Recommended Step
```text
1) Add ForceAtlas2 worker layout for Overview only, with a visible "Layout optimizing..." pill and stop control.
2) Add animated search/blast-radius highlights similar to GitNexus AI citation highlights.
3) Replace text graph-control buttons with icon buttons once lucide-react is installed.
```

## Handoff - 2026-05-01 00:04 America/Chicago

### Phase
phase4/ui-gitnexus-behavior-pass

### Agent
Codex

### Task
Finished the GitNexus-inspired graph interaction pass after the user reported the UI still felt broken and non-repo perspectives fell back to the menu.

### Files Changed
- `ui/src/App.tsx`
- `ui/src/graph/GraphScene.tsx`
- `ui/src/graph/SigmaCanvas.tsx`
- `ui/src/layout/TopQueryBar.tsx`
- `docs/agent_handoff.md`

### Commands Run
```bash
cd ui
npm run build
```

Browser smoke used `http://127.0.0.1:8766/?v=no-width-fix`.

### Tests Run
```bash
Frontend build:
  npm run build

Browser smoke:
  Overview auto-load
  Symbols perspective
  Call Graph perspective
  Processes perspective
  console/page error capture
```

### What Passed
- Build passed.
- Overview now opens as a GitNexus-style bounded mixed graph with worker ForceAtlas2 layout, curved edges, and breathing node animation.
- Perspective selector includes overview/repo/symbols/calls/framework/processes.
- Symbols no longer falls back to the menu; it auto-opens the first file with symbols when available.
- Calls/framework/processes now load bounded graph slices instead of showing the old scoped empty prompt.
- Search results are grouped in a top-bar popover; selecting a result highlights/focuses the node and clears the popover.
- Sigma no-width container errors were fixed with `allowInvalidContainer`.
- Browser smoke reported zero console/page errors after switching Symbols -> Call Graph -> Processes.

### What Failed / Blocked
- The local smoke index has `processes: 0`, so true ordered process-flow visuals still need validation on an index with process maps.
- Playwright screenshot artifacts remain untracked because sandbox cleanup was denied earlier.

### Next Recommended Step
```text
1) Validate with examples/ts-process-express or another indexed repo that has process maps.
2) Add a regression test/smoke for perspective buttons so they always render graph slices.
3) Add lucide-react or a tiny icon system for final control polish.
```

## Handoff - 2026-05-01 12:50 America/Chicago

### Phase
phase4/gitnexus-fluidity-click-fix

### Agent
Codex

### Task
Responded to the user report that the graph animation stuttered and node clicks appeared to do nothing.

### Files Changed
- `ui/src/App.tsx`
- `ui/src/graph/GraphScene.tsx`
- `ui/src/graph/SigmaCanvas.tsx`
- `ui/src/layout/InspectorDrawer.tsx`
- `ui/src/styles.css`
- `docs/agent_handoff.md`

### Commands Run
```bash
cd ui
npm run build
```

Browser smoke used:
```text
http://127.0.0.1:8766/?v=stability2
http://127.0.0.1:8766/?v=stability3
http://127.0.0.1:8766/?v=stability4
http://127.0.0.1:8766/?v=stability5
```

### Tests Run
```bash
npm run build
```

Manual browser smoke:
```text
Overview loads with Sigma canvas
Repo Map node click opens inspector
Inspector shows immediate node/file summary
Symbols perspective loads a bounded symbols scene
Processes perspective shows a specific no-processes empty state for this index
Console error capture returned zero errors on the stability2 smoke
```

### What Passed
- Build passed after every patch.
- Node click now sets inspector content immediately from the in-scene graph node before `/api/node` finishes.
- Direct node click no longer camera-jumps into a blank-looking canvas.
- Hover card is cleared on node click so it does not cover the selected node.
- Selection dimming was relaxed so the graph remains visible after selection.
- ForceAtlas2 worker tuning was slowed down and the extra forced refresh loop during layout was removed to reduce stutter.
- Edges remain visible during movement for a more continuous GitNexus-like scene.
- The graph background has a denser multi-layer star field.
- Empty states are perspective-specific instead of looking like the same generic menu.

### What Failed / Blocked
- The current local index has `processes: 0`, so process-flow animation still needs validation against an index that actually contains process maps.
- Playwright screenshots and `.playwright-mcp/` remain untracked; prior cleanup attempts were denied by filesystem permissions.

### Next Recommended Step
```text
1) Smoke with examples/ts-process-express or another process-map index.
2) Add a real Playwright regression for node click -> inspector summary.
3) Add a deterministic screenshot/snapshot check for Overview so visual regressions are caught quickly.
```

## Handoff - 2026-05-01 21:01 America/Chicago

### Phase
phase4/neo4j-graph-verification

### Agent
Codex

### Task
Added a local Neo4j verification path after the user reported route/framework/call/symbol graph scenes looked wrong and asked to verify raw graph data outside the UI.

### Files Changed
- `docker-compose.neo4j.yml`
- `docs/neo4j_verification.md`
- `pyproject.toml`
- `src/codegraphkb/api.py`
- `src/codegraphkb/cli.py`
- `src/codegraphkb/core/exporters/__init__.py`
- `src/codegraphkb/core/exporters/graph_exporter.py`
- `src/codegraphkb/core/exporters/neo4j_exporter.py`
- `tests/test_neo4j_exporter.py`
- `ui/src/graph/graphStyles.ts`

### Commands Run
```bash
docker compose -f docker-compose.neo4j.yml config
docker compose -f docker-compose.neo4j.yml up -d
py -3 -m codegraphkb export neo4j --repo . --view full --clear --json
py -3 -m codegraphkb export neo4j --help
py -3 -c "<neo4j count queries>"
cd ui && npm run build
```

### Tests Run
```bash
py -3 -m pytest tests\test_neo4j_exporter.py tests\test_exporters.py --basetemp=.pytest_tmp_neo4j_run
```

### What Passed
- Targeted pytest suite passed: 7 passed.
- Frontend build passed after adding `ROUTES_TO` edge color.
- Docker Compose Neo4j config is valid.
- Local Neo4j container started on ports 7474 and 7687.
- Full graph export pushed successfully to Neo4j:
  - 663 nodes
  - 1015 relationships
  - 0 skipped edges
- Neo4j counts matched the exporter counts.
- Framework exporter now includes `ROUTES_TO`; this repo's framework view includes:
  - `TESTS`: 25
  - `TESTS_SYMBOL`: 25
  - `ROUTES_TO`: 6
  - `ROUTE_HANDLED_BY`: 2

### What Failed / Blocked
- The raw graph reveals duplicate route concepts: syntax route nodes such as `route::GET /health` and framework route nodes such as `fastapi::GET /health`. They are connected, but split across duplicate route nodes. This is a graph modeling/export normalization issue, not just a UI layout issue.
- Existing permission-denied temp directories still make plain `git status` noisy in this workspace.

### Next Recommended Step
```text
1) Add route canonicalization so `route::GET /x` and `fastapi::GET /x` collapse into one route node in exported/UI graphs.
2) Rebuild framework view around route -> handler -> calls/query/external columns after canonicalization.
3) Revisit UI layouts only after Neo4j confirms route/call/symbol relationships are semantically correct.
```

## Handoff - 2026-05-01 22:35 America/Chicago

### Phase
schema-v4-object-roles

### Agent
Codex

### Task
Implemented the object-role graph layer so CodeGraphKB can infer auditable roles such as handler, service, repository, client, model, config, fixture, and test above raw syntax node kinds.

### Files Changed
- `src/codegraphkb/core/roles.py`
- `src/codegraphkb/core/store.py`
- `src/codegraphkb/core/migrations.py`
- `src/codegraphkb/core/indexer.py`
- `src/codegraphkb/core/graph_schema.py`
- `src/codegraphkb/versioning.py`
- `src/codegraphkb/api.py`
- `src/codegraphkb/cli.py`
- `src/codegraphkb/diagnostics.py`
- `src/codegraphkb/server/ui_server.py`
- `src/codegraphkb/core/exporters/graph_exporter.py`
- `src/codegraphkb/core/exporters/impact_exporter.py`
- `src/codegraphkb/core/exporters/neo4j_exporter.py`
- `tests/test_object_roles.py`
- `docs/agent_handoff.md`

### Commands Run
```bash
py -3 -m pytest tests\test_object_roles.py -q -x --tb=short --basetemp=.pytest_tmp_roles_run2
py -3 -m pytest tests\test_object_roles.py tests\test_neo4j_exporter.py tests\test_exporters.py -q --tb=short --basetemp=.pytest_tmp_roles_run3
py -3 -m pytest tests\test_ui_api.py -q --tb=short --basetemp=.pytest_tmp_ui_roles
git status --short
```

### Tests Run
```bash
tests/test_object_roles.py
tests/test_neo4j_exporter.py
tests/test_exporters.py
tests/test_ui_api.py
```

### What Passed
- Role tests passed: 3 passed.
- Role + exporter regression passed: 10 passed.
- UI API regression passed: 7 passed.
- Indexing now writes `object_roles` rows after semantic/process passes.
- `codegraph stats` / doctor / `/api/summary` expose role counts.
- `/api/node/{id}` exposes node roles with confidence, reason, and signals.
- JSON, impact, and Neo4j exports include primary role and role metadata.
- Neo4j export now also adds role labels such as `CodeGraphRoleService`.

### What Failed / Blocked
- First pytest run inside the sandbox hit a Windows temp-directory permission cleanup error; rerunning pytest with approved elevated execution passed.

### Next Recommended Step
```text
1) Re-index this repo and push to Neo4j again so Browser shows CodeGraphRole* labels and role properties.
2) Add route canonicalization so duplicate `route::...` / `fastapi::...` route nodes collapse before UI/export.
3) Use roles in the UI layouts: handlers/routes/processes/services/repositories should drive framework and impact scenes.
```

## Handoff - 2026-05-03 00:20 America/Chicago

### Phase
phase5a-typed-symbol-model

### Agent
Codex

### Task
Implemented structured symbol parameters as first-class typed facts. This keeps parameters table-first rather than turning every parameter into a visible graph node.

### Files Changed
- `.gitignore`
- `helpers/ts-semantic/src/protocol.ts`
- `helpers/ts-semantic/src/symbols.ts`
- `src/codegraphkb/core/parsers/base.py`
- `src/codegraphkb/core/parsers/python_parser.py`
- `src/codegraphkb/core/parsers/js_parser.py`
- `src/codegraphkb/core/parsers/treesitter_js_parser.py`
- `src/codegraphkb/core/semantic/protocol.py`
- `src/codegraphkb/core/semantic/typescript_adapter.py`
- `src/codegraphkb/core/semantic/merge.py`
- `src/codegraphkb/core/semantic/__init__.py`
- `src/codegraphkb/core/semantic/base.py`
- `src/codegraphkb/core/store.py`
- `src/codegraphkb/core/migrations.py`
- `src/codegraphkb/core/indexer.py`
- `src/codegraphkb/core/graph_schema.py`
- `src/codegraphkb/versioning.py`
- `src/codegraphkb/api.py`
- `src/codegraphkb/cli.py`
- `src/codegraphkb/diagnostics.py`
- `src/codegraphkb/server/ui_server.py`
- `src/codegraphkb/core/exporters/graph_exporter.py`
- `src/codegraphkb/core/exporters/impact_exporter.py`
- `src/codegraphkb/core/exporters/neo4j_exporter.py`
- `tests/test_parameters.py`
- `docs/agent_handoff.md`

### Commands Run
```bash
cmd /c npm --prefix helpers\ts-semantic run build
py -3 -m pytest tests\test_parameters.py -q --tb=short --basetemp=.pytest_tmp_params
py -3 -m pytest tests\test_parameters.py tests\test_typescript_semantic.py tests\test_object_roles.py tests\test_exporters.py tests\test_neo4j_exporter.py tests\test_ui_api.py -q --tb=short --basetemp=.pytest_tmp_phase5a
git rm --cached -r --ignore-unmatch .pytest_tmp_roles_final
git status --short
```

### Tests Run
```bash
tests/test_parameters.py
tests/test_typescript_semantic.py
tests/test_object_roles.py
tests/test_exporters.py
tests/test_neo4j_exporter.py
tests/test_ui_api.py
```

### What Passed
- New parameter tests passed: 4 passed.
- Targeted regression suite passed: 31 passed.
- TypeScript semantic helper rebuilt successfully.
- `parameters` table and indexes are created through base schema/migration.
- Python AST extracts annotations, defaults, `*args`, keyword-only args, `**kwargs`, and return annotations.
- TS/JS syntax parser extracts function/arrow parameters and return types in regex/tree-sitter paths.
- TypeScript Compiler API helper emits structured `parameters` on semantic symbols.
- Semantic merge replaces syntax parameters with language-semantic precision when available.
- `/api/node/{id}`, graph export, impact export, stats, doctor, and Neo4j export expose parameter facts.

### What Failed / Blocked
- Initial `git rm --cached` hit a sandbox index-lock permission error; rerunning with approved escalation removed `.pytest_tmp_roles_final/` from the Git index.

### Next Recommended Step
```text
1) Re-index the repo and verify `codegraph stats --json` shows parameter counts.
2) Push to Neo4j again; nodes now carry `parameters_json`.
3) Start Phase 5B: callsites + call_arguments, using this parameter table for argument-to-parameter mapping.
```

## Handoff - 2026-05-03 14:05 America/Chicago

### Phase
phase5a-verification-hardening

### Agent
Codex

### Task
Verified Phase 5A against the real repo index before moving to 5B. Fixed two verification findings: human `codegraph stats` did not show parameter counts, and legacy semantic-only parameter rows could remain orphaned from earlier indexes.

### Files Changed
- `src/codegraphkb/cli.py`
- `src/codegraphkb/core/semantic/merge.py`
- `src/codegraphkb/core/store.py`
- `src/codegraphkb/core/indexer.py`
- `pyproject.toml`
- `tests/test_parameters.py`
- `docs/agent_handoff.md`

### Commands Run
```bash
py -3 -m pytest tests\test_parameters.py -q --tb=short --basetemp=.pytest_tmp_verify_params
py -3 -m pytest -q --tb=short --basetemp=.pytest_tmp_verify_all
codegraph doctor --json
codegraph stats
codegraph index . --force --semantic auto
codegraph export graph --format json --view symbols --out graph.json
py -3 -c "import sqlite3; cx=sqlite3.connect('.codegraphkb/graph.sqlite'); print(cx.execute('select count(*) from parameters p left join symbols s on s.qualified_name=p.owner_qname where s.qualified_name is null').fetchone()[0])"
```

### Tests Run
```bash
tests/test_parameters.py
full pytest suite
```

### What Passed
- Parameter suite now covers 8 cases and passed.
- Full pytest suite passed: 93 passed, 2 warnings.
- Fresh repo index completed with schema version 5.
- `codegraph stats` now prints `Parameters`.
- `codegraph doctor --json` reports `parameter_count`.
- `graph.json` export contains parameter arrays on symbol nodes.
- Parameter owner integrity check now returns `0` orphan rows.

### What Failed / Blocked
- Full pytest initially collected generated `.pytest_tmp*` fixture folders. Added pytest config to restrict collection to `tests/` and ignore `.pytest_tmp*`.
- DB integrity check initially found 698 orphan parameter rows from old semantic-only owners. Semantic merge now only persists params for existing symbols, and indexing prunes legacy orphan params.

### Next Recommended Step
```text
Start Phase 5B.1: callsite and call_arguments schema/store/merge/API tests. Do not jump to HTTP contracts yet.
```
