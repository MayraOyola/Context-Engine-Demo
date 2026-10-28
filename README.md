# Context Engine Demo

Enterprise data-discovery chatbot built on Redis Iris. A "behind the scenes" panel shows every
call: semantic routing, session memory, long-term memory, LangCache, Context Retriever (MCP) tools, and
memory writes with per-item expiry.

Walkthrough and talking points: [domains/datagov/docs/demo_paths.md](domains/datagov/docs/demo_paths.md).

## Redis Cloud pieces you need

| Service | What you need in `.env` |
|---|---|
| Redis database | host, port, password |
| Context Retriever | admin key |
| Agent Memory | base URL, store ID, API key. Set the long-term TTL above 730 days |
| LangCache | host, cache ID, API key |
| OpenAI | API key |

## Run it

```bash
make install            # Python + JS dependencies (needs uv and Node 18+)
cp .env.example .env    # fill in credentials
make setup              # generate models + data, load Redis, seed memory + cache
make dev                # http://localhost:3040
```

`make setup` deletes every non-memory key in the Redis database and purges all long-term memories in the
Agent Memory store before seeding. Point it at a database and store you can wipe. `make reset` repeats the
load and seed without regenerating models.

## Layout

```
backend/app/            FastAPI + LangGraph agent, SSE activity stream, Iris service clients
domains/datagov/
  schema.py             Employee, DataProduct, AccessRequest, QualityIncident, SupportInteraction, PolicyDoc
  data_generator.py     Synthetic data written straight to Redis
  retention.py          Reads the condition_event attributes Agent Memory extracts; enforces each memory's window
  memory_tools.py       retire / sweep tools (real Agent Memory deletes with an audit entry)
  prompt.py, domain.py  Agent prompt, guardrails, seeds, branding
frontend/               React chat UI and activity panel
tests/test_datagov_domain.pyOffline tests for the retention logic (fake Agent Memory client)
```

## Retention tiers

Agent Memory's own extraction creates a `context_event` memory (a custom memory type defined on the service,
with its extraction prompt) carrying a category, `retention_days`, `expires_on`, likely follow-ups and `status`.
Agent Memory has one long-term TTL per service, so this project sets each memory's own Redis key TTL, hides
expired or resolved memories at read time, and records deletes in the Redis stream `datagov:memory_audit`.
Set the service's extraction cadence to 60 seconds.

| Category | Retention |
|---|---|
| data_incident | 7 days |
| access_request | 30 days |
| project_work | 90 days |
| migration_deprecation | 180 days |
| regulatory_audit | 365 days |

All people, data products and incidents are synthetic.
