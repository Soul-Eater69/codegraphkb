#!/usr/bin/env bash
set -euo pipefail

DATASET="${1:-evals/datasets/self_repo_tasks.yaml}"

rm -rf .codegraphkb
mkdir -p reports

codegraph index . --parser auto --embed
codegraph doctor --json > reports/doctor.json
codegraph stats --object-types

python - <<'PY'
import json
from pathlib import Path

doctor = json.loads(Path("reports/doctor.json").read_text(encoding="utf-8"))
state = doctor.get("embedding_load_state", "none")
if state != "real-indexed-unverified":
    print("Embeddings unavailable. Running fallback baseline.")
    print("This run is not comparable to Phase 3 hybrid baseline.")
PY

codegraph eval-edit "$DATASET" --json --save reports/edit_eval.json
codegraph eval "$DATASET" --compare bm25,hybrid --save-report reports/retrieval_eval.json
codegraph regression-report \
  --eval "$DATASET" \
  --edit-eval "$DATASET" \
  --compare bm25,hybrid \
  --save reports/latest.json \
  --markdown reports/latest.md \
  --gate-profile release
