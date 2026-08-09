# Getting Started

Boot the API, run a chat, and make sure everything is wired correctly.

## 1. Prerequisites

- **Python 3.11+** (enforced in `pyproject.toml`)
- **Docker** (for Postgres + Redis via `docker-compose.yml`)
- **`uv`** package manager ([install](https://docs.astral.sh/uv/))
- **Node.js** (only if you plan to use stdio MCP servers like the filesystem MCP)
- At least one LLM provider API key (OpenAI, Anthropic, or Gemini)
- For travel mode: **Tavily** (`TAVILY_API_KEY`) and **Jina** (`JINA_API_KEY`) for web search and deep research

## 2. Start infrastructure

```bash
docker-compose up -d postgres redis
```

This launches:

- `postgres` — `pgvector/pgvector:pg16` image on port `5432`
- `redis` — `redis:7-alpine` on port `6379`

## 3. Install dependencies

```bash
uv venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

uv sync --extra dev
```

## 4. Configure `.env`

```bash
cp .env.example .env
```

Open `.env` and set **at minimum**:

- `JWT_SECRET_KEY` — any long random string.
- `OPENAI_API_KEY` **or** `ANTHROPIC_API_KEY` **or** `GOOGLE_API_KEY`.
- `DEFAULT_LLM_PROVIDER` — must match the provider above (`openai` | `anthropic` | `gemini`).
- `DEFAULT_MODEL_NAME` — a model ID valid for that provider.
- `TRAVEL_PLANNER_ENABLED=true` — enables the travel guide graphs (recommended for this project).
- `PGVECTOR_ENABLED=true` + `OPENAI_API_KEY` — destination RAG for the city expert.
- `TAVILY_API_KEY` — web search for specialists and fallback.
- `JINA_API_KEY` — deep research when building a new destination KB.

Everything else has sensible defaults. See [`configuration.md`](./configuration.md) for the full reference.

## 5. Apply migrations

```bash
alembic upgrade head
```

This creates the `users` and `sessions` tables. LangGraph's Postgres checkpointer provisions its own tables lazily on first run.

## 6. Run the API

```bash
# Windows (PowerShell)
./scripts/dev.ps1

# macOS / Linux
./scripts/dev.sh
```

Open <http://localhost:8000/docs> for the interactive OpenAPI UI.

## 7. First trip plan (travel mode)

With `TRAVEL_PLANNER_ENABLED=true`, chat starts the **Travel Planner**:

```bash
# 1) Register
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"name":"Ada","email":"ada@example.com","password":"hunter22"}'

# 2) Login and grab access_token from the response
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"ada@example.com","password":"hunter22"}'

# 3) Create a session (replace $TOKEN)
curl -X POST http://localhost:8000/api/v1/sessions/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"Paris trip"}'

# 4) Plan a trip (replace $SESSION_ID)
curl -X POST http://localhost:8000/api/v1/chat/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"session_id":"'$SESSION_ID'","message":"Plan 5 days in Paris, budget mid-range"}'
```

If the response includes `"interrupted": true`:

- **Missing trip details** — resume with `POST /api/v1/runs/{thread_id}/resume` and `{"feedback": "..."}`.
- **KB build approval** — resume with `{"action": "approve"}` (deep research + ingest) or `{"action": "reject"}` (web search only, nothing stored).

See [`travel-planner.md`](./travel-planner.md), [`knowledge-builder.md`](./knowledge-builder.md), and [`api-reference.md`](./api-reference.md#human-approval).

> **Template mode** (`TRAVEL_PLANNER_ENABLED=false`): use a generic message like `"Hi, what time is it in Tokyo?"` to exercise the supervisor graph instead.

## 8. Run the tests

```bash
pytest -v
```

The e2e chat test is skipped by default unless the full stack + real API keys are present.

## 9. Optional: Celery worker

```bash
celery -A workers.celery_app worker --loglevel=info --concurrency=2
```

Use this path when you want agent runs deferred out of the HTTP request cycle. See [`deployment.md`](./deployment.md).

## Next steps

- Read [`onboarding.md`](./onboarding.md) for the full new-developer guide (architecture tour, recipes, debugging).
- Read [`travel-planner.md`](./travel-planner.md) and [`knowledge-builder.md`](./knowledge-builder.md) for the two core graphs.
- Read [`architecture.md`](./architecture.md) to understand why the code is organised the way it is.
- Read [`agent-orchestration.md`](./agent-orchestration.md) for travel mode and template supervisor internals.
- Read [`deployment.md`](./deployment.md) to deploy the `stage` branch to GCE via GitHub Actions.
