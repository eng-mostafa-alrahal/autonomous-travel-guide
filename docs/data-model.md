# Data Model

This project uses **PostgreSQL** through SQLAlchemy 2.x async, plus LangGraph's own Postgres checkpointer for conversation state.

## Entity-relationship diagram

```mermaid
erDiagram
    USERS ||--o{ SESSIONS : "has many"
    USERS ||--o{ ITINERARIES : "has many"
    SESSIONS ||--o{ ITINERARIES : "has many"
    USERS {
      uuid id PK "UUIDv7"
      string name "max 120"
      string email UK "max 255"
      string hashed_password
      bool is_active
      timestamptz created_at
      timestamptz updated_at
    }
    SESSIONS {
      uuid id PK "UUIDv7, == LangGraph thread_id"
      uuid user_id FK "→ USERS.id (cascade delete)"
      string title "max 255, default 'New Chat'"
      timestamptz created_at
      timestamptz updated_at
    }
    KB_DESTINATIONS {
      uuid id PK "UUIDv7"
      string destination_key UK "normalized 'city|country'"
      string city "nullable"
      string country "nullable"
      string status "none|building|ready|failed"
      int doc_count
      text error_message "nullable"
      timestamptz indexed_at "nullable"
      timestamptz created_at
      timestamptz updated_at
    }
    ITINERARIES {
      uuid id PK "UUIDv7"
      uuid session_id FK "→ SESSIONS.id (cascade delete)"
      uuid user_id FK "→ USERS.id (cascade delete)"
      text content "rendered markdown plan"
      jsonb requirements "TripRequirements dump"
      jsonb clusters "per-day DayCluster dumps"
      int num_days "nullable"
      string destination_label "max 255, nullable"
      timestamptz created_at
      timestamptz updated_at
    }
```

## Tables

### `users` (`app/infrastructure/database/postgres/models/user_model.py`)

| Column | Type | Constraints |
|---|---|---|
| `id` | `UUID` | PK, default `uuid7()` |
| `name` | `VARCHAR(120)` | not null |
| `email` | `VARCHAR(255)` | unique, indexed, not null |
| `hashed_password` | `VARCHAR(255)` | not null, bcrypt via passlib |
| `is_active` | `BOOLEAN` | not null, default `true` |
| `created_at` | `TIMESTAMPTZ` | not null, default `now(UTC)` |
| `updated_at` | `TIMESTAMPTZ` | not null, auto-updated |

Relationship: `sessions = relationship("SessionORM", back_populates="user", cascade="all, delete-orphan")`.

### `sessions` (`app/infrastructure/database/postgres/models/session_model.py`)

| Column | Type | Constraints |
|---|---|---|
| `id` | `UUID` | PK, default `uuid7()` |
| `user_id` | `UUID` | FK → `users.id`, `ON DELETE CASCADE`, indexed |
| `title` | `VARCHAR(255)` | not null, default `"New Chat"` |
| `created_at` | `TIMESTAMPTZ` | not null |
| `updated_at` | `TIMESTAMPTZ` | not null, auto-updated |

**The session `id` doubles as the LangGraph `thread_id`.** This is the glue between the REST surface and the checkpointer — deleting a session does *not* delete the thread's checkpoint rows (they're harmless orphans; prune manually if desired).

### `kb_destinations` (`app/infrastructure/database/postgres/models/kb_destination_model.py`)

Tracks which destinations have an indexed knowledge base. Shared by the travel planner (to detect a KB miss) and the knowledge builder (to mark progress).

| Column | Type | Constraints |
|---|---|---|
| `id` | `UUID` | PK, default `uuid7()` |
| `destination_key` | `VARCHAR(512)` | unique, indexed — normalized `"city\|country"` (lowercased, trimmed) |
| `city` | `VARCHAR(255)` | nullable |
| `country` | `VARCHAR(255)` | nullable |
| `status` | `VARCHAR(32)` | not null, default `"none"` — one of `none` / `building` / `ready` / `failed` |
| `doc_count` | `INTEGER` | not null, default `0` |
| `error_message` | `TEXT` | nullable |
| `indexed_at` | `TIMESTAMPTZ` | nullable |
| `created_at` | `TIMESTAMPTZ` | not null |
| `updated_at` | `TIMESTAMPTZ` | not null, auto-updated |

The canonical key is built by `build_destination_key()` in `app/modules/agent_orchestration/domain/kb_destination.py`.

### `itineraries` (`app/infrastructure/database/postgres/models/itinerary_model.py`)

A persisted travel plan, written (best-effort) when a travel-planner run finishes (Stage 9). Each completed run appends a new row, so the table doubles as a per-session version history; revision turns are intentionally deferred, but the stored `requirements` + `clusters` are the inputs a revision diff will compare against.

| Column | Type | Constraints |
|---|---|---|
| `id` | `UUID` | PK, default `uuid7()` |
| `session_id` | `UUID` | FK → `sessions.id`, `ON DELETE CASCADE`, indexed |
| `user_id` | `UUID` | FK → `users.id`, `ON DELETE CASCADE`, indexed |
| `content` | `TEXT` | not null — rendered day-by-day markdown |
| `requirements` | `JSONB` | not null, default `{}` — `TripRequirements` dump that produced this plan |
| `clusters` | `JSONB` | not null, default `[]` — per-day `DayCluster` dumps (stops + travel legs) |
| `num_days` | `INTEGER` | nullable |
| `destination_label` | `VARCHAR(255)` | nullable |
| `created_at` | `TIMESTAMPTZ` | not null |
| `updated_at` | `TIMESTAMPTZ` | not null, auto-updated |

The write path is `ItineraryService.save_completed()` (`modules/agent_orchestration/application/use_cases/itinerary_service.py`), called from `MainGraphOrchestrator` after a successful, non-interrupted run. Persistence failures are logged and swallowed so a DB hiccup never fails an otherwise-successful turn. Reads: `get_latest_for_session` / `list_for_session` on `IItineraryRepository` — no HTTP endpoint yet (the itinerary already streams back in the chat reply/SSE).

### ID strategy

All primary keys are **UUIDv7** (see `app/shared/uuid_utils.py`). UUIDv7s are time-sortable, which keeps B-tree indexes compact and list ordering intuitive ("newest first" === `ORDER BY id DESC`).

## Migrations

`alembic/` manages schema changes.

- `alembic/env.py` wires a sync psycopg URL (via `settings.get_database_sync_url()`) so Alembic doesn't need async drivers.
- `alembic/versions/31121b69cc8e_initial_schema.py` is the initial migration (creates `users` + `sessions`).
- `alembic/versions/a1b2c3d4e5f6_add_kb_destinations.py` adds the `kb_destinations` table.
- `alembic/versions/b7c8d9e0f1a2_add_itineraries.py` adds the `itineraries` table.

Commands:

```bash
alembic upgrade head              # apply all pending migrations
alembic revision --autogenerate -m "add column foo"
alembic downgrade -1              # rollback one
```

## Unit of Work

Database access uses a `SqlAlchemyUnitOfWork` (in `app/infrastructure/database/postgres/unit_of_work.py`) that exposes repositories (`users`, `sessions`, `kb_destinations`, `itineraries`) and commits/rolls-back atomically. Use cases always interact through the UoW — they never construct repositories directly.

```python
async with uow:
    user = await uow.users.get_by_email(email)
    session = await uow.sessions.create(user_id=user.id, title="…")
    await uow.commit()
```

## Domain ↔ ORM mapping

Domain entities are pure dataclasses/Pydantic under `modules/<feature>/domain/*`. Repositories map ORM rows → domain objects so upper layers never see SQLAlchemy types.

- `UserORM` ↔ `User`  (`modules/users/domain/user.py`)
- `SessionORM` ↔ `Session`  (`modules/sessions/domain/session.py`)
- `KBDestinationORM` ↔ `KBDestination`  (`modules/agent_orchestration/domain/kb_destination.py`)
- `ItineraryORM` ↔ `Itinerary`  (`modules/agent_orchestration/domain/itinerary.py`)

## pgvector (optional)

When `PGVECTOR_ENABLED=true`, `app/infrastructure/database/postgres/vector_store.py` builds a LangChain `PGVector` retriever using:

- `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS`
- `PGVECTOR_COLLECTION`
- `OPENAI_API_KEY` (the retriever uses OpenAI embeddings by default)

Requires the `pgvector` extension installed in the database (the `pgvector/pgvector:pg16` image used by `docker-compose.yml` already ships with it). The collection tables are auto-created by `langchain-postgres`.

## LangGraph checkpointer

LangGraph persists every super-step of every run using `PostgresSaver` from `langgraph-checkpoint-postgres`.

- Initialised during FastAPI `lifespan` (`init_postgres_checkpoint_saver()` in `app/modules/agent_orchestration/infrastructure/langgraph_engine/memory/postgres_saver.py`).
- Uses the **same Postgres database** as the app (sync URL).
- Schema is auto-provisioned on first use (`setup()` is called internally; `ensure_checkpointer_ready()` is idempotent).
- Rows are keyed by `thread_id` — which we set to `session_id`.

### What the checkpointer stores

For every step of a run:

- The full `messages` list (as serialised LangChain `BaseMessage` objects).
- The `SupervisorState` fields (`session_id`, `user_id`, `next_agent`, `delegation_reasoning`, `error`, `human_feedback`).
- The `ResearcherState.retrieved_context` when inside that subgraph.
- The "next" node(s) and any pending interrupts (the basis for HITL resume).

### Reading state

- `orchestrator.get_state(thread_id)` → `AgentStateSnapshot`
- `orchestrator.resume(thread_id, action, feedback?)` — resumes from the last checkpoint
- `orchestrator.invoke(message, session_id, user_id)` — appends a new user message and continues

### Cleanup

There is no automatic retention policy. Options:

1. Run a periodic job that deletes rows whose `thread_id` no longer matches a row in `sessions`.
2. Cap storage by pruning rows older than N days.
3. Leave them — the footprint per run is small and the tables are B-tree-indexed.

## Redis

Redis is used for:

- **Rate limiting** — slowapi keys.
- **Celery** — `CELERY_BROKER_URL` (broker) and `CELERY_RESULT_BACKEND` (results).
- **Ad-hoc caching** — surface in `app/infrastructure/cache/redis_manager.py`.

No app-level data is authoritative in Redis — it's safe to flush.
