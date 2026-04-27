# Prelegal Project

## Overview

This is a SaaS product to allow users to draft legal agreements based on templates in the templates directory. The user uses AI chat in order to establish what document they want and how to fill in the fields. The available documents are covered in the catalog.json file in the project root, included here:

@catalog.json

Status: v1 foundation, MNDA generator, and AI chat are all live. The chat is multi-document aware (knows the catalog and routes non-MNDA requests politely back to MNDA), but only the Mutual NDA has a full form/preview/PDF flow today.

## Development process

When instructed to build a feature:

1. Use your Atlassian tools to read the feature instructions from Jira
2. Develop the feature - do not skip any step from the feature-dev 7 step process
3. Thoroughly test the feature with unit tests and integration tests and fix any issues
4. Submit a PR using your github tools

## AI design

When writing code to make calls to LLMs, use your Cerebras skill to use LiteLLM via OpenRouter to the 'openrouter/openAI/gpt-oss-120b' model with Cerebras as the inference provider. You should use Structured Outputs so that you can interpret the results and populate fields in the legal document.

The OpenRouter API key is available in the `.env` file at the project root.

## Technical design

The entire project should be packaged into a Docker container. The backend should be in `backend/` and be a uv project, using FastAPI. The frontend should be in `frontend/`. Consider statically building the frontend and serving it via FastAPI, if that will work. The database is SQLite, recreated from scratch every time the Docker container starts, with a `users` table supporting registration and login. There should be scripts in `scripts/` for:

```
# Mac
scripts/start-mac.sh        # Start
scripts/stop-mac.sh         # Stop

# Linux
scripts/start-linux.sh
scripts/stop-linux.sh

# Windows
scripts/start-windows.ps1
scripts/stop-windows.ps1
```

Backend available at http://localhost:8000

## Color Scheme

- Accent Yellow: `#ecad0a`
- Blue Primary: `#209dd7`
- Purple Secondary: `#753991` (submit buttons)
- Dark Navy: `#032147` (headings)
- Gray Text: `#888888`

## Current implementation

### Layout

```
backend/         FastAPI service (uv project)
  app/main.py      app factory + SPA fallback (path-traversal guarded)
  app/db.py        SQLite bootstrap; reset_database() runs in lifespan startup
  app/llm.py       LiteLLM → OpenRouter → Cerebras client; injects catalog.json
                   into the system prompt; enforces "always ask a follow-up"
  app/routes/      auth.py (register/login), chat.py (POST /api/chat), health.py
  tests/           pytest
frontend/        Next.js 15 (static export, output: "export")
  app/page.tsx     MNDA generator; redirects to /login if no session
  app/login/       fake login page (email-only, no password)
  components/      MNDAChat, MNDAForm, MNDAPreview, LanguageToggle
  lib/api.ts       apiFetch + auth.{login,register} + chatApi.send
  lib/i18n.ts      zh/en dictionaries (default zh)
  lib/mndaState.ts MndaState type + AI-update merge (drops unknown keys)
  lib/mndaTemplate.ts Common Paper MNDA standard terms with placeholders
  lib/session.ts   localStorage-backed session under key "prelegal:user"
  e2e/             Playwright (login, mnda, chat)
Dockerfile       multi-stage: Node builds frontend → Python runtime serves both;
                 catalog.json is COPYed into the runtime image at /app
scripts/         start/stop per OS; start scripts forward .env into the container
```

### Backend API

- `GET /api/health` → `{"status":"ok"}`
- `POST /api/auth/register` → `{id,email,name,created_at}` (409 on duplicate email)
- `POST /api/auth/login` → finds-or-creates user by email; **no password verification yet**, race-safe against concurrent first logins
- `POST /api/chat` → `{messages:[{role,content}], mnda_state}` ⇒ `{assistant_message, mnda_updates, done}`. Stateless (frontend keeps history). Returns 502 if `OPENROUTER_API_KEY` missing or the LLM call fails.
- `GET /` and unknown paths → SPA fallback to the Next.js static export (path-traversal refused, falls back to `index.html`)

`users` schema: `id`, `email UNIQUE`, `name`, `created_at`. **No password column** — when real auth is added, this is the place.

### Auth model (placeholder)

The login screen accepts any email and lands the user on `/`. Session is just a `localStorage` blob; the backend has no gate. Real auth (passwords + signed sessions/cookies) is a future task — do not assume any endpoint is protected.

### Configuration

- `PRELEGAL_DB_PATH` (backend, default `/tmp/prelegal.sqlite`) — SQLite file path; recreated on every process start.
- `OPENROUTER_API_KEY` (backend, **required for AI chat**) — read from the project-root `.env`. Without it `/api/chat` returns 502. The `start-{mac,linux,windows}` scripts forward `.env` into the container automatically.
- `NEXT_PUBLIC_API_BASE_URL` (frontend, default `""`) — set to `http://localhost:8000` for local dev where the Next dev server runs on a different port from FastAPI. Empty in Docker (same origin).

### Local dev (without Docker)

```bash
cd backend  && uv sync && uv run uvicorn app.main:app --reload --port 8000
cd frontend && NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev
```

### Tests

- Backend: `cd backend && uv run pytest`
- Frontend unit: `cd frontend && npm test -- --run`
- Frontend e2e: `cd frontend && npx playwright test`
