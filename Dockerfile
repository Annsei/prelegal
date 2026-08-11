# syntax=docker/dockerfile:1.7

# ---------- Shared Python base ----------
FROM python:3.12-slim AS python-base

# WeasyPrint needs Pango at runtime; Noto CJK supplies deterministic Chinese
# glyph coverage for PDF generation instead of relying on host fonts.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fonts-noto-cjk \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

# uv: pinned binary, copied straight from the official image. Faster than
# `pip install uv` and avoids needing build tools in the final image.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

WORKDIR /app/backend

# README.md is referenced by pyproject. The quality stage installs the full
# locked dependency set; the product runtime installs only production deps.
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./

# ---------- Kernel-isolated quality gate ----------
# Dependency installation happens at build time. The resulting image is run
# without network, capabilities, host mounts, or an OpenRouter key.
FROM python-base AS quality-gate
RUN uv sync --frozen --no-install-project
COPY backend/app/ ./app/
COPY backend/quality_evals/ ./quality_evals/
COPY catalog.json /app/catalog.json
COPY templates/ /app/templates/
RUN useradd --system --user-group --no-create-home prelegal \
    && chown -R prelegal:prelegal /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache
USER prelegal
ENTRYPOINT ["/app/backend/.venv/bin/python", "-m", "quality_evals.kernel_gate"]
CMD []

# ---------- Frontend builder ----------
FROM node:22-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- Product runtime ----------
FROM python-base AS runtime

# Install dependencies first so the layer cache survives source edits.
# uv.lock pins exact versions; --frozen prevents dependency re-resolution.
RUN uv sync --frozen --no-dev --no-install-project

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

# Final install places the project itself into the venv.
RUN uv sync --frozen --no-dev

# Unprivileged runtime user. The entrypoint starts as root only to chown
# /data (bind mounts arrive with arbitrary ownership) and then drops to
# this user via setpriv; see scripts/docker-entrypoint.sh.
RUN useradd --system --user-group --no-create-home prelegal \
    && chown -R prelegal:prelegal /app
COPY --chmod=755 scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# SQLite lives under /data so users and saved drafts persist across
# container restarts. The start scripts bind a host directory here.
ENV PRELEGAL_DB_PATH=/data/prelegal.sqlite
VOLUME ["/data"]
EXPOSE 8000

# The API is up when /api/health answers; python3 (system, not the venv)
# keeps the check dependency-free.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["/app/backend/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Keep the default Docker target as the product runtime.
FROM runtime AS production
