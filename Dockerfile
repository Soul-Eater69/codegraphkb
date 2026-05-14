FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir -e ".[api,parser,embeddings]"

EXPOSE 8765

CMD ["python", "-m", "codegraphkb.server.run_product_api"]

