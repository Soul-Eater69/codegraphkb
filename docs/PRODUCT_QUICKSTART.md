# CodeGraphKB Product Quickstart

This local-first product API lets users create project records from a public
GitHub URL or uploaded ZIP, index each project in its own workspace, and call
project-scoped ask, prepare-edit, impact, stats, files, symbols, and graph
summary endpoints.

## Run Locally

```bash
python -m pip install -e ".[all,dev]"
python -m codegraphkb.server.run_product_api
curl http://localhost:8765/health
```

The API stores metadata in `.codegraphkb_app/app.sqlite` and imported projects
under `.codegraphkb_app/workspaces` by default.

## Run With Docker

```bash
docker compose up --build
curl http://localhost:8765/health
```

## Browser Product UI

Run the API and Vite UI in separate terminals:

```bash
python -m codegraphkb.server.run_product_api
npm --prefix ui run dev
```

Open `http://localhost:5173/projects`.

## Public GitHub Import

```bash
curl -X POST http://localhost:8765/projects/github \
  -H "Content-Type: application/json" \
  -d "{\"url\":\"https://github.com/owner/repo\",\"name\":\"repo\"}"
```

Only public HTTPS GitHub URLs are accepted in v0.1. SSH URLs, non-GitHub
domains, credentials, query strings, and private repo auth are rejected.

## ZIP Upload

```bash
curl -X POST http://localhost:8765/projects/upload \
  -F "name=my-repo" \
  -F "file=@repo.zip"
```

ZIP extraction rejects absolute paths, `..` traversal, symlinks, oversize
archives, oversize files, and ignored folders such as `.git`, `node_modules`,
`dist`, `build`, and `.venv`.

## Project Endpoints

```bash
curl http://localhost:8765/projects
curl http://localhost:8765/projects/<project_id>
curl http://localhost:8765/projects/<project_id>/jobs/latest
curl http://localhost:8765/projects/<project_id>/stats
curl http://localhost:8765/projects/<project_id>/files
curl http://localhost:8765/projects/<project_id>/symbols?kind=function
curl http://localhost:8765/projects/<project_id>/graph/summary
```

Ask and prepare-edit require the project status to be `ready`:

```bash
curl -X POST http://localhost:8765/projects/<project_id>/ask \
  -H "Content-Type: application/json" \
  -d "{\"question\":\"How does authentication work?\",\"context_only\":true}"

curl -X POST http://localhost:8765/projects/<project_id>/prepare-edit \
  -H "Content-Type: application/json" \
  -d "{\"task\":\"Add refresh token rotation\",\"token_budget\":6000}"
```

## Current Limitations

- No SaaS auth or GitHub OAuth.
- No private GitHub clone flow.
- No Redis/Celery; jobs run through local FastAPI background tasks.
- No automatic package installs or test commands from imported repos.
- The graph explorer remains a separate advanced local tool.
