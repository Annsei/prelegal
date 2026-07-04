# Prelegal

A platform for drafting common legal agreements.

## Quick start (Docker)

```bash
# macOS
scripts/start-mac.sh        # build + run
scripts/stop-mac.sh

# Linux
scripts/start-linux.sh
scripts/stop-linux.sh

# Windows (PowerShell)
scripts/start-windows.ps1
scripts/stop-windows.ps1
```

Then open <http://localhost:8000>. The container builds the frontend, mounts
it under FastAPI, and serves both the API (`/api/*`) and the static site from
the same port.

Before starting, copy `.env.example` to `.env` at the repo root and fill in
`OPENROUTER_API_KEY` — the AI chat returns 502 without it. The start scripts
forward `.env` into the container automatically.

Accounts use real password auth (bcrypt + bearer-token sessions), and the
SQLite DB is persisted on the host (`~/.prelegal/data`), so users and saved
drafts survive container restarts and `docker rm`.

## Layout

```
backend/         FastAPI service (uv project) — see backend/README.md
frontend/        Next.js 15 app (static export) — see frontend/TESTING.md
scripts/         start/stop scripts per OS
templates/       Common Paper legal templates (read-only data)
catalog.json     Document catalog used by the AI chat to suggest templates
Dockerfile       Multi-stage: Node builds the frontend, Python serves it
```

## Local development (without Docker)

Frontend and backend can run independently. Set
`NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` so the dev server hits the
local FastAPI process, and `PRELEGAL_CORS_ORIGINS=http://localhost:3000` on
the backend — the two dev servers are cross-origin, so browsers block the
API calls without it. (CORS stays off in Docker, where everything is served
from one origin.)

```bash
# Terminal 1 — backend
cd backend
uv sync
PRELEGAL_CORS_ORIGINS=http://localhost:3000 \
PRELEGAL_DB_PATH=./prelegal-dev.sqlite \
uv run uvicorn app.main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev
```
