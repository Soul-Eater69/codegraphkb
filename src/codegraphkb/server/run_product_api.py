"""Run the CodeGraphKB multi-project product API."""
from __future__ import annotations

import uvicorn  # type: ignore

from codegraphkb.server.product_api import build_product_app


app = build_product_app()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8765)

