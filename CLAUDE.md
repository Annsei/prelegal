# Prelegal Project

## Overview

This is a SaaS product to allow users to draft **PRC-law (中国法) Chinese legal agreements** based on templates in the templates directory. The template library is first-party (Prelegal 范本 v1.0, AI-drafted, not lawyer-reviewed — the product ships a three-place lawyer-review disclaimer); it replaced the original Common Paper (US-law, English) library. The user uses AI chat in order to establish what document they want and how to fill in the fields. The available documents are covered in the catalog.json file in the project root, included here:

@catalog.json

Status: v1 foundation, AI chat, multi-document UI, and multi-user persistence are live. The chat is catalog-aware and the preview pane switches per document — picking any of the 11 catalog docs renders its underlying PRC-law Chinese template with AI-collected key terms (field values are Simplified Chinese; contract text stays Chinese regardless of UI locale). Documents are being upgraded onto a **manifest-driven pipeline** (cover-page field manifest in `templates/manifests/<doc_id>.json` → LLM field checklist + constrained schema → structured Cover Page render + body term-reference highlighting → manifest-driven edit form → download gated on required fields): **the CSA is the first fully-drafted doc on it**. The MNDA keeps its bespoke typed form/preview/PDF for now (migrating it onto the pipeline is a follow-up). The remaining 9 docs read the markdown template through the generic renderer with a flat summary card until they get a manifest — adding one doc ≈ writing one manifest JSON. Requests outside the catalog get routed to the closest available item. Real password auth (bcrypt + bearer-token sessions) gates per-user document CRUD **and the AI chat** (each turn costs LLM credits); login/register/chat are rate-limited and sessions expire after 30 days (configurable). Drafts auto-save (debounced, 800ms) including the conversation log, show up in a left sidebar, and survive container restarts via a host-mounted SQLite volume. The frontend remembers the user's last open draft and restores it (with chat history replayed) on refresh / re-login. Upstream LLM errors are classified into one-line user-facing messages instead of dumping raw exception traces. A "draft, have a lawyer review" disclaimer ships in three places (preview banner, page footer, login marketing column).

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

The entire project should be packaged into a Docker container. The backend should be in `backend/` and be a uv project, using FastAPI. The frontend should be in `frontend/`. Consider statically building the frontend and serving it via FastAPI, if that will work. The database is SQLite, persisted across container restarts via a host-mounted volume so registered users and their saved drafts survive `docker rm` (the schema init is idempotent — `CREATE TABLE IF NOT EXISTS`). There should be scripts in `scripts/` for:

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
  app/db.py        SQLite bootstrap; init_database() runs in lifespan startup
                   (idempotent — preserves existing rows). Schema: users
                   (with password_hash), sessions, documents.
  app/auth.py      bcrypt password helpers + bearer-token `current_user`
                   FastAPI dependency; sessions expire PRELEGAL_SESSION_TTL_DAYS
                   (default 30) after creation, expired rows purged at startup
  app/ratelimit.py in-memory sliding-window rate limiters (login/register
                   per IP, chat per user); PRELEGAL_RATELIMIT_DISABLED=1
                   turns enforcement off for load/test tooling
  app/llm.py       LiteLLM → OpenRouter → Cerebras client; injects catalog.json
                   into the system prompt; when the open doc has a manifest,
                   appends its field checklist and constrains the
                   structured-output field_updates schema to those keys;
                   enforces "always ask a follow-up" (one retry + localized
                   fallback append); classifies upstream exceptions into
                   one-line user-facing messages
  app/manifests.py loads templates/manifests/<doc_id>.json (cover-page field
                   manifests) — shared by templates route + llm prompt/schema
  app/routes/      auth.py (register/login/logout/me), chat.py (POST /api/chat),
                   templates.py (GET /api/templates/{doc_id}),
                   documents.py (per-user CRUD), health.py
  tests/           pytest
frontend/        Next.js 15 (static export, output: "export")
  app/page.tsx     Legal-agreement generator with sidebar / editor / preview
                   layout. Auto-saves (debounced 800 ms) the wrapped doc
                   state (chat log + typed fields) under the current bearer
                   token; routes by currentDocId — MNDA → MNDAForm +
                   MNDAPreview, others → GenericDocPreview. On mount,
                   rehydrates the last-active draft pointer from
                   localStorage so refresh / re-login lands the user back
                   in the same conversation. Redirects to /login if no
                   session.
  app/login/       Two-column login/register page (marketing left, form right).
                   Real password auth.
  components/      MNDAChat (controlled history prop, textarea-focus restore,
                   lazy welcome bubble, multi-doc callbacks, sends doc_id per
                   turn), MNDAForm, MNDAPreview, GenericDocPreview (structured
                   Cover Page + body term-ref highlighting for manifest docs;
                   flat summary card otherwise), DocForm (manifest-driven
                   manual-edit form), DocumentSidebar, SaveStatus, Disclaimer,
                   LanguageToggle
  lib/api.ts       apiFetch (Bearer-token aware) + auth + chatApi
                   + templatesApi + documentsApi
  lib/docManifest.ts  manifest types + allRequiredFilled/extraFields +
                   annotateTermRefs (marks coverpage/orderform/keyterms_link
                   spans as term-defined/term-missing before marked renders)
  lib/useDocTemplate.ts  page-level hook fetching /api/templates/{doc_id}
                   (manifest drives form tab + download gating, so the page
                   owns the fetch, not the preview)
  lib/i18n.ts      zh/en dictionaries (default zh)
  lib/mndaState.ts MndaState type + AI-update merge (drops unknown keys)
  lib/mndaTemplate.ts PRC-law 双方保密协议 standard terms with placeholders
                   (governingLaw = 适用法律, jurisdiction = 争议解决)
  lib/session.ts   localStorage-backed session ({user, token}) under key
                   "prelegal:session". Companion key "prelegal:activeDocId"
                   (written by app/page.tsx) remembers which draft to
                   re-open on next mount.
  e2e/             Playwright (login.spec, mnda.spec, chat.spec, documents.spec,
                   csa.spec — covers focus-return, non-MNDA doc switching,
                   sidebar + debounced auto-save with bearer token, chat
                   history restoration after refresh, and the CSA manifest
                   pipeline: cover page, term-ref highlighting, download
                   gating)
templates/       11 PRC-law Chinese markdown packages (Prelegal 范本 v1.0,
                 AI-drafted; mutual-nda has cover_page + standard_terms,
                 others standard_terms only). Same span conventions as the
                 old Common Paper library (header_2/3, coverpage_link /
                 orderform_link / keyterms_link with Chinese variable
                 names). templates.json indexes them (origin: prelegal).
                 manifests/<doc_id>.json — cover-page field manifests (key,
                 type, required, zh/en labels, hint, example, alias span
                 texts). CSA has one today; adding a doc to the full
                 pipeline ≈ adding its manifest here (+ flipping its
                 catalog.json status to "available").
Dockerfile       multi-stage: Node builds frontend → Python runtime serves both;
                 deps installed with `uv sync --frozen` from the committed
                 backend/uv.lock (reproducible builds); runs as non-root user
                 `prelegal` (entrypoint chowns /data then drops privileges via
                 setpriv — scripts/docker-entrypoint.sh); HEALTHCHECK hits
                 /api/health; catalog.json and templates/ are COPYed into the
                 runtime image at /app and /app/templates respectively
scripts/         start/stop per OS; start scripts forward .env into the
                 container and run with --restart unless-stopped + rotated
                 json-file logs (10MB × 3)
.github/         workflows/ci.yml — four jobs on push/PR: backend (ruff +
                 pytest, locked deps), frontend (eslint + tsc + vitest),
                 e2e (Playwright vs production build), docker (image builds)
```

### Backend API

- `GET /api/health` → `{"status":"ok"}`
- `POST /api/auth/register` → `{user:{id,email,name,created_at}, token}` (409 on duplicate email; 422 if password < 8 chars)
- `POST /api/auth/login` → `{user, token}`; 401 for both unknown email and wrong password (don't leak which)
- `POST /api/auth/logout` → 204; invalidates the bearer token used to make the call
- `GET /api/auth/me` → `{id,email,name,created_at}`; used by the frontend to validate a stored token after a page reload
- `POST /api/chat` → `{messages:[{role,content}], mnda_state, doc_id}` ⇒ `{assistant_message, selected_doc_id, mnda_updates, field_updates, done}`. **Requires `Authorization: Bearer <token>`** (each turn spends LLM credits) and is rate-limited 20/min per user (429 beyond). Stateless (frontend keeps history). `doc_id` is the doc the frontend has open — when it has a manifest, the LLM prompt gains that doc's field checklist and `field_updates` keys are schema-constrained to it; `done: true` becomes reachable once required fields are filled. `selected_doc_id` is the catalog id the LLM picked (empty until intent is clear); `field_updates` is a `{label: value}` map for non-MNDA docs (free-form when the doc has no manifest). `mnda_state` is capped at 64KB serialized (422 beyond). Returns 502 if `OPENROUTER_API_KEY` missing, the LLM call fails, or the LLM returns malformed structured output (all classified into one-line messages).
- `GET /api/templates/{doc_id}` → `{doc_id, title, standard_terms, cover_page?, manifest?}`. Reads from `templates/templates.json` and the markdown files alongside it; `manifest` is the cover-page field manifest from `templates/manifests/` (null for docs without one). 404 on unknown id.
- `GET/POST/PUT/DELETE /api/documents[/{id}]` → per-user draft CRUD. **All require `Authorization: Bearer <token>`.** A user can only see and modify their own rows; cross-user access returns 404 to avoid leaking existence. The `state` field is a wrapped envelope: `{chat: ChatTurn[], mnda?: MndaState, fields?: Record<string,string>}` — `chat` is the conversation log; `mnda` is populated for `mutual-nda` only; `fields` carries cover-page-level key/value data for any other doc. Missing keys decode to fresh-draft defaults on the frontend.
- `GET /` and unknown paths → SPA fallback to the Next.js static export (path-traversal refused, falls back to `index.html`)

`users` schema: `id`, `email UNIQUE`, `name`, `password_hash` (bcrypt), `created_at`.
`sessions` schema: `token PRIMARY KEY`, `user_id FK`, `created_at`. Tokens persist across server restarts and expire `PRELEGAL_SESSION_TTL_DAYS` (default 30) after `created_at` — enforced in the `current_user` query (no `expires_at` column, so existing volumes need no migration); expired rows are purged at startup; explicit logout deletes the row immediately.
`documents` schema: `id, user_id FK, doc_id, title, state_json, created_at, updated_at`.

### Auth model

bcrypt password hashing + bearer-token sessions. Frontend stores `{user, token}` in localStorage under key `prelegal:session` (all localStorage access is wrapped in try/catch — private-mode browsers degrade to a non-persistent session instead of crashing) and sends `Authorization: Bearer <token>` on protected calls (`/api/auth/me`, `/api/auth/logout`, `/api/chat`, all `/api/documents/*`). Tokens persist across server restarts alongside the rest of the DB and expire `PRELEGAL_SESSION_TTL_DAYS` (default 30 days; `0` disables) after creation; explicit `/api/auth/logout` deletes the row immediately. Login pays the same bcrypt cost for unknown emails as for wrong passwords (dummy-hash verify) so response timing doesn't leak which emails are registered. Login (10/min) and register (5/min) are rate-limited per client IP, chat (20/min) per user — in-memory sliding windows, see `app/ratelimit.py`. The frontend handles 401 from any protected call by clearing the session and bouncing to `/login`. `/api/templates/*` remains open today — it serves static template text only.

### Configuration

- `PRELEGAL_DB_PATH` (backend, default `/data/prelegal.sqlite` in Docker) — SQLite file path. The Docker image declares `/data` as a `VOLUME`, and the start scripts bind `$HOME/.prelegal/data` (or `%USERPROFILE%\.prelegal\data` on Windows) into it so users + drafts persist across `docker rm`. For local non-Docker dev pass any writable path (e.g. `./prelegal-dev.sqlite`).
- `OPENROUTER_API_KEY` (backend, **required for AI chat**) — read from the project-root `.env`. Without it `/api/chat` returns 502. The `start-{mac,linux,windows}` scripts forward `.env` into the container automatically.
- `NEXT_PUBLIC_API_BASE_URL` (frontend, default `""`) — set to `http://localhost:8000` for local dev where the Next dev server runs on a different port from FastAPI. Empty in Docker (same origin).
- `PRELEGAL_CORS_ORIGINS` (backend, default unset = CORS off) — comma-separated allowlist of origins. Required for local non-Docker dev (`http://localhost:3000`) because the two dev servers are cross-origin; leave unset in Docker where everything is same-origin.
- `PRELEGAL_SESSION_TTL_DAYS` (backend, default `30`) — sessions expire this many days after creation; `0` disables expiry.
- `PRELEGAL_RATELIMIT_DISABLED` (backend, default unset) — set to `1` to turn off login/register/chat rate limiting (load tests, local tooling). Never set in production.

A committed `.env.example` at the repo root documents these keys — copy it to `.env` to get started.

### Local dev (without Docker)

```bash
cd backend  && uv sync && PRELEGAL_CORS_ORIGINS=http://localhost:3000 PRELEGAL_DB_PATH=./prelegal-dev.sqlite uv run uvicorn app.main:app --reload --port 8000
cd frontend && NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev
```

### Tests & lint

- Backend: `cd backend && uv run pytest`; lint: `uv run ruff check .`
- Frontend unit: `cd frontend && npm test -- --run`
- Frontend lint / types: `cd frontend && npm run lint && npx tsc --noEmit`
- Frontend e2e: `cd frontend && npx playwright test` (CI runs `npm run test:e2e:ci` against the production build)
- CI runs all of the above plus a Docker image build on every push/PR (`.github/workflows/ci.yml`)
