# Context Engine Demo

A chatbot for finding and getting access to enterprise data, built on **Redis Iris**. A side panel shows
every Redis call behind each answer, so you can see which piece of Iris did what.

| Iris piece | What it does here |
|---|---|
| **Context Retriever** | Turns the entity model (data products, access requests, incidents, support history, policies) into MCP tools the agent calls: filters, counts, text and vector search |
| **Agent Memory** | Remembers each user's work context. A custom extraction policy has the LLM pick a category and an expiry for every memory, and Redis expires it on time |
| **LangCache** | Answers repeated questions from a semantic cache with no model call |
| **Semantic routing** (RedisVL) | Blocks off-topic prompts, and picks which tools the model sees for each question |
| **Redis** | JSON profiles, LangGraph checkpoints, per-memory key TTLs, an audit stream |

Demo script and prompts: [domains/datagov/docs/demo_paths.md](domains/datagov/docs/demo_paths.md).

## Run it

You need uv, Node 18+, and a Redis Cloud database with Context Retriever, Agent Memory and LangCache enabled.
In Agent Memory, create the custom `context_event` memory type with the extraction prompt, set the extraction
cadence to 60 seconds and set the long-term TTL above 365 days.

```bash
make install            # Python and JS dependencies
cp .env.example .env    # fill in the credentials
make setup              # generate models and data, load Redis, seed memory and cache
make dev                # http://localhost:3040
```

`make setup` and `make reset` wipe the Redis database and the Agent Memory store before seeding, so point them
at ones you can lose. All people, data products and incidents are synthetic.

## How a chat turn works

`backend/app/chat.py` runs these steps in order and streams each one to the panel:

1. **Guardrail**: Redis semantic router. Off-topic or impersonation prompts stop here.
2. **Cache**: LangCache. A similar earlier question is answered without the model.
3. **Tool routing**: a second semantic router picks the tools the model gets, cutting prompt tokens.
4. **Memory**: write the user's message to the session, load the session and the user's long-term memories.
5. **Agent**: a LangGraph agent calls Context Retriever and the memory tools, then answers.
6. **Save**: store the reply in the session (switched off here so extraction only sees what the user said).

## Where Redis does the work, and where code does

Done in Redis: all data lookups (Context Retriever), vector search, the semantic cache, both routers, session and
long-term memory, conversation checkpoints, the signed-in user's profile (a JSON document), and memory expiry.
Each long-term memory is its own Redis hash, and the app sets that key's TTL to the memory's own window. Redis
then deletes the record and drops it from the search index when the window ends.

Done in code, because the services do not do it today:

- Applying the per-memory TTL. Agent Memory has one long-term TTL per store, so `native_ttl.py` sets each key's
  TTL on read. It writes to the service's own keys, so confirm that with Redis product before a pilot.
- Hiding resolved and superseded memories. An Agent Memory update changes text only, so a recovery arrives as a
  new `resolved` memory and `retention.py` hides the older active one.
- The retire and sweep tools, which call Agent Memory's delete and append to a Redis stream (`datagov:memory_audit`).

## Layout

```
backend/app/
  main.py                 FastAPI endpoints
  chat.py                 One chat turn (the six steps above)
  services.py             Clients for Context Retriever, Agent Memory, LangCache, the routers
  langgraph_agent.py      The agent, its tools and the Redis checkpointer
  trace.py                Compact payloads for the activity panel
  *_service.py            One thin client per Iris service
domains/datagov/
  schema.py               Entity model (source of truth for the Context Retriever tools)
  data_generator.py       Synthetic data written straight to Redis
  retention.py            Retention categories and the rules for hiding a memory
  native_ttl.py           Per-memory Redis key TTL
  memory_tools.py         Search, retire and sweep tools for the agent
  prompt.py, domain.py    Agent prompt, guardrails, tool routes, seeds, branding
frontend/src/             React chat UI and activity panel
scripts/                  Setup: generate models and data, create the surface, load, seed
tests/                    Offline tests (no Redis needed)
```

## Retention categories

| Category | Retention |
|---|---|
| data_incident | 7 days |
| access_request | 30 days |
| project_work | 90 days |
| migration_deprecation | 180 days |
| regulatory_audit | 365 days |
