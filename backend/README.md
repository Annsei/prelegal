# Prelegal backend

FastAPI service that serves the API and the statically-built frontend.

## Routes

- `GET  /api/health` — liveness check.
- `POST /api/auth/register` — register a user.
- `POST /api/auth/login` — fake login: looks up (or creates) a user by email and returns it. **No password verification — placeholder for v1.**
- `GET  /` and other unknown paths — serves the static Next.js export from `static/`.

## Database

SQLite, file path is `PRELEGAL_DB_PATH` (default `/tmp/prelegal.sqlite`). The
file is recreated from scratch on every process start; data does **not**
persist across container restarts.

## Local development

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

The API will be at `http://localhost:8000/api/`. Until you run
`scripts/start-*.sh` (which builds the frontend into `backend/static/`), the
non-API routes will return 404 — that's expected.

## Tests

```bash
cd backend
uv run pytest
```
