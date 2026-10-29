# Demo paths

Run `make reset` first (dates in the seed memories are relative to today). Switch users with the
**Signed in as** picker. Open the **Redis Iris** panel to see every Redis call as it happens.

| Prompt (as Priya Nair unless noted) | What it shows | Redis Iris piece |
|---|---|---|
| `Is it safe to run my credit model on today's data?` | The question never names the incident or the products. Memory knows her model uses Company Fundamentals and Credit Default Probability; Context Retriever returns each product's current incidents. | Agent Memory + Context Retriever |
| `What's the status of my data access requests?` | Filters access requests by the signed-in user. | Context Retriever (`filter_*`) |
| `What do analysts usually ask after a data quality incident?` | Semantic search over past support interactions. | Context Retriever (vector search) |
| `Are we allowed to resell sentiment data?` | Semantic search over policy documents. | Context Retriever (vector search) |
| `I've been seeing duplicate rows in Credit Default Probability since Monday.` | Nothing visible in the reply. Agent Memory's extraction creates a `context_event` with a category, a retention window and an expiry date. Watch the **Agent Memory EXTRACTION** row. | Agent Memory (custom extraction) |
| **Fast-forward expiry** button | Sets the memory's Redis key TTL to ~10 seconds. Redis deletes the record and its index entry. | Redis key expiry |
| `Please clean up anything expired in my profile.` | Deletes memories past their window and writes an audit entry. | Agent Memory (delete) + Redis stream |
| Switch to Daniel Okafor, then `What do you know about me?` | Only Daniel's memories come back, nothing of Priya's. | Agent Memory (per-user isolation) |
| `How can I request access to a restricted data product?`, then ask it again in other words | Second ask is answered from the cache with no model call. | LangCache |
| `What's a good pasta recipe?` | Blocked before the model is called. | Semantic routing |
