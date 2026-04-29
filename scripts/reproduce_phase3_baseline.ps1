param(
    [string]$Dataset = "evals/datasets/self_repo_tasks.yaml"
)

$ErrorActionPreference = "Stop"

Remove-Item -LiteralPath ".codegraphkb" -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force "reports" | Out-Null

codegraph index . --parser auto --embed
codegraph doctor --json | Set-Content -Encoding UTF8 "reports/doctor.json"
codegraph stats --object-types

$doctor = Get-Content "reports/doctor.json" -Raw | ConvertFrom-Json
if ($doctor.embedding_load_state -ne "real-indexed-unverified") {
    Write-Host "Embeddings unavailable. Running fallback baseline."
    Write-Host "This run is not comparable to Phase 3 hybrid baseline."
}

codegraph eval-edit $Dataset --json --save reports/edit_eval.json
codegraph eval $Dataset --compare bm25,hybrid --save-report reports/retrieval_eval.json
codegraph regression-report `
    --eval $Dataset `
    --edit-eval $Dataset `
    --compare bm25,hybrid `
    --save reports/latest.json `
    --markdown reports/latest.md `
    --gate-profile release
