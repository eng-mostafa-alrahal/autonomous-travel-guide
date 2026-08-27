# Configuration

Everything is loaded from `.env` (via `pydantic-settings`). The schema is `app/core/config/settings.py`.

> **`.env` wins over OS env** — the source order is customised so that stale shell / IDE variables don't silently override the repo's `.env`. If a setting "looks ignored", it almost always means it's missing from `.env` and being picked up from your OS environment.

Re-read on every `get_settings()` call (no LRU cache), so editing `.env` and hitting a new request picks up the change without restart — except for values that only apply at graph-compile time. Those are listed under [Recompile-on-change](#recompile-on-change).

## Application

| Var | Type | Default | Notes |
|---|---|---|---|
| `APP_NAME` | str | `Travel Guide System` | Shown in OpenAPI + health. |
| `APP_VERSION` | str | `0.1.0` | — |
| `ENVIRONMENT` | `development` \| `staging` \| `production` | `development` | Changes logging behaviour + MCP warnings. |
| `DEBUG` | bool | `false` | Surfaces extra tracebacks in logs. |
| `LOG_LEVEL` | str | `INFO` | — |

## Server

| Var | Default | Notes |
|---|---|---|
| `HOST` | `0.0.0.0` | — |
| `PORT` | `8000` | — |
| `WORKERS` | `1` | Used by Gunicorn configs under `app/core/config/gunicorn_configs.py`. |

## Database (Postgres)

| Var | Default | Notes |
|---|---|---|
| `DATABASE_HOST` | `localhost` | — |
| `DATABASE_PORT` | `5432` | — |
| `DATABASE_USER` | `postgres` | Shared-infra (`shared-infra-postgres-1`) uses `postgres` / `postgres`. |
| `DATABASE_PASSWORD` | `postgres` | Match the container. |
| `DATABASE_NAME` | `agent_db` | Created automatically by `ensure_database_exists()` if missing. Local `.env` often uses `autonomous_travel_guide_db`. |
| `DATABASE_URL` | — | Full async URL. If set, overrides the components above. |
| `DB_POOL_SIZE` | `20` | SQLAlchemy pool. |
| `DB_MAX_OVERFLOW` | `10` | — |
| `DB_POOL_RECYCLE` | `3600` | Seconds. |

Built URL: `postgresql+asyncpg://<user>:<pw>@<host>:<port>/<db>`.  
A sync URL (`psycopg2`) is derived via `settings.get_database_sync_url()` for tools that need it (Alembic, LangGraph checkpointer).

For local shared infra already on `:5432` / `:6379`, point `.env` at those containers instead of `docker-compose up postgres redis`. Shared Postgres is `pgvector/pgvector:pg16` with user/password `postgres` — keep `PGVECTOR_ENABLED=true`.

## Redis

| Var | Default | Notes |
|---|---|---|
| `REDIS_HOST` | `localhost` | Shared-infra Redis is `localhost:6379` with no password. |
| `REDIS_PORT` | `6379` | — |
| `REDIS_USER_NAME` | `default` | — |
| `REDIS_PASSWORD` | `` | — |
| `REDIS_DB` | `0` | — |
| `REDIS_SSL` | `false` | Set `true` only for TLS (e.g. Redis Cloud `rediss://`). |
| `REDIS_URL` | — | Full URL override. |

## JWT / Auth

| Var | Default | Notes |
|---|---|---|
| `JWT_SECRET_KEY` | `CHANGE-ME-IN-PRODUCTION` | **Must be set in any real deployment.** |
| `JWT_ALGORITHM` | `HS256` | — |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | — |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | — |
| `RATE_LIMIT_PER_MINUTE` | `60` | Used by `slowapi`. |

## LLM providers

| Var | Default | Notes |
|---|---|---|
| `OPENAI_API_KEY` | `` | — |
| `ANTHROPIC_API_KEY` | `` | — |
| `GOOGLE_API_KEY` | `` | Gemini. |
| `DEFAULT_LLM_PROVIDER` | `openai` | One of `openai` \| `anthropic` \| `gemini`. |
| `DEFAULT_MODEL_NAME` | `openai/gpt-oss-120b` | Must be valid for the selected provider. |

Provider builders live in `app/infrastructure/llm_gateways/`.

## Research tools

| Var | Default | Notes |
|---|---|---|
| `TAVILY_API_KEY` | `` | If unset, `web_search` tool is not registered. Alias: `TAVILY_KEY`. |
| `EMBEDDING_MODEL` | `jina-embeddings-v3` | Query-time embedder. Must match ingest (`INGESTION_*`). |
| `EMBEDDING_DIMENSIONS` | `1024` | Must match the embedding model and stored vectors. |
| `EMBEDDING_API_KEY` | `` | Falls back to `OPENAI_API_KEY` when empty. |
| `EMBEDDING_BASE_URL` | `` | Set to `https://api.jina.ai/v1` for Jina. When set, query embeddings skip OpenAI token pre-processing (`check_embedding_ctx_length=False`) so Jina accepts the request. |
| `PGVECTOR_COLLECTION` | `knowledge_base` | Logical table namespace. |
| `PGVECTOR_ENABLED` | `false` | Requires the `pgvector` extension (the `pgvector/pgvector:pg16` image in shared-infra compose has it). |

When `PGVECTOR_ENABLED=true` **and** an embedding API key is set (`EMBEDDING_API_KEY` or `OPENAI_API_KEY`), the RAG tool / city-expert retriever is constructed with a live `pgvector` store.  If initialisation fails, a warning is logged and callers get empty retrieval rather than a hard crash.

If query embeddings fail (wrong `EMBEDDING_BASE_URL`, model 404, key mismatch), retrieval looks empty even when `kb_destinations` already has `status=ready`. The city expert must **not** ask to rebuild in that case — it falls back to web search. Symptom of a misconfigured query embedder: "I don't have a knowledge base for X yet" on a city you just indexed.

## Travel Guide

These drive the travel-planner and knowledge-builder graphs.

| Var | Default | Notes |
|---|---|---|
| `KNOWLEDGE_PREP_ENABLED` | `true` | Enables the dedup/preparation step before ingestion. |
| `KNOWLEDGE_PREP_INCLUDE_MODEL` | `true` | Whether the prep step uses an LLM pass. |
| `TRAVEL_PLANNER_ENABLED` | `false` | When `true`, the master graph routes through the travel-planner / knowledge-builder pipeline instead of the generic supervisor. |
| `VALIDATOR_MODEL` | `` | Model override for the deduplication/validator agent. Falls back to `DEFAULT_MODEL_NAME`. |
| `RESEARCHER_MODEL` | `` | Model override for the deep-research agent. |
| `LOGISTICIAN_MODEL` | `` | Model override for the flights / travel & logistics agent. |

### Travel data providers (Stage 10)

Specialists source data from a real provider when configured, and fall back to web search (or the distance heuristic) on `none`, empty results, or any error — so CI and offline runs are unchanged by default.

| Var | Type | Default | Notes |
|---|---|---|---|
| `TRAVEL_MOCK_APIS` | bool | `false` | Master switch: when `true`, **all four** providers use the offline fixture pack (London, Paris, Rome, Berlin, New York, Damascus, Los Angeles). Does **not** skip the knowledge builder — `city_expert` still detects KB misses. Overrides the per-provider flags below. |
| `PLACES_PROVIDER` | `osm` \| `none` | `none` | POI/geocoding for `city_expert` + `food`. `osm` = Nominatim. Ignored when `TRAVEL_MOCK_APIS=true`. |
| `TRANSIT_PROVIDER` | `osrm` \| `none` | `none` | Routed leg distance/time in `spatial_cluster`. `osrm` = OSRM. |
| `FLIGHTS_PROVIDER` | `none` | `none` | No live adapter yet — use `TRAVEL_MOCK_APIS` for offline flight/logistics options. |
| `HOTELS_PROVIDER` | `none` | `none` | No live adapter yet — use `TRAVEL_MOCK_APIS` for offline hotels. |
| `NOMINATIM_BASE_URL` | str | `https://nominatim.openstreetmap.org` | Override to point at a self-hosted Nominatim. |
| `NOMINATIM_USER_AGENT` | str | `autonomous-travel-guide/0.1` | Nominatim's usage policy requires an identifiable User-Agent. |
| `OSRM_BASE_URL` | str | `https://router.project-osrm.org` | Override for a self-hosted OSRM. |
| `TRAVEL_PROVIDER_TIMEOUT_S` | float | `15.0` | Per-request timeout for provider HTTP calls. |

Ports live in `modules/agent_orchestration/application/ports/travel_providers_port.py`; adapters + factory in `app/infrastructure/travel/` (`mock_data.py` / `mock_providers.py` for the offline pack). Adding a live provider = implement the port, add a `Literal` flag value, branch in `factory.py`. All of these are read at graph-compile time — see [Recompile-on-change](#recompile-on-change).

### Jina DeepSearch (deep research)

| Var | Default | Notes |
|---|---|---|
| `JINA_API_KEY` | `` | Required for the deep-research agent. |
| `JINA_DEEPSEARCH_MODEL` | `jina-deepsearch-v1` | — |
| `JINA_DEEPSEARCH_TIMEOUT_S` | `300` | Per-request timeout for deep research. |
| `JINA_DEEPSEARCH_REASONING_EFFORT` | `medium` | One of `low` \| `medium` \| `high`. |

### Ingestion service (RAG Document Processor)

| Var | Default | Notes |
|---|---|---|
| `INGESTION_SERVICE_URL` | `` | Base URL of the external RAG Document Processor (no trailing slash, no `/api/v1`). **Leave empty to use the local pgvector ingestion fallback.** |
| `INGESTION_SERVICE_API_KEY` | `` | The `rag_...` client key, sent as the `X-API-Key` header. Issued by the service operator. |
| `INGESTION_SERVICE_TIMEOUT_S` | `60` | HTTP client timeout per call. |
| `INGESTION_POLL_TIMEOUT_S` | `300` | Max time to poll a job before giving up. |
| `INGESTION_POLL_INTERVAL_S` | `2.0` | Delay between job-status polls. |
| `INGESTION_EMBEDDING_PIPELINE` | `late_chunking` | `late_chunking` \| `chunk_then_embed`. Must match the query-time embedder (Jina for late chunking). |
| `INGESTION_EMBEDDER_PROVIDER` | `jina` | `openai` \| `jina`. Pinned on every request so the service can't silently fall back to a different embedder. |
| `INGESTION_MACRO_SPLITTER` | `semantic` | `recursive` \| `semantic` \| `token_aware`. |
| `INGESTION_LATE_CHUNK_MIN_TOKENS` | `800` | Late-chunking only: merge tiny fragments up to this size. |
| `INGESTION_LATE_CHUNK_MAX_TOKENS` | `2000` | Late-chunking only: max tokens per stored chunk. |
| `INGESTION_MAX_CONCURRENCY` | `4` | Knowledge segments are submitted as independent jobs; this bounds how many are in flight. |
| `AGENT_GRAPH_TIMEOUT_S` | `900` | Overall budget for a single agent graph run (deep research can be slow). |

When `INGESTION_SERVICE_URL` is empty the knowledge builder chunks and embeds locally into pgvector. When it is set, the builder submits text to the external service, polls the job, then upserts the returned vectors into pgvector **without re-embedding**.

> **Consistency is enforced, not assumed.** The adapter pins `embedder_provider`, `embedding_model`, `embedding_dimensions`, and `embedding_pipeline` on every submit, and rejects any returned chunk whose vector width differs from `EMBEDDING_DIMENSIONS`. `late_chunking` requires Jina at **both** ingest and query time (`EMBEDDING_MODEL=jina-embeddings-v3`, `EMBEDDING_BASE_URL=https://api.jina.ai/v1`).

Verify connectivity, the key, and vector width with:

```bash
uv run python scripts/check_ingestion_service.py
```

## Observability

| Var | Default | Notes |
|---|---|---|
| `LANGSMITH_API_KEY` | `` | Enables LangSmith tracing when set. |
| `LANGSMITH_PROJECT` | `langgraph-agents` | — |
| `OTEL_EXPORTER_ENDPOINT` | `` | When set, OTel instrumentation is wired up (FastAPI auto-instrumentation). |

## MCP

| Var | Default | Notes |
|---|---|---|
| `MCP_SERVERS` | `[]` | JSON array of discriminated specs. See [`tools.md`](./tools.md#mcp) + [`architecture/mcp_integration.md`](./architecture/mcp_integration.md). |

Example (filesystem MCP via `npx`):

```bash
MCP_SERVERS=[{"name":"filesystem","transport":"stdio","command":"npx","args":["-y","@modelcontextprotocol/server-filesystem","mcp_workspace"]}]
```

## Prompts

| Var | Default | Notes |
|---|---|---|
| `PROMPT_ASSETS_DIR` | `app/modules/agent_orchestration/infrastructure/prompts` | Directory that contains intent subfolders. |
| `PROMPT_REGISTRY_PATH` | `app/core/config/prompt_registry.toml` | TOML mapping `intent → path`. |

Override both for Docker images that mount prompts as a volume.

## Agent limits & memory

| Var | Default | Notes |
|---|---|---|
| `AGENT_MAX_CONTEXT_TOKENS` | `12000` | Upper bound for per-subgraph prompt size (via `trim_messages`). Set `0` to disable trimming. |
| `SUPERVISOR_ROUTING_MAX_TOKENS` | `2048` | Tight cap for the routing step. |
| `MAX_TOOL_OUTPUT_CHARS` | `10000` | Truncates any single tool output before it re-enters the graph. Set `0` to disable. |
| `MEMORY_SUMMARIZATION_TRIGGER_MESSAGES` | `40` | If message count ≥ this, summarise. |
| `MEMORY_SUMMARIZATION_KEEP_RECENT_MESSAGES` | `12` | Keep the last N verbatim after summarising. |
| `MEMORY_SUMMARY_MAX_CHARS` | `4000` | Summary cap. |
| `MEMORY_SUMMARIZER_PROVIDER` | `` | If set, use a separate provider/model for memory summarisation (cheap model recommended). |
| `MEMORY_SUMMARIZER_MODEL_NAME` | `` | Required when `MEMORY_SUMMARIZER_PROVIDER` is set. |

## Celery

| Var | Default | Notes |
|---|---|---|
| `CELERY_BROKER_URL` | `redis://localhost:6379/1` | — |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/2` | — |

## Recompile-on-change

Some settings only take effect when the compiled LangGraph is rebuilt. The orchestrator caches a signature of:

- `TAVILY_API_KEY`
- `PGVECTOR_ENABLED`
- `OPENAI_API_KEY` (bool)
- `DEFAULT_LLM_PROVIDER`
- `DEFAULT_MODEL_NAME`
- `AGENT_MAX_CONTEXT_TOKENS`
- `SUPERVISOR_ROUTING_MAX_TOKENS`
- `MAX_TOOL_OUTPUT_CHARS`
- `MEMORY_SUMMARIZATION_*`
- `TRAVEL_PLANNER_ENABLED`
- `VALIDATOR_MODEL`, `RESEARCHER_MODEL`, `LOGISTICIAN_MODEL`
- `JINA_API_KEY` (bool), `JINA_DEEPSEARCH_MODEL`
- `INGESTION_SERVICE_URL` (bool)
- `TRAVEL_MOCK_APIS`
- `PLACES_PROVIDER`, `TRANSIT_PROVIDER`, `FLIGHTS_PROVIDER`, `HOTELS_PROVIDER`
- `NOMINATIM_BASE_URL`, `OSRM_BASE_URL`, `NOMINATIM_USER_AGENT`, `TRAVEL_PROVIDER_TIMEOUT_S`
- `MCP_SERVERS` (JSON-normalised)

When any of these change, the next request builds a fresh orchestrator with a new compiled graph. Other settings (log level, rate limits, CORS, etc.) apply immediately. MCP **tool bootstrap** is only performed at application startup — add/remove MCP servers requires an app restart.
