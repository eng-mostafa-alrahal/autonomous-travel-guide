# Project Requirements — Autonomous Travel Guide

> Canonical requirements specification for the **Autonomous Travel Guide** system.
> Keywords **MUST**, **MUST NOT**, **SHOULD**, and **MAY** follow RFC 2119 semantics.
> Requirements marked ✅ are implemented; 🔜 marks planned work (see [Roadmap](#10-roadmap-requirements-planned)).

---

## 1. Project target

Build an **autonomous, multi-agent travel planning backend** on FastAPI + LangGraph that:

1. Collects a traveller's trip requirements conversationally (with human-in-the-loop questions).
2. Produces a **day-by-day itinerary** within the user's budget and trip length, composed from
   specialist agents (city expert, hotels, flights/logistics, food).
3. Maintains a **destination knowledge base** (pgvector) that is filled on demand by an
   autonomous **Knowledge Builder** (deep research → dedup → ingestion), auto-triggered when the
   planner encounters a destination with no KB coverage.
4. Remains a clean-architecture codebase: framework-agnostic domain, ports/adapters boundaries,
   fully testable without network or LLM keys.

**Non-goals (current version):** real booking transactions, a frontend/UI, multi-tenant
SaaS features. Specialists are search-then-summarize (no live booking APIs yet).

---

## 2. Scope

### In scope
- REST + SSE API for chat-driven trip planning (JWT-authenticated).
- Two LangGraph graphs (Planner, Knowledge Builder) composed in a travel master graph, feature-flagged by `TRAVEL_PLANNER_ENABLED`.
- Legacy generic supervisor graph preserved as a fallback mode.
- Deep research via Jina DeepSearch; ingestion via local pgvector or the external RAG Document Processor service.
- Human-in-the-loop interrupts for requirement gathering and KB-build approval.
- Postgres persistence (users, sessions, `kb_destinations`, LangGraph checkpoints, pgvector).

### Out of scope (current version)
- Real hotel/flight/restaurant booking integrations.
- Frontend/UI (backend-only; SSE contract is the interface).
- Multi-tenant auth/orgs/quotas/billing.
- Production hardening of file/URL ingestion paths (text ingestion only).

---

## 3. Functional requirements

### 3.1 Travel Planner graph ✅

| ID | Requirement |
|----|-------------|
| FR-P1 | The planner MUST extract `TripRequirements` from the conversation using structured LLM output (`collect_requirements` node). |
| FR-P2 | Required slots are **destination** (city and/or country), **`num_days`**, and **`budget`** (free text, e.g. `"$1500"` or `"mid-range"`). Optional slots: `start_date`, `party_size`, `interests`. |
| FR-P3 | While required slots are missing, the planner MUST pause with a LangGraph `interrupt()` (`ask_requirements`), ask the user only for the missing slots, and loop back to extraction on resume. |
| FR-P4 | Once requirements are complete, a deterministic `delegate` node MUST walk a specialist queue so **every section is produced exactly once**: `city_expert`, `hotels`, `flights_logistics`, `food`. Delegation MUST NOT rely on per-step LLM routing. |
| FR-P5 | `city_expert` MUST query a **destination-scoped pgvector retriever** (`build_destination_retriever(destination_key)`) and fall back to `web_search` when retrieval is empty or the KB is unavailable. |
| FR-P6 | On a KB miss, `city_expert` MUST set `kb_miss = true` and a canonical `destination_key` in state so the master graph can trigger the Knowledge Builder. |
| FR-P7 | `hotels`, `flights_logistics`, and `food` are search-then-summarize specialists sharing one parameterized prompt (`travel_specialist`, parameter `role`). `flights_logistics` also covers local transport and day-routing, and MUST use `LOGISTICIAN_MODEL` when set. |
| FR-P8 | `synthesize_itinerary` MUST compose the final day-by-day plan from all `specialist_outputs`, respecting budget and `num_days`, and write it to `itinerary` and as the final `AIMessage`. |
| FR-P9 | Specialist results MUST merge into `specialist_outputs` via a state reducer (safe for future parallel execution). |

### 3.2 Knowledge Builder graph ✅

| ID | Requirement |
|----|-------------|
| FR-K1 | Before any deep research, `confirm_build` MUST `interrupt()` with a warning that research may take a while, and wait for `approve`/`reject` via the resume endpoint. |
| FR-K2 | On approval, `kb_destinations.status` MUST be set to `building`; on rejection the builder MUST end **without writing anything** to the KB, and the planner falls back to web search. |
| FR-K3 | `deep_research` MUST compose a research brief from `city`/`country`/`topics` and call the Jina DeepSearch client (async, honoring `JINA_DEEPSEARCH_TIMEOUT_S` and `JINA_DEEPSEARCH_REASONING_EFFORT`), storing raw text + source URLs in state. |
| FR-K4 | `deduplicate` MUST use structured LLM output (`PreparedKnowledge`) to remove redundant content and organize research into topic-tagged segments; it uses `VALIDATOR_MODEL` when set. |
| FR-K5 | `ingest` MUST send segments through the `IIngestionService` port. On success it marks `kb_destinations.status = ready` with `doc_count`; on failure it marks `status = failed`. |
| FR-K6 | `notify_complete` MUST emit an `AIMessage` telling the user the destination KB is ready. |
| FR-K7 | Every ingested chunk MUST carry the metadata contract `{destination_key, city, country, topic, source}` so the city expert's filtered retriever can find it. |

### 3.3 Master graph & auto-trigger ✅

| ID | Requirement |
|----|-------------|
| FR-M1 | When `TRAVEL_PLANNER_ENABLED=true`, the master graph MUST be `travel_root → planner → (kb miss?) → knowledge_builder → after_build → planner (re-plan) → error_handler → END`. When false, the legacy supervisor graph MUST run unchanged. |
| FR-M2 | `after_build` MUST set `kb_build_attempted = true` and clear `kb_miss` so one run can never trigger a second build (loop guard), whether the build was approved or rejected. |
| FR-M3 | Graph selection MUST happen at compile time in `MainGraphOrchestrator`; both modes share the same checkpointer, resume endpoint, and error handler. |

### 3.4 API surface ✅

| ID | Requirement |
|----|-------------|
| FR-A1 | All routes are prefixed `/api/v1`. All routes except `/health` and `/auth/*` MUST require `Authorization: Bearer <access_token>`. |
| FR-A2 | `POST /chat/` runs a full graph turn and returns the result; `POST /chat/stream` streams `AgentEvent`s over SSE (`stream_detail` controls verbosity). |
| FR-A3 | When a graph interrupts (requirements question or KB-build confirmation), the API MUST return `interrupted: true` plus the interrupt payload; the client resumes via `POST /runs/{thread_id}/resume` with `{"action": "approve"|"reject", "feedback": "..."}` . `GET /runs/{thread_id}/state` exposes the paused state. Interrupt payloads MUST carry a `kind` (`requirements` \| `kb_build`) so clients can render the right prompt. |
| FR-A4 | Auth endpoints MUST provide register/login/refresh/me with access + refresh JWT rotation. User routes MUST enforce self-access (403 otherwise); session routes MUST enforce ownership. |
| FR-A5 | Every response MUST carry `x-request-id` (echoed or generated) and `x-process-time-ms`. |
| FR-A6 | Conversation state MUST persist per `session_id` (LangGraph thread id) in the Postgres checkpointer so multi-turn planning and resumes survive restarts. |

### 3.5 Progress streaming ✅

| ID | Requirement |
|----|-------------|
| FR-S1 | Graph nodes MUST attach a coarse `phase` (`requirements`, `planning`, `knowledge_build`, `itinerary`, `done`) and a user-facing `phase_status` line to their state updates. Phase constants and status builders live in the **domain** layer (`domain/phases.py`, no framework imports). |
| FR-S2 | Because LangGraph publishes a node's updates only after it returns, a node MUST announce the work that comes **next**, so a status appears before the slow step it describes rather than after it. |
| FR-S3 | `stream_detail=phases` MUST emit `{"phase", "status"}` progress chunks plus the same content chunks as `content` mode. Consecutive identical progress lines MUST be suppressed. |
| FR-S4 | `content` and `full` output MUST be unaffected by progress reporting (no new or duplicated chunks). |
| FR-S5 | Progress originates inside subgraphs, so the orchestrator MUST stream with `subgraphs=True`; each `AgentEvent` carries a `namespace` (enclosing subgraph nodes, empty at master level) so content is only taken from master-level events and never duplicated. |
| FR-S6 | `status` text is presentation prose and MAY change between releases; clients MUST NOT parse it. The legacy supervisor mode emits no phases, so `phases` degrades to `content` there. |

### 3.6 Ingestion service integration ✅

| ID | Requirement |
|----|-------------|
| FR-I1 | Ingestion MUST go through the `IIngestionService` port. `factory.build_ingestion_service()` selects the adapter: `HttpIngestionAdapter` when `INGESTION_SERVICE_URL` is set, otherwise `LocalPgVectorIngestionAdapter`. |
| FR-I2 | The local adapter MUST chunk + embed segments and `add_documents()` into pgvector with the metadata contract (FR-K7). |
| FR-I3 | The HTTP adapter MUST implement the RAG Document Processor contract: `POST /api/v1/ingest/text` → poll `GET /api/v1/jobs/{id}` every `INGESTION_POLL_INTERVAL_S` (bounded by `INGESTION_POLL_TIMEOUT_S`) → `GET /api/v1/jobs/{id}/results` (retrying on `409 job_results_not_ready`) → upsert via `PGVector.add_embeddings` **without re-embedding**. Auth: `X-API-Key` header. |
| FR-I4 | Each knowledge segment MUST be submitted as its own job (per-topic metadata survives), with at most `INGESTION_MAX_CONCURRENCY` jobs in flight. |
| FR-I5 | **Embedding consistency (critical):** the adapter MUST pin `embedder_provider`, `embedding_model`, and `embedding_dimensions` on every submit to match query-time settings (`text-embedding-3-small`, 1536 dims), MUST always request the `chunk_then_embed` pipeline (the service's `late_chunking` is Jina-only and incompatible), and MUST raise if any returned vector width differs from `EMBEDDING_DIMENSIONS`. Mismatched vectors would be permanently unsearchable. |
| FR-I6 | Documented service errors (`401`, `404 job_not_found`, `409 job_results_not_ready`, `413`, `415`, `422 invalid_embedding_dimensions`, job `failed` with `error_message`) MUST surface as clear failures that set `kb_destinations.status = failed`. |
| FR-I7 | The integration MUST be smoke-testable end to end without pgvector writes: `uv run python scripts/check_ingestion_service.py`. |

---

## 4. Non-functional requirements

### 4.1 Architecture (best practices — enforced)

| ID | Requirement |
|----|-------------|
| NFR-AR1 | **Dependency rule:** `api → modules(application/domain) ← infrastructure`; domain code MUST NOT import LangChain/LangGraph/FastAPI/SQLAlchemy. Routing rules and schemas in `domain/` are pure functions/Pydantic. |
| NFR-AR2 | External systems MUST be reached only through **ports** (`application/ports/…`) with adapters in `infrastructure/…` (e.g. `IDeepResearchClient` ← Jina client, `IIngestionService` ← local/HTTP adapters, `IPromptProvider` ← `FilePromptRegistry`). |
| NFR-AR3 | LangGraph/LangChain types are permitted **only** inside `infrastructure/langgraph_engine/`; the orchestrator's public surface returns pure DTOs (`AgentRunResult`, `AgentEvent`, `AgentStateSnapshot`). |
| NFR-AR4 | All prompts MUST live as Jinja assets registered in `prompt_registry.toml` (no inline prompt strings in nodes). Current intents: `travel_requirements`, `travel_specialist`, `travel_city_expert`, `travel_itinerary`, `KNOWLEDGE_DEDUP`. |
| NFR-AR5 | Graph builders MUST return **uncompiled** `StateGraph`s; compilation + checkpointer wiring happens once in `MainGraphOrchestrator`. Per-role LLM overrides (`VALIDATOR_MODEL`, `RESEARCHER_MODEL`, `LOGISTICIAN_MODEL`) fall back to `DEFAULT_MODEL_NAME` when blank. |
| NFR-AR6 | Database writes MUST go through the Unit-of-Work/repository pattern (`SqlAlchemyUnitOfWork`); schema changes require Alembic migrations. |

### 4.2 Reliability & error handling

| ID | Requirement |
|----|-------------|
| NFR-R1 | A single graph run MUST be bounded by `AGENT_GRAPH_TIMEOUT_S` (default 900 s — deep research is slow). |
| NFR-R2 | Every unhandled node error MUST flow to the shared `error_handler` node and surface as a structured error, never a hung run. |
| NFR-R3 | KB builds MUST be idempotent per destination: `kb_destinations` status (`none|building|ready|failed`) gates re-builds; a failed ingest leaves the row `failed`, not `ready`. |
| NFR-R4 | HITL interrupts MUST survive process restarts (Postgres checkpointer); resuming a non-interrupted thread MUST return a clear `GraphNotInterruptedError`. |
| NFR-R5 | LLM context MUST be bounded: `AGENT_MAX_CONTEXT_TOKENS` trimming, `MAX_TOOL_OUTPUT_CHARS` tool-output caps, and message summarization after `MEMORY_SUMMARIZATION_TRIGGER_MESSAGES` messages (keep `MEMORY_SUMMARIZATION_KEEP_RECENT_MESSAGES` recent). |

### 4.3 Security

| ID | Requirement |
|----|-------------|
| NFR-S1 | JWT auth (HS256) with short-lived access tokens (default 30 min) + refresh rotation (default 7 days). `JWT_SECRET_KEY` MUST be overridden in production. |
| NFR-S2 | Rate limiting MUST apply per client (`RATE_LIMIT_PER_MINUTE`, default 60). |
| NFR-S3 | Secrets (OpenAI, Tavily, Jina, ingestion API key, DB/Redis credentials) MUST come from environment/`.env` and MUST NOT be committed. ⚠ Known debt: a historical `.env` with live keys was committed — rotate those keys and purge git history. |
| NFR-S4 | Outbound service auth: Jina via `Authorization: Bearer`, RAG Document Processor via `X-API-Key`. |
| NFR-S5 | Users can only read/modify their own user and session resources (self-access checks, 403 on violation). |

### 4.4 Observability

| ID | Requirement |
|----|-------------|
| NFR-O1 | Every request MUST be traceable by `x-request-id` propagated into graph logs (`request_context.get_request_id()`). |
| NFR-O2 | Graph execution MUST log per-event timing; steps slower than 3 s MUST log a `slow_step` warning. |
| NFR-O3 | LangSmith tracing MUST be supported via `LANGSMITH_API_KEY`/`LANGSMITH_PROJECT`; OTEL export via `OTEL_EXPORTER_ENDPOINT`. |

### 4.5 Testing

| ID | Requirement |
|----|-------------|
| NFR-T1 | Unit tests MUST run **without network access or LLM keys** (fake LLMs, mocked HTTP transports, stub retrievers). |
| NFR-T2 | Required coverage: routing rules, requirement extraction/slot logic, specialist nodes, knowledge-builder nodes, HTTP ingestion adapter (mocked `httpx`), and an e2e master-graph test covering KB-miss → HITL confirm → build → re-plan. |
| NFR-T3 | Graph builders MUST have compile smoke tests (graphs compile with stub dependencies). |

### 4.6 Documentation (project rule)

| ID | Requirement |
|----|-------------|
| NFR-D1 | Every behavior/config/schema change MUST update the matching page under `docs/` (see the [docs index](./README.md)). |
| NFR-D2 | The two graph docs (`travel-planner.md`, `knowledge-builder.md`) MUST stay in sync with node names, state fields, and prompt intents. |
| NFR-D3 | New environment variables MUST be added to `settings.py`, `.env.example`, and `configuration.md` together. |

---

## 5. Data requirements

| ID | Requirement |
|----|-------------|
| DR-1 | `kb_destinations` table: canonical `destination_key`, `city`, `country`, `status ∈ {none, building, ready, failed}`, `doc_count`, `indexed_at`; upserts via `KBStatusService` (`mark_building`/`mark_ready`/`mark_failed`/`get_status`). |
| DR-2 | Vector store: pgvector collection `PGVECTOR_COLLECTION` (default `knowledge_base`), embeddings `text-embedding-3-small` @ **1536 dimensions** — this pair MUST match between ingest time and query time. |
| DR-3 | Chunk metadata contract: `{destination_key, city, country, topic, source}` on every stored vector. |
| DR-4 | LangGraph checkpoints persist in Postgres keyed by thread id = `session_id`. |
| DR-5 | Users/sessions in Postgres via SQLAlchemy models + Alembic migrations. |

---

## 6. State contracts (graph state fields)

### `TravelPlannerState` (extends `BaseAgentState`: `messages`, `session_id`, `user_id`, `error`, `human_feedback`)

| Field | Type | Purpose |
|-------|------|---------|
| `phase` / `phase_status` | `str \| None` | Progress phase + user-facing status line. |
| `requirements` | `dict` | Latest extracted `TripRequirements`. |
| `requirements_complete` | `bool` | All required slots present. |
| `missing_slots` | `list[str]` | Slots still needed. |
| `pending_specialists` | `list[str]` | Delegation queue. |
| `next_specialist` | `str \| None` | Current routing target. |
| `specialist_outputs` | `dict[str, str]` | Per-specialist results (reducer-merged). |
| `itinerary` | `str \| None` | Final plan (markdown). |
| `destination_key` / `city` / `country` | `str` | Cross-graph handoff to the Knowledge Builder. |
| `kb_miss` / `kb_build_attempted` | `bool` | Auto-trigger + loop guard. |

### `KnowledgeBuilderState`

| Field | Type | Purpose |
|-------|------|---------|
| `destination_key`, `city`, `country`, `topics` | — | Build target + research topics. |
| `approved` | `bool \| None` | HITL decision. |
| `raw_research`, `research_sources` | — | Jina output + citations. |
| `prepared_segments` | `list[dict]` | `[{topic, content}]` after dedup. |
| `doc_count` | `int` | Vectors stored. |
| `phase` / `phase_status` | `str \| None` | Progress phase + user-facing status line. |

---

## 7. Configuration requirements (environment variables)

All settings load from `.env` (which **wins over process env** — deliberate, so repo config beats stale IDE variables). `extra="ignore"`: unknown keys are silently dropped, so new keys MUST be declared in `settings.py`.

| Group | Keys (defaults) |
|-------|-----------------|
| App/server | `APP_NAME`, `ENVIRONMENT` (`development`), `DEBUG`, `LOG_LEVEL`, `HOST`, `PORT` (8000), `WORKERS` |
| Database | `DATABASE_URL` or `DATABASE_HOST/PORT/USER/PASSWORD/NAME`; pool: `DB_POOL_SIZE` (20), `DB_MAX_OVERFLOW` (10), `DB_POOL_RECYCLE` (3600) |
| Redis | `REDIS_URL` or `REDIS_HOST/PORT/USER_NAME/PASSWORD/DB/SSL` |
| Auth | `JWT_SECRET_KEY` ⚠, `JWT_ALGORITHM` (HS256), `ACCESS_TOKEN_EXPIRE_MINUTES` (30), `REFRESH_TOKEN_EXPIRE_DAYS` (7), `RATE_LIMIT_PER_MINUTE` (60) |
| LLM | `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `DEFAULT_LLM_PROVIDER` (openai), `DEFAULT_MODEL_NAME` |
| RAG | `TAVILY_API_KEY`, `EMBEDDING_MODEL` (text-embedding-3-small), `EMBEDDING_DIMENSIONS` (1536), `PGVECTOR_COLLECTION` (knowledge_base), `PGVECTOR_ENABLED` (false) |
| Travel mode | `TRAVEL_PLANNER_ENABLED` (false), `VALIDATOR_MODEL`, `RESEARCHER_MODEL`, `LOGISTICIAN_MODEL` (blank → default model) |
| Jina | `JINA_API_KEY`, `JINA_DEEPSEARCH_MODEL` (jina-deepsearch-v1), `JINA_DEEPSEARCH_TIMEOUT_S` (300), `JINA_DEEPSEARCH_REASONING_EFFORT` (medium) |
| Ingestion | `INGESTION_SERVICE_URL` (empty → local fallback), `INGESTION_SERVICE_API_KEY`, `INGESTION_SERVICE_TIMEOUT_S` (60), `INGESTION_POLL_TIMEOUT_S` (300), `INGESTION_POLL_INTERVAL_S` (2.0), `INGESTION_EMBEDDER_PROVIDER` (openai), `INGESTION_MACRO_SPLITTER` (recursive), `INGESTION_MAX_CONCURRENCY` (4) |
| Run budget | `AGENT_GRAPH_TIMEOUT_S` (900) |
| Context/memory | `AGENT_MAX_CONTEXT_TOKENS` (12000), `SUPERVISOR_ROUTING_MAX_TOKENS` (2048), `MAX_TOOL_OUTPUT_CHARS` (10000), `MEMORY_SUMMARIZATION_*`, `MEMORY_SUMMARIZER_PROVIDER/MODEL_NAME` |
| Observability | `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `OTEL_EXPORTER_ENDPOINT` |
| Other | `MCP_SERVERS` (JSON), `PROMPT_ASSETS_DIR`, `PROMPT_REGISTRY_PATH`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` |

Full reference with explanations: [`configuration.md`](./configuration.md).

---

## 8. External dependencies

| System | Purpose | Failure behavior |
|--------|---------|------------------|
| OpenAI / Anthropic / Gemini | Chat LLMs + embeddings | Run fails via error handler; per-role model overrides optional. |
| Tavily | `web_search` tool (specialist + KB fallback) | Specialists degrade; city expert has no fallback if both KB and web are unavailable. |
| Jina DeepSearch | Autonomous deep research (OpenAI-compatible `/v1/chat/completions`) | Build fails → `kb_destinations.status = failed`; planner falls back to web. |
| RAG Document Processor (Cloud Run) | Chunking + embedding as a service | Optional — local pgvector adapter is the default fallback. |
| Postgres (+ pgvector) | Relational data, checkpoints, vectors | Hard dependency. `PGVECTOR_ENABLED` gates vector features. |
| Redis | Celery broker/back end, future caching | Not on the planning hot path. |

---

## 9. Acceptance criteria (implemented behavior)

1. With `TRAVEL_PLANNER_ENABLED=true`, `POST /api/v1/chat/` with "Plan me 4 days in Kyoto, $1500, I love food and history" either returns a markdown itinerary or interrupts asking only for missing required slots.
2. A destination absent from `kb_destinations` causes exactly one KB-build confirmation interrupt; `approve` runs research → dedup → ingest and re-plans with KB data; `reject` re-plans using web search and writes nothing.
3. All vectors stored for a destination carry the full metadata contract and are retrievable by the city expert's filtered retriever.
4. `pytest tests/unit` passes offline (no keys, no network).
5. With `TRAVEL_PLANNER_ENABLED=false`, the legacy supervisor behaves exactly as before.
6. `stream_detail=phases` reports the run as it happens (start → specialist announcements → knowledge build → itinerary), each line arriving before the step it describes, while `content` and `full` streams are byte-identical to before progress reporting existed.
7. `scripts/check_ingestion_service.py` completes a text-ingest job round-trip against the live service without touching pgvector.

---

## 10. Roadmap requirements (planned) 🔜

Tracked as Stages 5–10 in the active plan; summarized here for completeness.

| Stage | Requirement summary |
|-------|--------------------|
| ~~5 — Phase SSE~~ | ✅ **Done** — see §3.5. |
| 6 — Structured outputs | Specialists return validated Pydantic objects (`POI` with lat/lng/category/duration, `HotelOption`, `FlightOption`, `ItineraryDay`) instead of free text. |
| 7 — Spatial clustering | Deterministic (non-LLM) haversine day-clustering of POIs anchored on the chosen hotel, feeding the itinerary prompt. |
| 8 — Parallel specialists | Specialists fan out concurrently via LangGraph `Send` with a join node; the sequential queue remains switchable for CI determinism. |
| 9 — Persistence & revision | Itineraries persist in a new table (Alembic migration); follow-up revision turns re-run only affected specialists/days. |
| 10 — Real APIs | Flights/hotels/places adapters (e.g. Amadeus, Booking, Google Places/OSRM) behind the same node interfaces; web-search mode kept for CI/fallback. |

---

## 11. Known technical debt

- Committed historical `.env` with live secrets — rotate keys, purge history (NFR-S3).
- Typo `"Aautonomous"` in the health endpoint's `app` name.
- Itinerary exists only in graph state (addressed by Stage 9).
