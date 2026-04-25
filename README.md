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

> **Heads up:** the SQLite DB is recreated from scratch on every container
> start. There is no real authentication yet — the login screen will land any
> email on the platform. This is the v1 foundation, not a production setup.

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
local FastAPI process.

```bash
# Terminal 1 — backend
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev
```
