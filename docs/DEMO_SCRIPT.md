# CodeGraphKB v0.1 Demo Script

## 1. Start The Product API

```bash
python -m pip install -e ".[all,dev]"
python -m codegraphkb.server.run_product_api
```

In another terminal:

```bash
curl http://localhost:8765/health
```

Expected:

```json
{"ok":true,"version":"0.1.0"}
```

## 2. Start The Browser UI

```bash
npm --prefix ui install
npm --prefix ui run dev
```

Open:

```text
http://localhost:5173/projects
```

Use New Project to upload a ZIP or import a public GitHub URL. The UI polls
`/projects/{project_id}/jobs/latest` until the project is ready.

## 3. ZIP Upload With Curl

Create a ZIP from a sample repo:

```powershell
Compress-Archive -Path examples/repos/python-fastapi-mini/* -DestinationPath .tmp/python-fastapi-mini.zip -Force
```

Upload it:

```bash
curl -X POST http://localhost:8765/projects/upload \
  -F "name=python-fastapi-mini" \
  -F "file=@.tmp/python-fastapi-mini.zip"
```

Capture the returned `project_id`.

## 4. Watch The Index Job

```bash
curl http://localhost:8765/projects/<project_id>/jobs/latest
curl http://localhost:8765/projects/<project_id>/stats
curl http://localhost:8765/projects/<project_id>/files
curl http://localhost:8765/projects/<project_id>/symbols
curl http://localhost:8765/projects/<project_id>/graph/summary
```

## 5. Ask A Ready Project

```bash
curl -X POST http://localhost:8765/projects/<project_id>/ask \
  -H "Content-Type: application/json" \
  -d "{\"question\":\"How does user lookup work?\",\"context_only\":true}"
```

## 6. Prepare An Edit

```bash
curl -X POST http://localhost:8765/projects/<project_id>/prepare-edit \
  -H "Content-Type: application/json" \
  -d "{\"task\":\"Add validation for missing user ids\",\"token_budget\":6000}"
```

## 7. Docker API Smoke

```bash
docker compose up --build
curl http://localhost:8765/health
```

Docker runs the Product API. Use the local Vite UI command above for the browser
product flow during v0.1 preview.
