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
uv run ruff check .
uv run pytest -m "not contract_quality_gate"
```

The ordinary test suite includes fresh-process tripwires for accidental socket,
DNS, subprocess, and LLM imports. Those Python hooks are regression checks, not
a security sandbox. The authoritative hard gate runs the full deterministic
11-document kernel, download, and DOCX/PDF evaluation in the Linux quality-gate
image under `docker run --network none --cap-drop ALL --security-opt
no-new-privileges`; see `.github/workflows/ci.yml` for the exact command.

## PL-24B live LLM behavior evaluation

PL-24's `quality_evals` gate is deterministic and kernel-isolated. PL-24B's
`llm_quality_evals` runner is a separate, opt-in check of the real authenticated
`POST /api/chat` path through LiteLLM, OpenRouter, and the Cerebras provider. Its
versioned corpus contains 34 cases across catalog routing, manifest field
extraction, follow-up behavior, and prompt injection for all 11 documents.

Ordinary pytest, GitHub CI, and the deterministic quality gate never run this
live evaluator and never spend LLM credits. A live run requires an
`OPENROUTER_API_KEY` already present in the process environment plus both
`--live` and `--confirm-spend`. Do not paste the key into commands or reports.
Every evaluator completion forces LiteLLM `max_retries=0`; `--max-calls` is the
hard run-wide outer-provider-attempt budget, and `--max-retries` is a separate
run-wide evaluator retry budget. Product follow-up calls share `--max-calls` but
are reported separately. The serial request pacer respects the production chat
limit of 20 requests per 60 seconds.

```bash
cd backend

# Three-case smoke; never exceeds three outer provider attempts.
uv run python -m llm_quality_evals --live --confirm-spend --smoke \
  --max-calls 3 --max-retries 0 --output /tmp/prelegal-pl24b-smoke.json --json

# One named case, one category, or one document.
uv run python -m llm_quality_evals --live --confirm-spend \
  --case fields.mnda-simplified-chinese --max-calls 2 --max-retries 0
uv run python -m llm_quality_evals --live --confirm-spend \
  --category manifest_field_extraction --max-calls 10 --max-retries 0
uv run python -m llm_quality_evals --live --confirm-spend \
  --doc mutual-nda --max-calls 12 --max-retries 0

# Full 34-case corpus. This can spend substantially more credits; review the
# budget before running. It is documentation only and is not a CI command.
uv run python -m llm_quality_evals --live --confirm-spend \
  --max-calls 68 --max-retries 0 --output /tmp/prelegal-pl24b-full.json
```

Reports use `schema_version=1` and include run/model/provider metadata, selected
case ids, per-case pass/fail/error/skipped status, assertion outcomes, latency,
SDK-retry-disabled `actual_calls`, evaluator retries, product follow-up calls,
local fallback counts, token usage, provider-reported cost when available,
an explicit null estimated cost when no locked pricing source exists, aggregate
totals, and invariant errors. They omit prompts, response text,
headers, bearer tokens, passwords, and API keys. Put any repository-local
reports under `.live-eval-reports/`, which is ignored; live reports are not
product artifacts and should not be committed.

Exit codes are: `0` complete with all quality assertions passing; `1` a quality
failure or report invariant failure; `2` corpus/startup/configuration failure
before a run; `3` incomplete due to upstream, call-budget, or local route-limit
failure. `pass` and `fail` are completed model responses, `error` is an
incomplete case, and remaining cases become `skipped` after an incomplete
error. A live result does not establish legal accuracy, lawyer review, or that a
document is safe to sign.
