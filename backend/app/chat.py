"""One chat turn, as a stream of events for the activity panel.

Each step is a small async generator that yields SSE events and records what it learned on the
`Turn`. A step sets `turn.done` when it has already answered (guardrail block, cache hit).

  1. guardrail      Redis semantic router: off-topic or impersonation prompts stop here
  2. cache          LangCache: a similar earlier question is answered without the model
  3. tools          Redis semantic router: choose which tools the model gets to see
  4. memory         Agent Memory: write the user's message, load session + long-term memory
  5. agent          LangGraph agent calls Context Retriever (MCP) and internal tools
  6. save           Agent Memory: store the assistant reply (if the domain wants it)
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, AsyncIterator

from backend.app import services as svc
from backend.app.contracts import ChatRequest
from backend.app.langgraph_agent import AGENT_TOOL_TOKENS
from backend.app.request_context import reset_member_id, reset_thread_id, set_member_id, set_thread_id
from backend.app.trace import (
    Timer,
    compact_mcp_result,
    compact_session_events,
    error_payload,
    ms_since,
    parse_tool_output,
    pop_pending_tool,
    sse,
)

log = logging.getLogger("iris")
domain = svc.domain


@dataclass
class Turn:
    message: str
    thread_id: str
    member_id: str
    timer: Timer = field(default_factory=Timer)
    done: bool = False
    guard_vector: list[float] | None = None
    tool_names: list[str] | None = None
    session_events: list[dict[str, Any]] = field(default_factory=list)
    memories: list[dict[str, Any]] = field(default_factory=list)
    reply: str = ""

    def call(self, name: str, kind: str, payload: dict[str, Any]) -> str:
        return sse("tool-call", toolName=name, toolKind=kind, payload=payload, ts=self.timer.elapsed_ms())

    def result(self, name: str, kind: str, payload: dict[str, Any], started: float) -> str:
        return sse(
            "tool-result", toolName=name, toolKind=kind, payload=payload,
            durationMs=ms_since(started), ts=self.timer.elapsed_ms(),
        )

    def finish(self, **fields: Any) -> str:
        self.done = True
        return sse("done", totalElapsedMs=self.timer.elapsed_ms(), **fields)


def _tool_kind(name: str) -> str:
    if "memory" in name.lower():
        return "memory"
    return "internal_function" if name in {t.name for t in svc.internal_tools.definitions} else "mcp_tool"


# ── 1. Guardrail ─────────────────────────────────────────────────────────────────


async def _guardrail(turn: Turn) -> AsyncIterator[str]:
    if not svc.guardrail_service.is_configured():
        return
    turn.guard_vector = await svc.guardrail_service.embed(turn.message)
    yield turn.call("guardrail_check", "guardrail", {"query": turn.message})
    started = perf_counter()
    verdict = await svc.guardrail_service.check(turn.guard_vector)
    allowed = verdict.get("allowed", True)
    distance = verdict.get("distance")
    yield turn.result(
        "guardrail_check", "guardrail",
        {"allowed": allowed, "route": verdict.get("route"), "distance": round(distance, 3) if distance is not None else None},
        started,
    )
    if allowed:
        return
    branding = domain.manifest.branding
    reply = verdict.get("block_message") or (
        f"I'm your {branding.app_name} assistant and can only help with topics related to this service. "
        "What can I help you with today?"
    )
    yield sse("text-delta", delta=reply)
    yield turn.finish(guardrailBlocked=True)


# ── 2. Semantic cache ────────────────────────────────────────────────────────────


async def _cache(turn: Turn) -> AsyncIterator[str]:
    if not svc.langcache_service.is_configured():
        return
    yield turn.call("semantic_cache_search", "langcache", {"query": turn.message})
    started = perf_counter()
    hit = await svc.langcache_service.search(turn.message)
    if not hit:
        yield turn.result("semantic_cache_search", "langcache", {"hit": False}, started)
        return
    yield turn.result(
        "semantic_cache_search", "langcache",
        {"hit": True, "similarity": round(hit.get("similarity", 0), 3), "cached_prompt": hit.get("prompt", "")},
        started,
    )
    yield sse("text-delta", delta=hit.get("response", ""))
    yield turn.finish(cacheHit=True)


# ── 3. Tool routing ──────────────────────────────────────────────────────────────


async def _tool_routing(turn: Turn) -> AsyncIterator[str]:
    if turn.guard_vector is None or not svc.tool_routing_service.is_configured() or not AGENT_TOOL_TOKENS:
        return
    yield turn.call("tool_routing", "guardrail", {"query": turn.message})
    started = perf_counter()
    selection = await svc.tool_routing_service.select(turn.guard_vector, list(AGENT_TOOL_TOKENS))
    if not selection.fallback:
        turn.tool_names = selection.tools
    saved = sum(AGENT_TOOL_TOKENS.values()) - sum(AGENT_TOOL_TOKENS.get(n, 0) for n in selection.tools)
    payload: dict[str, Any] = {
        "routes": [r["name"] for r in selection.routes],
        "tools": f"{len(selection.tools)} of {len(AGENT_TOOL_TOKENS)}",
        "tokens_saved_per_call": saved,
    }
    if selection.fallback:
        payload["fallback"] = "no route matched, sent every tool"
    yield turn.result("tool_routing", "guardrail", payload, started)


# ── 4. Agent Memory ──────────────────────────────────────────────────────────────


def _memory_line(memory: dict[str, Any]) -> str:
    card = domain.memory_card(memory) if hasattr(domain, "memory_card") else {}
    card = {"id": memory.get("id"), "text": memory.get("text"), **card}
    details = {k: v for k, v in card.items() if k not in ("id", "text") and v not in (None, [], "")}
    return f"- {card['text']} {json.dumps(details, default=str)} [memory_id: {card['id']}]"


async def _recall_long_term(turn: Turn) -> AsyncIterator[str]:
    """Search long-term memory, load call-start context, then apply per-memory expiry."""
    mem = svc.memory_service
    yield turn.call("long_term_memory_search", "memory", {"query": turn.message})
    started = perf_counter()
    found = await mem.asearch_long_term_memory(text=turn.message, owner_id=turn.member_id, limit=5)

    # Vague openers ("checking in on my data") match nothing semantically, so also load the user's
    # stored context for every turn.
    prefetch_query = getattr(domain, "call_start_query", None)
    if prefetch_query:
        yield turn.call("member_context_prefetch_memory", "memory", {"query": prefetch_query})
        prefetch_started = perf_counter()
        prefetched = await mem.asearch_long_term_memory(
            text=prefetch_query, owner_id=turn.member_id, limit=10, similarity_threshold=0.0
        )
        known = {m.get("id") for m in found}
        found += [m for m in prefetched if m.get("id") not in known]
        yield turn.result("member_context_prefetch_memory", "memory", {"loaded": len(prefetched)}, prefetch_started)

    ttl_report: list[dict[str, Any]] = []
    hidden: list[dict[str, Any]] = []
    if hasattr(domain, "reconcile_long_term_memories"):
        ttl_report = await asyncio.to_thread(domain.reconcile_long_term_memories, svc.settings, found)
    if hasattr(domain, "filter_long_term_memories"):
        found, hidden = domain.filter_long_term_memories(found)
    turn.memories = found

    ttl_days = {t["id"]: t["ttl_days"] for t in ttl_report}
    cards = []
    for memory in found:
        card = dict(domain.memory_card(memory)) if hasattr(domain, "memory_card") else {"id": memory.get("id"), "text": memory.get("text")}
        if card.get("id") in ttl_days:
            card["redis_ttl_days"] = ttl_days[card["id"]]
        cards.append(card)
    payload: dict[str, Any] = {"memories": cards}
    if hidden:
        payload["hidden_from_agent"] = hidden
    yield turn.result("long_term_memory_search", "memory", payload, started)


async def _memory(turn: Turn) -> AsyncIterator[str]:
    mem = svc.memory_service
    if not mem.is_configured():
        return
    try:
        await mem.add_session_event(
            owner_id=turn.member_id, session_id=turn.thread_id, actor_id=turn.member_id,
            role="USER", text=turn.message, metadata={"source": "iris-memory-demo"},
        )
    except Exception as exc:
        log.warning("Session memory write failed: %s", exc)

    yield turn.call("short_term_memory_get", "memory", {"session": turn.thread_id})
    started = perf_counter()
    try:
        session = await mem.get_session(owner_id=turn.member_id, session_id=turn.thread_id)
        turn.session_events = session.get("events", []) if isinstance(session, dict) else []
        yield turn.result("short_term_memory_get", "memory", {"events": compact_session_events(turn.session_events[-6:])}, started)
    except Exception as exc:
        log.warning("short-term GET failed: %s", exc)
        yield turn.result("short_term_memory_get", "memory", {"error": str(exc)}, started)

    try:
        async for chunk in _recall_long_term(turn):
            yield chunk
    except Exception as exc:
        log.warning("long-term SEARCH failed: %s", exc)
        yield turn.result("long_term_memory_search", "memory", {"error": str(exc)}, perf_counter())


async def _enriched_message(turn: Turn) -> str:
    """The user's message plus what Redis knows about them: profile, recent turns, long-term memory."""
    sections: list[str] = []
    profile_hook = getattr(domain, "member_profile_context", None)
    if callable(profile_hook):
        try:
            profile = await asyncio.to_thread(profile_hook, svc.settings, turn.member_id)
        except Exception:
            profile = None
        if profile:
            sections.append(f"Signed-in user:\n{profile}")
    recent = compact_session_events(turn.session_events[-6:])
    if recent:
        sections.append("Short-term memory:\n" + "\n".join(f"{e['role']}: {e['text']}" for e in recent))
    if turn.memories:
        sections.append("Long-term memory:\n" + "\n".join(_memory_line(m) for m in turn.memories[:8]))
    if not sections:
        return turn.message
    return f"{turn.message}\n\nRetrieved context:\n" + "\n\n".join(sections)


# ── 5. Agent ─────────────────────────────────────────────────────────────────────


async def _agent(turn: Turn) -> AsyncIterator[str]:
    try:
        agent = await svc.get_agent()
    except Exception as exc:
        log.error("Agent init failed, rebuilding: %s", exc)
        agent = await svc.get_agent(force_rebuild=True)

    config: dict[str, Any] = {"configurable": {"thread_id": turn.thread_id}}
    if turn.tool_names:
        config["configurable"]["tool_names"] = turn.tool_names
    message = await _enriched_message(turn)

    pending: dict[str, dict[str, Any]] = {}
    started_count = 0
    try:
        async for event in agent.astream_events(
            {"messages": [{"role": "user", "content": message}]}, config=config, version="v2"
        ):
            kind = event["event"]
            name = event.get("name", "")
            data = event.get("data") or {}

            if kind == "on_tool_start":
                started_count += 1
                run_id = str(event.get("run_id") or f"{name}-{started_count}")
                tool_input = data.get("input", {}) if isinstance(data, dict) else {}
                pending[run_id] = {"name": name, "start": perf_counter()}
                yield turn.call(name, _tool_kind(name), tool_input if isinstance(tool_input, dict) else {"input": tool_input})

            elif kind in ("on_tool_end", "on_tool_error"):
                entry = pop_pending_tool(pending, run_id=str(event.get("run_id") or ""), name=name)
                name = name or (entry or {}).get("name", "")
                started = (entry or {}).get("start", perf_counter())
                tool_kind = _tool_kind(name)
                if kind == "on_tool_error":
                    payload = error_payload(data.get("error") if isinstance(data, dict) else None)
                else:
                    payload = parse_tool_output(data.get("output", "") if isinstance(data, dict) else "")
                    if tool_kind == "mcp_tool":
                        payload = compact_mcp_result(payload)
                yield turn.result(name, tool_kind, payload, started)

            elif kind == "on_chat_model_stream":
                chunk = event["data"].get("chunk")
                if chunk and getattr(chunk, "content", None) and not getattr(chunk, "tool_calls", None):
                    turn.reply += chunk.content
                    yield sse("text-delta", delta=chunk.content)

    except Exception as exc:
        error_type, message_text = type(exc).__name__, str(exc)[:300]
        log.error("Agent loop failed: %s: %s", error_type, message_text)
        if "connection" in message_text.lower() or "reset by peer" in message_text.lower():
            svc.discard_agent()  # rebuild on the next request
        for entry in pending.values():  # close any trace rows still showing "Running"
            name = str(entry.get("name", ""))
            yield turn.result(name, _tool_kind(name), {"error": message_text, "type": error_type}, entry.get("start", perf_counter()))
        yield sse("error", errorType=error_type, message=message_text, ts=turn.timer.elapsed_ms())
        yield sse("text-delta", delta=f"\n\n⚠️ {error_type}: {message_text}")
        yield turn.finish()


# ── 6. Save the assistant reply ──────────────────────────────────────────────────


async def _save_reply(turn: Turn) -> None:
    # Domains can keep assistant replies out of Agent Memory so extraction only sees what the user
    # said (replies that restate facts would otherwise be extracted as new events).
    if not (svc.memory_service.is_configured() and turn.reply.strip() and getattr(domain, "record_assistant_events", True)):
        return
    try:
        await svc.memory_service.add_session_event(
            owner_id=turn.member_id, session_id=turn.thread_id, actor_id="assistant",
            role="ASSISTANT", text=turn.reply.strip(), metadata={"source": "iris-memory-demo"},
        )
    except Exception as exc:
        log.warning("Assistant memory write failed: %s", exc)


# ── Entry point ──────────────────────────────────────────────────────────────────


async def cs_event_stream(request: ChatRequest) -> AsyncIterator[str]:
    turn = Turn(
        message=(request.messages[-1].content if request.messages else "").strip(),
        thread_id=request.thread_id or "default",
        member_id=svc.resolve_member_id(request.member_id),
    )
    log.info("REQUEST [thread=%s] %s", turn.thread_id[:8], turn.message[:80])

    for step in (_guardrail, _cache, _tool_routing, _memory):
        async for chunk in step(turn):
            yield chunk
        if turn.done:
            return

    thread_token = set_thread_id(turn.thread_id)
    member_token = set_member_id(turn.member_id)
    try:
        async for chunk in _agent(turn):
            yield chunk
        if turn.done:  # the agent loop failed and already closed the stream
            return
        await _save_reply(turn)
        yield turn.finish()
    finally:
        reset_thread_id(thread_token)
        reset_member_id(member_token)
    log.info("DONE [thread=%s] %dms", turn.thread_id[:8], turn.timer.elapsed_ms())
