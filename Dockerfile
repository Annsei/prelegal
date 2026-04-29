# syntax=docker/dockerfile:1.7

# ---------- Frontend builder ----------
FROM node:22-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- Python runtime ----------
FROM python:3.12-slim AS runtime

# uv: pinned binary, copied straight from the official image. Faster than
# `pip install uv` and avoids needing build tools in the final image.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

WORKDIR /app/backend

# Install dependencies first so the layer cache survives source edits.
# README.md is referenced by pyproject and hatchling refuses to build without it.
COPY backend/pyproject.toml backend/README.md ./
RUN uv sync --no-dev --no-install-project

# App source + the static frontend export from the Node stage.
COPY backend/app/ ./app/
COPY --from=frontend /app/frontend/out/ /app/backend/static/

# catalog.json is read at backend import time to drive multi-doc routing
# in the chat. Keep its path in lockstep with the Path() resolution in
# app/llm.py: from /app/backend/app/llm.py, parent.parent.parent is /app.
COPY catalog.json /app/catalog.json

# Templates serve the GET /api/templates/{doc_id} preview endpoint. Path
# resolution in app/routes/templates.py expects them at /app/templates.
COPY templates/ /app/templates/

# Final install (places the project itself into the venv).
RUN uv sync --no-dev

# SQLite lives under /data so users and saved drafts persist across
# container restarts. Declaring it as a VOLUME means even a `docker run`
# without an explicit mount gets an anonymous volume — better than
# silently losing data on `docker rm`. The start scripts bind a host
# directory ($HOME/.prelegal/data) here so the file lives outside the
# container entirely.
ENV PRELEGAL_DB_PATH=/data/prelegal.sqlite
VOLUME ["/data"]
EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
