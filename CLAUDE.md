# Prelegal Project

## Overview

This is a SaaS product to allow users to draft legal agreements based on templates in the templates directory. The user uses AI chat in order to establish what document they want and how to fill in the fields. The available documents are covered in the catalog.json file in the project root, included here:

@catalog.json

Status: v1 foundation, AI chat, multi-document UI, and multi-user persistence are live. The chat is catalog-aware and the preview pane switches per document — picking any of the 11 catalog docs renders its underlying Common Paper template with AI-collected key terms. **Only the MNDA has a typed manual-edit form, bespoke placeholder rendering, and PDF download** today; the other 10 docs read the markdown template through a generic renderer with a Cover Page Summary card on top. Requests outside the catalog get routed to the closest available item. Real password auth (bcrypt + bearer-token sessions) gates per-user document CRUD; drafts auto-save (debounced, 800ms) and show up in a left sidebar. A "draft, have a lawyer review" disclaimer ships in three places (preview banner, page footer, login marketing column).

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
  app/db.py        SQLite bootstrap; reset_database() runs in lifespan startup.
                   Schema: users (with password_hash), sessions, documents.
  app/auth.py      bcrypt password helpers + bearer-token `current_user`
                   FastAPI dependency
  app/llm.py       LiteLLM → OpenRouter → Cerebras client; injects catalog.json
                   into the system prompt; enforces "always ask a follow-up"
                   (one retry + localized fallback append)
  app/routes/      auth.py (register/login/logout/me), chat.py (POST /api/chat),
                   templates.py (GET /api/templates/{doc_id}),
                   documents.py (per-user CRUD), health.py
  tests/           pytest
frontend/        Next.js 15 (static export, output: "export")
  app/page.tsx     Legal-agreement generator with sidebar / editor / preview
                   layout. Auto-saves (debounced 800 ms) under the current
                   bearer token; routes by currentDocId — MNDA →
                   MNDAForm + MNDAPreview, others → GenericDocPreview.
                   Redirects to /login if no session.
  app/login/       Two-column login/register page (marketing left, form right).
                   Real password auth.
  components/      MNDAChat (textarea-focus restore + multi-doc callbacks),
                   MNDAForm, MNDAPreview, GenericDocPreview,
                   DocumentSidebar, SaveStatus, Disclaimer, LanguageToggle
  lib/api.ts       apiFetch (Bearer-token aware) + auth + chatApi
                   + templatesApi + documentsApi
  lib/i18n.ts      zh/en dictionaries (default zh)
  lib/mndaState.ts MndaState type + AI-update merge (drops unknown keys)
  lib/mndaTemplate.ts Common Paper MNDA standard terms with placeholders
  lib/session.ts   localStorage-backed session ({user, token}) under key
                   "prelegal:session"
  e2e/             Playwright (login.spec, mnda.spec, chat.spec, documents.spec
                   — covers focus-return, non-MNDA doc switching, sidebar +
                   debounced auto-save with bearer token)
templates/       11 Common Paper markdown packages (mutual-nda has cover_page
                 + standard_terms; others have standard_terms only).
                 templates.json indexes them with provenance commits.
Dockerfile       multi-stage: Node builds frontend → Python runtime serves both;
                 catalog.json and templates/ are COPYed into the runtime image
                 at /app and /app/templates respectively
scripts/         start/stop per OS; start scripts forward .env into the container
```

### Backend API

- `GET /api/health` → `{"status":"ok"}`
- `POST /api/auth/register` → `{user:{id,email,name,created_at}, token}` (409 on duplicate email; 422 if password < 8 chars)
- `POST /api/auth/login` → `{user, token}`; 401 for both unknown email and wrong password (don't leak which)
- `POST /api/auth/logout` → 204; invalidates the bearer token used to make the call
- `GET /api/auth/me` → `{id,email,name,created_at}`; used by the frontend to validate a stored token after a page reload
- `POST /api/chat` → `{messages:[{role,content}], mnda_state}` ⇒ `{assistant_message, selected_doc_id, mnda_updates, field_updates, done}`. Stateless (frontend keeps history). `selected_doc_id` is the catalog id the LLM picked (empty until intent is clear); `field_updates` is a free-form `{label: value}` map for non-MNDA docs (cover-page-level data). Returns 502 if `OPENROUTER_API_KEY` missing or the LLM call fails.
- `GET /api/templates/{doc_id}` → `{doc_id, title, standard_terms, cover_page?}`. Reads from `templates/templates.json` and the markdown files alongside it. 404 on unknown id.
- `GET/POST/PUT/DELETE /api/documents[/{id}]` → per-user draft CRUD. **All require `Authorization: Bearer <token>`.** A user can only see and modify their own rows; cross-user access returns 404 to avoid leaking existence. State JSON shape is MndaState for `mutual-nda`, free-form `{label: value}` for any other doc.
- `GET /` and unknown paths → SPA fallback to the Next.js static export (path-traversal refused, falls back to `index.html`)

`users` schema: `id`, `email UNIQUE`, `name`, `password_hash` (bcrypt), `created_at`.
`sessions` schema: `token PRIMARY KEY`, `user_id FK`, `created_at` — DB resets every restart, so tokens are intentionally short-lived.
`documents` schema: `id, user_id FK, doc_id, title, state_json, created_at, updated_at`.

### Auth model

bcrypt password hashing + bearer-token sessions. Frontend stores `{user, token}` in localStorage under key `prelegal:session` and sends `Authorization: Bearer <token>` on protected calls (`/api/auth/me`, `/api/auth/logout`, all `/api/documents/*`). Tokens vanish when the server restarts (DB resets); the frontend handles 401 from any protected call by clearing the session and bouncing to `/login`. `/api/chat` and `/api/templates/*` remain open today — gating them is a follow-up.

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
