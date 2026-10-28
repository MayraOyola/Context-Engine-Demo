from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from pathlib import Path
from time import perf_counter
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_core.messages import AIMessage

from backend.app.context_surface_service import ContextSurfaceService
from backend.app.core.domain_loader import get_active_domain
from backend.app.contracts import ChatRequest
from backend.app.internal_tools import InternalToolService, domain_runtime_config, internal_tool_names
from backend.app.guardrail_service import GuardrailService
from backend.app.langcache_service import LangCacheService
from backend.app.langgraph_agent import AGENT_TOOL_TOKENS, create_agent, create_checkpointer
from backend.app.memory_service import MemoryService
from backend.app.redis_connection import create_redis_client
from backend.app.rag_service import SimpleRAGService
from backend.app.tool_routing_service import ToolRoutingService
from backend.app.request_context import (
    reset_member_id,
    reset_thread_id,
    set_member_id,
    set_thread_id,
)
from backend.app.settings import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("iris")

settings = get_settings()
domain = get_active_domain(settings)


def resolve_member_id(requested: str | None) -> str:
    """The signed-in member for this request: a known demo member, else the configured default."""
    identity = domain.manifest.identity
    default = os.getenv(identity.id_env_var, identity.default_id)
    allowed = {m["id"] for m in getattr(domain, "demo_members", [])}
    return requested if requested and requested in allowed else default
ROOT_DIR = Path(__file__).resolve().parents[2]


def _cors_origins() -> tuple[list[str], bool]:
    raw_value = (settings.cors_origin or "").strip()
    if not raw_value:
        return (
            [
                "http://localhost:3040",
                "http://127.0.0.1:3040",
                "http://localhost:3041",
                "http://127.0.0.1:3041",
            ],
            True,
        )
    if raw_value == "*":
        return (["*"], False)
    origins = [item.strip() for item in raw_value.split(",") if item.strip()]
    extras = [
        "http://localhost:3040",
        "http://127.0.0.1:3040",
        "http://localhost:3041",
        "http://127.0.0.1:3041",
    ]
    for origin in extras:
        if origin not in origins:
            origins.append(origin)
    return (origins, True)


allowed_origins, allow_credentials = _cors_origins()
app = FastAPI(title=f"{domain.manifest.branding.app_name} Demo")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

internal_tools = InternalToolService(settings)
cs_service = ContextSurfaceService(settings)
rag_service = SimpleRAGService(settings)
runtime_config = domain_runtime_config(domain, settings)
memory_service = MemoryService(
    settings,
    similarity_threshold=runtime_config.get("memory_similarity_threshold"),
    memory_type_filter=getattr(domain, "memory_type_filter", None),
)
langcache_service = LangCacheService(settings)
guardrail_service = GuardrailService(settings, domain.manifest.guardrail)
tool_routing_service = ToolRoutingService(settings, domain.manifest.tool_routing)


@app.on_event("startup")
async def _warmup() -> None:
    """Eagerly initialize heavy services so the first request is fast."""
    t0 = perf_counter()
    tasks: list[asyncio.Task] = []
    if guardrail_service.is_configured():
        tasks.append(asyncio.create_task(guardrail_service.warm_up()))
    if tool_routing_service.is_configured():
        tasks.append(asyncio.create_task(tool_routing_service.warm_up()))
    tasks.append(asyncio.create_task(get_agent()))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for r in results:
        if isinstance(r, Exception):
            log.warning("Warmup task failed: %s", r)
    log.info("Warmup complete in %dms", round((perf_counter() - t0) * 1000))


@app.on_event("shutdown")
async def _shutdown() -> None:
    await cs_service.close()
    await memory_service.close()
    await langcache_service.close()
    await guardrail_service.close()

_langgraph_agent = None
_checkpointer = None
_agent_lock = asyncio.Lock()


async def get_agent(*, force_rebuild: bool = False):
    global _langgraph_agent, _checkpointer
    async with _agent_lock:
        if _langgraph_agent is None or force_rebuild:
            t0 = perf_counter()
            _checkpointer = await create_checkpointer(settings)
            _langgraph_agent = await create_agent(settings, internal_tools, cs_service, _checkpointer)
            log.info("Agent initialized in %dms (model=%s)", round((perf_counter() - t0) * 1000), settings.openai_chat_model)
        return _langgraph_agent


class Timer:
    def __init__(self) -> None:
        self._start = perf_counter()
        self._lap = self._start

    def elapsed_ms(self) -> int:
        return round((perf_counter() - self._start) * 1000)

    def lap_ms(self) -> int:
        now = perf_counter()
        delta = round((now - self._lap) * 1000)
        self._lap = now
        return max(delta, 1)

    def phase(self, label: str) -> int:
        ms = self.lap_ms()
        log.info("  %-40s %6dms  (total %dms)", label, ms, self.elapsed_ms())
        return ms


def sse(event_type: str, **fields: Any) -> str:
    return f"data: {json.dumps({'type': event_type, **fields})}\n\n"


def _logo_src(path: Path) -> str:
    suffix = path.suffix.lower()
    mime_type = {
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(suffix, "application/octet-stream")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


_INTERNAL_NAMES = {t.name for t in internal_tools.definitions}


def _is_memory_tool(name: str) -> bool:
    return "memory" in name.lower() or name.startswith("remember_")


def _tool_kind(name: str) -> str:
    if _is_memory_tool(name):
        return "memory"
    return "internal_function" if name in _INTERNAL_NAMES else "mcp_tool"


def _session_event_text(event: dict[str, Any]) -> str:
    content = event.get("content", [])
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("text"):
            parts.append(str(item["text"]))
    return " ".join(parts).strip()


def _short_term_memory_context(events: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for event in events[-6:]:
        text = _session_event_text(event)
        if not text:
            continue
        role = str(event.get("role", "USER")).upper()
        lines.append(f"{role}: {text}")
    return "\n".join(lines)


def _long_term_memory_context(memories: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for memory in memories[:8]:
        text = str(memory.get("text", "")).strip()
        if not text:
            continue
        topics = memory.get("topics", [])
        topic_suffix = f" (topics: {', '.join(topics)})" if isinstance(topics, list) and topics else ""
        attrs = memory.get("attributes")
        attr_suffix = f" attributes={json.dumps(attrs, default=str)}" if isinstance(attrs, dict) and attrs else ""
        id_suffix = f" [memory_id: {memory['id']}]" if memory.get("id") else ""
        lines.append(f"- {text}{topic_suffix}{attr_suffix}{id_suffix}")
    return "\n".join(lines)


def _short_input(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("query", "text", "product_id", "store_id", "order_id", "shipment_id", "tracking_number", "customer_id"):
            value = payload.get(key)
            if value:
                return str(value)
    if payload is None:
        return ""
    return str(payload)


def _thinking_step_for_tool(name: str, payload: Any) -> str | None:
    if hasattr(domain, "describe_tool_trace_step"):
        custom = domain.describe_tool_trace_step(tool_name=name, payload=payload, runtime_config=runtime_config)
        if custom is not None:
            return custom or None

    detail = _short_input(payload)
    if name == domain.manifest.identity.tool_name:
        return "Identify the signed-in user context before using live account data."
    if name == "get_current_time":
        return "Compare live timestamps against relevant dates and status windows."
    if name.startswith("search_"):
        return f"Search domain data using: {detail or 'the current query'}."
    if name.startswith("filter_"):
        return "Filter live domain records to narrow the relevant results."
    if name.startswith("get_"):
        return "Fetch the exact record needed for the current question."
    return None


def _format_elapsed_ms(duration_ms: int) -> str:
    if duration_ms >= 1000:
        return f"{duration_ms / 1000:.1f}s"
    return f"{duration_ms}ms"


def _llm_phase_label(*, llm_call_index: int, tool_calls_seen: int) -> str:
    if llm_call_index == 1 and tool_calls_seen == 0:
        return "Plan the next action and decide whether tools are needed."
    if tool_calls_seen > 0:
        return "Review tool results and decide the next step."
    return "Reason about the request and decide the next step."


def _parse_tool_output(raw_output: Any) -> dict[str, Any]:
    """Normalize a tool's raw output into a JSON-serializable dict payload."""
    if raw_output is None or raw_output == "":
        return {}
    if isinstance(raw_output, dict):
        return raw_output
    if hasattr(raw_output, "content") and isinstance(raw_output.content, str):
        try:
            parsed = json.loads(raw_output.content)
        except (json.JSONDecodeError, TypeError):
            return {"result": raw_output.content}
        return parsed if isinstance(parsed, dict) else {"result": parsed}
    try:
        parsed = json.loads(str(raw_output))
    except (json.JSONDecodeError, TypeError):
        return {"result": str(raw_output)}
    return parsed if isinstance(parsed, dict) else {"result": parsed}


def _tool_error_payload(error: Any, *, fallback: str = "Tool failed.") -> dict[str, str]:
    if error is None:
        return {"error": fallback}
    return {
        "error": str(error) or fallback,
        "type": error.__class__.__name__,
    }


def _tool_duration_ms(start: float | None) -> int:
    if start is None:
        return 1
    return max(round((perf_counter() - start) * 1000), 1)


def _pop_pending_tool(
    pending_tools: dict[str, dict[str, Any]],
    *,
    run_id: str,
    name: str,
) -> dict[str, Any] | None:
    """Match a tool end/error event back to its pending start.

    LangGraph normally provides a stable ``run_id``; when it doesn't, fall back
    to the oldest pending call with the same tool name so the trace still
    resolves instead of stalling on "Running" forever.
    """
    if run_id and run_id in pending_tools:
        return pending_tools.pop(run_id)
    for pending_run_id, pending in list(pending_tools.items()):
        if name and pending.get("name") != name:
            continue
        return pending_tools.pop(pending_run_id)
    return None


@app.get("/api/health")
async def health() -> JSONResponse:
    return JSONResponse({
        "ok": True,
        "openai_configured": bool(settings.openai_api_key),
        "domain": domain.manifest.id,
        "mcp_enabled": bool(settings.mcp_agent_key),
        "memory_enabled": memory_service.is_configured(),
        "langcache_enabled": langcache_service.is_configured(),
        "guardrail_enabled": guardrail_service.is_configured(),
        "tool_routing_enabled": tool_routing_service.is_configured(),
        "internal_tools": internal_tool_names(settings),
    })


@app.get("/api/domain-config")
async def domain_config() -> JSONResponse:
    branding = domain.manifest.branding
    return JSONResponse({
        "id": domain.manifest.id,
        "app_name": branding.app_name,
        "subtitle": branding.subtitle,
        "hero_title": branding.hero_title,
        "placeholder_text": branding.placeholder_text,
        "demo_steps": branding.demo_steps,
        "starter_prompts": [card.model_dump() for card in branding.starter_prompts],
        "theme": branding.theme.model_dump(),
        "logo_src": _logo_src(ROOT_DIR / branding.logo_path),
        "ui": branding.ui.model_dump(),
        "seed_langcache": [
            {"prompt": e.prompt, "response": e.response}
            for e in domain.manifest.seed_langcache
        ],
        "members": getattr(domain, "demo_members", []),
        "default_member_id": os.getenv(
            domain.manifest.identity.id_env_var, domain.manifest.identity.default_id
        ),
    })


@app.get("/api/memory/dashboard")
async def memory_dashboard(thread_id: str | None = None, member_id: str | None = None) -> JSONResponse:
    current_user_id = resolve_member_id(member_id)
    if not memory_service.is_configured():
        return JSONResponse(
            {
                "enabled": False,
                "thread_id": thread_id,
                "short_term": [],
                "long_term": [],
            }
        )

    short_term: list[dict[str, Any]] = []
    long_term: list[dict[str, Any]] = []
    errors: list[str] = []

    if thread_id:
        try:
            session_payload = await memory_service.get_session(owner_id=current_user_id, session_id=thread_id)
            short_term = session_payload.get("events", []) if isinstance(session_payload, dict) else []
        except Exception as exc:
            errors.append(f"short-term memory unavailable: {exc}")

    try:
        long_term = await memory_service.asearch_long_term_memory(
            text="",
            owner_id=current_user_id,
            limit=25,
        )
    except Exception as exc:
        errors.append(f"long-term memory unavailable: {exc}")

    reconciler = getattr(domain, "reconcile_long_term_memories", None)
    if callable(reconciler) and long_term:
        try:
            await asyncio.to_thread(reconciler, settings, long_term)
        except Exception as exc:
            errors.append(f"ttl reconcile unavailable: {exc}")
    memory_filter = getattr(domain, "filter_long_term_memories", None)
    if callable(memory_filter) and long_term:
        _, hidden = memory_filter(long_term)
        hidden_ids = {h["id"] for h in hidden}
        hidden_reason = {h["id"]: h.get("reason", "expired") for h in hidden}
        long_term = [
            {**m, "text": f"[Hidden from agent: {hidden_reason[m.get('id')]}] {m.get('text', '')}"}
            if m.get("id") in hidden_ids
            else m
            for m in long_term
        ]

    return JSONResponse(
        {
            "enabled": True,
            "thread_id": thread_id,
            "owner_id": current_user_id,
            "short_term": short_term,
            "long_term": long_term,
            "errors": errors,
        }
    )


@app.get("/api/memory/extraction-watch")
async def extraction_watch(thread_id: str, member_id: str | None = None) -> StreamingResponse:
    """Show Agent Memory's background extraction in the activity panel.

    Extraction happens inside the Agent Memory service, after the chat turn, so the chat stream
    never sees it. This waits for memories that Agent Memory created from this session and reports
    them, including the structured fields its extraction filled in.
    """
    owner_id = resolve_member_id(member_id)

    async def events() -> AsyncIterator[str]:
        started = perf_counter()
        yield sse(
            "tool-call",
            toolName="agent_memory_extraction",
            toolKind="memory",
            payload={
                "waiting_for": "Agent Memory to extract memories from this session",
                "session_id": thread_id,
                "owner_id": owner_id,
                "note": "Runs in the service in the background, usually within a minute",
            },
            ts=0,
        )
        service = MemoryService(settings)
        seen: list[dict[str, Any]] = []
        try:
            for _ in range(24):  # about two minutes
                await asyncio.sleep(5)
                seen = await service.asearch_long_term_memory(
                    text="health condition event",
                    owner_id=owner_id,
                    session_id=thread_id,
                    limit=50,
                    similarity_threshold=0.0,
                )
                if seen:
                    await asyncio.sleep(3)  # let the rest of the run land
                    seen = await service.asearch_long_term_memory(
                        text="health condition event",
                        owner_id=owner_id,
                        session_id=thread_id,
                        limit=50,
                        similarity_threshold=0.0,
                    )
                    break
        except Exception as exc:
            yield sse("tool-result", toolName="agent_memory_extraction", toolKind="memory",
                      payload={"error": str(exc)}, durationMs=0, ts=0)
            return
        finally:
            await service.close()

        custom = [m for m in seen if m.get("memoryType") == getattr(domain, "memory_type_filter", None)]
        other = [m for m in seen if m not in custom]
        if custom:
            payload: dict[str, Any] = {
                "created_by_agent_memory": [
                    {
                        "id": m.get("id"),
                        "memory_type": m.get("memoryType"),
                        "text": m.get("text"),
                        "attributes": m.get("attributes"),
                    }
                    for m in custom
                ],
                "other_memories_extracted": len(other),
            }
        elif seen:
            payload = {
                "created_by_agent_memory": [],
                "other_memories_extracted": len(other),
                "note": "No health event found in this conversation, so no condition_event was created",
            }
        else:
            payload = {"created_by_agent_memory": [], "note": "Nothing extracted for this session yet"}
        yield sse(
            "tool-result",
            toolName="agent_memory_extraction",
            toolKind="memory",
            payload=payload,
            durationMs=max(round((perf_counter() - started) * 1000), 1),
            ts=0,
        )

    return StreamingResponse(events(), media_type="text/event-stream")


@app.post("/api/demo/expire-soon")
async def expire_soon(member_id: str | None = None, seconds: int = 10) -> JSONResponse:
    """Demo only: let Redis expire a member's newest condition memory within `seconds`.

    This compresses time, not the mechanism: it sets the memory's Redis key TTL to a few seconds,
    and Redis then deletes the record and drops it from the search index.
    """
    fast_forward = getattr(domain, "fast_forward_expiry", None)
    if not callable(fast_forward):
        return JSONResponse({"error": "not supported for this domain"}, status_code=400)
    owner_id = resolve_member_id(member_id)
    result = await asyncio.to_thread(fast_forward, settings, owner_id, max(3, min(seconds, 60)))
    if result is None:
        return JSONResponse({"error": "no active condition memory to expire"}, status_code=404)
    return JSONResponse(result)


@app.post("/api/demo/reset")
async def reset_demo() -> JSONResponse:
    """Return the demo to its starting state: member memories, semantic cache and audit log.

    Context Retriever data is left alone. Session memory is not enumerable, so the UI starts a
    new thread instead.
    """
    seed_sets: dict[str, list[Any]] = (
        domain.seed_memory_sets()
        if hasattr(domain, "seed_memory_sets")
        else {resolve_member_id(None): list(domain.manifest.seed_memories)}
    )
    result: dict[str, Any] = {"members": {}}

    reset_service = MemoryService(settings)  # unfiltered: clears every memory type for the member
    if reset_service.is_configured():
        for owner_id, seeds in seed_sets.items():
            deleted = 0
            for _ in range(10):  # the search caps at 100 per call
                existing = await reset_service.asearch_long_term_memory(
                    text="reset", owner_id=owner_id, limit=100, similarity_threshold=0.0
                )
                ids = [str(m["id"]) for m in existing if m.get("id")]
                if not ids:
                    break
                await reset_service.adelete_long_term_memories(owner_id=owner_id, memory_ids=ids)
                deleted += len(ids)
            for i, entry in enumerate(seeds):
                await asyncio.to_thread(
                    reset_service.create_long_term_memory,
                    text=entry.text,
                    owner_id=owner_id,
                    memory_type=entry.memory_type,
                    topics=entry.topics,
                    attributes=entry.attributes or None,
                    memory_id=f"seed-{domain.manifest.id}-{owner_id}-{i}",
                )
            result["members"][owner_id] = {"deleted": deleted, "seeded": len(seeds)}
    await reset_service.close()

    if langcache_service.is_configured() and domain.manifest.seed_langcache:
        flushed = await langcache_service.flush()
        stored = 0
        for entry in domain.manifest.seed_langcache:
            if await langcache_service.store(
                prompt=entry.prompt, response=entry.response, attributes=entry.attributes or None
            ):
                stored += 1
        result["langcache"] = {"flushed": bool(flushed), "seeded": stored}

    audit_stream = getattr(domain, "audit_stream", None)
    if audit_stream:
        redis_client = create_redis_client(settings)
        result["audit_entries_cleared"] = await asyncio.to_thread(redis_client.delete, audit_stream)

    return JSONResponse(result)


@app.get("/api/tools")
async def list_available_tools() -> JSONResponse:
    tools: list[dict[str, Any]] = []
    for t in internal_tools.definitions:
        tools.append({
            "name": t.name,
            "description": t.description,
            "kind": "internal",
            "input_schema": t.input_schema,
        })
    try:
        mcp_tools = await cs_service.list_tools()
        for t in mcp_tools:
            tools.append({
                "name": t["name"],
                "description": t.get("description", ""),
                "kind": "mcp_tool",
            })
    except Exception:
        pass
    return JSONResponse({"tools": tools, "count": len(tools)})


async def cs_event_stream(request: ChatRequest) -> AsyncIterator[str]:
    timer = Timer()
    phases: list[tuple[str, int]] = []
    thread_id = request.thread_id or "default"
    latest_message = request.messages[-1].content if request.messages else ""
    current_user_id = resolve_member_id(request.member_id)

    log.info("━━━ REQUEST [thread=%s] %s", thread_id[:8], latest_message[:80])

    # ── Guardrail: semantic routing check ──
    guard_vector: list[float] | None = None
    if guardrail_service.is_configured():
        guard_vector = await guardrail_service.embed(latest_message.strip())
        yield sse(
            "tool-call",
            toolName="guardrail_check",
            toolKind="guardrail",
            payload={"query": latest_message.strip()},
            ts=timer.elapsed_ms(),
        )
        guard_start = perf_counter()
        guard_result = await guardrail_service.check(guard_vector)
        guard_ms = max(round((perf_counter() - guard_start) * 1000), 1)

        yield sse(
            "tool-result",
            toolName="guardrail_check",
            toolKind="guardrail",
            payload={
                "allowed": guard_result.get("allowed", True),
                "route": guard_result.get("route"),
                "distance": guard_result.get("distance"),
            },
            durationMs=guard_ms,
            ts=timer.elapsed_ms(),
        )

        if not guard_result.get("allowed", True):
            app_name = domain.manifest.branding.app_name
            subtitle = domain.manifest.branding.subtitle.lower()
            blocked_message = guard_result.get("block_message") or (
                f"I'm your {app_name} {subtitle} assistant — "
                "I can only help with topics related to this service. "
                "What can I help you with today?"
            )
            yield sse("text-delta", delta=blocked_message, ts=timer.elapsed_ms())
            yield sse("done", totalElapsedMs=timer.elapsed_ms(), guardrailBlocked=True)
            log.info(
                "━━━ GUARDRAIL BLOCKED in %dms (route=%s, distance=%.3f): %s",
                guard_ms,
                guard_result.get("route"),
                guard_result.get("distance", 0),
                latest_message[:80],
            )
            return

    # ── Phase 0: Semantic cache check ──
    if langcache_service.is_configured():
        yield sse(
            "tool-call",
            toolName="semantic_cache_search",
            toolKind="langcache",
            payload={"query": latest_message.strip()},
            ts=timer.elapsed_ms(),
        )
        cache_start = perf_counter()
        cache_result = await langcache_service.search(latest_message.strip())
        cache_ms = max(round((perf_counter() - cache_start) * 1000), 1)

        if cache_result:
            yield sse(
                "tool-result",
                toolName="semantic_cache_search",
                toolKind="langcache",
                payload={
                    "hit": True,
                    "similarity": cache_result.get("similarity", 0),
                    "cached_prompt": cache_result.get("prompt", ""),
                },
                durationMs=cache_ms,
                ts=timer.elapsed_ms(),
            )
            cached_response = cache_result.get("response", "")
            yield sse("text-delta", delta=cached_response, ts=timer.elapsed_ms())
            yield sse("done", totalElapsedMs=timer.elapsed_ms(), cacheHit=True)
            log.info("━━━ CACHE HIT in %dms (similarity=%.3f)", cache_ms, cache_result.get("similarity", 0))
            return
        else:
            yield sse(
                "tool-result",
                toolName="semantic_cache_search",
                toolKind="langcache",
                payload={"hit": False},
                durationMs=cache_ms,
                ts=timer.elapsed_ms(),
            )

    yield sse("status", text="Initializing agent…", ts=timer.elapsed_ms())

    # ── Phase 1: Agent init ──
    try:
        agent = await get_agent()
    except Exception as exc:
        log.error("Agent init failed, rebuilding: %s", exc)
        agent = await get_agent(force_rebuild=True)
    phases.append(("agent_init", timer.phase("Agent init")))

    defer_final_answer = runtime_config.get("enable_post_model_verifier", False)
    config = {"configurable": {"thread_id": thread_id}}

    # ── Semantic tool routing: attach only the tools this question needs ──
    if guard_vector is not None and tool_routing_service.is_configured() and AGENT_TOOL_TOKENS:
        all_tool_names = list(AGENT_TOOL_TOKENS)
        yield sse(
            "tool-call",
            toolName="tool_routing",
            toolKind="guardrail",
            payload={"query": latest_message.strip()},
            ts=timer.elapsed_ms(),
        )
        route_start = perf_counter()
        selection = await tool_routing_service.select(guard_vector, all_tool_names)
        route_ms = max(round((perf_counter() - route_start) * 1000), 1)
        if not selection.fallback:
            config["configurable"]["tool_names"] = selection.tools
        total_tokens = sum(AGENT_TOOL_TOKENS.values())
        sent_tokens = sum(AGENT_TOOL_TOKENS.get(name, 0) for name in selection.tools)
        yield sse(
            "tool-result",
            toolName="tool_routing",
            toolKind="guardrail",
            payload={
                "routes": selection.routes,
                "fallback": selection.fallback,
                "tools_selected": len(selection.tools),
                "tools_total": len(all_tool_names),
                "approx_tool_tokens_sent": sent_tokens,
                "approx_tool_tokens_saved_per_call": total_tokens - sent_tokens,
            },
            durationMs=route_ms,
            ts=timer.elapsed_ms(),
        )
        log.info(
            "Tool routing: %d/%d tools (~%d tokens/call saved) routes=%s%s",
            len(selection.tools), len(all_tool_names), total_tokens - sent_tokens,
            [r["name"] for r in selection.routes], " [fallback]" if selection.fallback else "",
        )

    pending_tools: dict[str, dict[str, Any]] = {}
    llm_start_times: dict[str, float] = {}
    llm_step_ids: dict[str, str] = {}
    llm_call_counter = 0
    tool_calls_seen = 0
    last_thinking_step: str | None = None
    final_text = ""
    thread_token = set_thread_id(thread_id)
    member_token = set_member_id(current_user_id)

    # ── Phase 2: Session memory write ──
    if memory_service.is_configured() and latest_message.strip():
        try:
            await memory_service.add_session_event(
                owner_id=current_user_id,
                session_id=thread_id,
                actor_id=current_user_id,
                role="USER",
                text=latest_message.strip(),
                metadata={"source": "iris-memory-demo"},
            )
            yield sse("status", text="Session memory updated.", ts=timer.elapsed_ms())
        except Exception as exc:
            log.warning("Session memory write failed: %s", exc)
            yield sse("status", text=f"Memory logging unavailable: {exc}", ts=timer.elapsed_ms())
    phases.append(("memory_write", timer.phase("Session memory write")))

    # ── Phase 3: Memory enrichment (short-term + long-term) ──
    short_term_events: list[dict[str, Any]] = []
    long_term_memories: list[dict[str, Any]] = []
    if memory_service.is_configured():
        # Short-term
        yield sse(
            "tool-call",
            toolName="short_term_memory_get",
            toolKind="memory",
            payload={"thread_id": thread_id, "owner_id": current_user_id},
            ts=timer.elapsed_ms(),
        )
        st_start = perf_counter()
        try:
            session_payload = await memory_service.get_session(owner_id=current_user_id, session_id=thread_id)
            short_term_events = session_payload.get("events", []) if isinstance(session_payload, dict) else []
            st_ms = max(round((perf_counter() - st_start) * 1000), 1)
            yield sse(
                "tool-result",
                toolName="short_term_memory_get",
                toolKind="memory",
                payload={"event_count": len(short_term_events), "events": short_term_events[-6:]},
                durationMs=st_ms,
                ts=timer.elapsed_ms(),
            )
            log.info("  short-term GET: %d events in %dms", len(short_term_events), st_ms)
        except Exception as exc:
            st_ms = max(round((perf_counter() - st_start) * 1000), 1)
            log.warning("  short-term GET failed (%dms): %s", st_ms, exc)
            yield sse(
                "tool-result",
                toolName="short_term_memory_get",
                toolKind="memory",
                payload={"error": str(exc)},
                durationMs=st_ms,
                ts=timer.elapsed_ms(),
            )

        # Long-term
        yield sse(
            "tool-call",
            toolName="long_term_memory_search",
            toolKind="memory",
            payload={"query": latest_message.strip(), "owner_id": current_user_id},
            ts=timer.elapsed_ms(),
        )
        lt_start = perf_counter()
        try:
            long_term_memories = await memory_service.asearch_long_term_memory(
                text=latest_message.strip(),
                owner_id=current_user_id,
                limit=5,
            )
            lt_ms = max(round((perf_counter() - lt_start) * 1000), 1)
            # Optional call-start load: pull the member's stored context regardless of how the
            # opening message is phrased, so vague openers still get personalized.
            prefetch_query = getattr(domain, "call_start_query", None)
            if prefetch_query:
                yield sse(
                    "tool-call",
                    toolName="member_context_prefetch_memory",
                    toolKind="memory",
                    payload={"query": prefetch_query, "owner_id": current_user_id},
                    ts=timer.elapsed_ms(),
                )
                pf_start = perf_counter()
                prefetched = await memory_service.asearch_long_term_memory(
                    text=prefetch_query,
                    owner_id=current_user_id,
                    limit=10,
                    similarity_threshold=0.0,
                )
                seen_ids = {m.get("id") for m in long_term_memories}
                long_term_memories = long_term_memories + [
                    m for m in prefetched if m.get("id") not in seen_ids
                ]
                yield sse(
                    "tool-result",
                    toolName="member_context_prefetch_memory",
                    toolKind="memory",
                    payload={"memory_count": len(prefetched)},
                    durationMs=max(round((perf_counter() - pf_start) * 1000), 1),
                    ts=timer.elapsed_ms(),
                )
            ttl_changes: list[dict[str, Any]] = []
            reconciler = getattr(domain, "reconcile_long_term_memories", None)
            if callable(reconciler):
                ttl_changes = await asyncio.to_thread(reconciler, settings, long_term_memories)
            expired_hidden: list[dict[str, Any]] = []
            memory_filter = getattr(domain, "filter_long_term_memories", None)
            if callable(memory_filter):
                long_term_memories, expired_hidden = memory_filter(long_term_memories)
            lt_payload: dict[str, Any] = {
                "memory_count": len(long_term_memories),
                "memories": long_term_memories,
            }
            if expired_hidden:
                lt_payload["expired_hidden"] = expired_hidden
            if ttl_changes:
                lt_payload["redis_key_ttl"] = ttl_changes
            yield sse(
                "tool-result",
                toolName="long_term_memory_search",
                toolKind="memory",
                payload=lt_payload,
                durationMs=lt_ms,
                ts=timer.elapsed_ms(),
            )
            log.info("  long-term SEARCH: %d results in %dms", len(long_term_memories), lt_ms)
        except Exception as exc:
            lt_ms = max(round((perf_counter() - lt_start) * 1000), 1)
            log.warning("  long-term SEARCH failed (%dms): %s", lt_ms, exc)
            yield sse(
                "tool-result",
                toolName="long_term_memory_search",
                toolKind="memory",
                payload={"error": str(exc)},
                durationMs=lt_ms,
                ts=timer.elapsed_ms(),
            )
    phases.append(("memory_enrich", timer.phase("Memory enrichment")))

    # ── Phase 4: Build enriched message ──
    memory_context_sections: list[str] = []
    short_term_context = _short_term_memory_context(short_term_events)
    long_term_context = _long_term_memory_context(long_term_memories)
    if short_term_context:
        memory_context_sections.append(f"Short-term memory:\n{short_term_context}")
    if long_term_context:
        memory_context_sections.append(f"Long-term memory:\n{long_term_context}")
    profile_hook = getattr(domain, "member_profile_context", None)
    if callable(profile_hook):
        try:
            profile_text = await asyncio.to_thread(profile_hook, settings, current_user_id)
        except Exception:
            profile_text = None
        if profile_text:
            memory_context_sections.insert(0, f"Signed-in member:\n{profile_text}")
    enriched_message = latest_message
    if memory_context_sections:
        enriched_message = (
            f"{latest_message}\n\n"
            "Retrieved context:\n"
            + "\n\n".join(memory_context_sections)
        )

    # ── Phase 5: LangGraph agent loop ──
    agent_start = perf_counter()
    llm_total_ms = 0
    tool_total_ms = 0

    try:
        async for event in agent.astream_events(
            {"messages": [{"role": "user", "content": enriched_message}]},
            config=config,
            version="v2",
        ):
            kind = event["event"]

            if kind == "on_tool_start":
                name = event.get("name", "")
                tool_calls_seen += 1
                run_id = str(event.get("run_id") or f"{name}-{tool_calls_seen}")
                data = event.get("data") or {}
                tool_input = data.get("input", {}) if isinstance(data, dict) else {}
                pending_tools[run_id] = {"name": name, "start": perf_counter()}
                thinking_step = _thinking_step_for_tool(name, tool_input)
                if thinking_step and thinking_step != last_thinking_step:
                    last_thinking_step = thinking_step
                    yield sse("thinking-step", step=thinking_step, ts=timer.elapsed_ms())
                yield sse("tool-call", toolName=name, toolKind=_tool_kind(name),
                           payload=tool_input if isinstance(tool_input, dict) else {"input": tool_input},
                           ts=timer.elapsed_ms())

            elif kind == "on_tool_end":
                name = event.get("name", "")
                run_id = str(event.get("run_id") or "")
                pending = _pop_pending_tool(pending_tools, run_id=run_id, name=name)
                if pending and not name:
                    name = str(pending.get("name", ""))
                data = event.get("data") or {}
                raw_output = data.get("output", "") if isinstance(data, dict) else ""
                output = _parse_tool_output(raw_output)
                duration_ms = _tool_duration_ms(pending.get("start") if pending else None)
                tool_total_ms += duration_ms
                log.info("  tool %-40s %4dms  [%s]", name, duration_ms, _tool_kind(name))
                yield sse("tool-result", toolName=name, toolKind=_tool_kind(name),
                           payload=output, durationMs=duration_ms, ts=timer.elapsed_ms())

            elif kind == "on_tool_error":
                # Without a terminal event the trace stalls on "Running" forever.
                name = event.get("name", "")
                run_id = str(event.get("run_id") or "")
                pending = _pop_pending_tool(pending_tools, run_id=run_id, name=name)
                if pending and not name:
                    name = str(pending.get("name", ""))
                data = event.get("data") or {}
                error = data.get("error") if isinstance(data, dict) else None
                duration_ms = _tool_duration_ms(pending.get("start") if pending else None)
                tool_total_ms += duration_ms
                log.info("  tool %-40s %4dms  [%s] ERROR", name, duration_ms, _tool_kind(name))
                yield sse("tool-result", toolName=name, toolKind=_tool_kind(name),
                           payload=_tool_error_payload(error), durationMs=duration_ms, ts=timer.elapsed_ms())

            elif kind == "on_chat_model_start":
                llm_call_counter += 1
                llm_start_times[event["run_id"]] = perf_counter()
                step_id = f"llm-step-{llm_call_counter}"
                llm_step_ids[event["run_id"]] = step_id
                if settings.show_llm_trace_steps:
                    step = _llm_phase_label(llm_call_index=llm_call_counter, tool_calls_seen=tool_calls_seen)
                    last_thinking_step = step
                    yield sse("thinking-step", step=step, stepId=step_id, stepKind="llm", ts=timer.elapsed_ms())

            elif kind == "on_chat_model_end":
                start = llm_start_times.pop(event["run_id"], perf_counter())
                step_id = llm_step_ids.pop(event["run_id"], "")
                duration_ms = max(round((perf_counter() - start) * 1000), 1)
                llm_total_ms += duration_ms
                log.info("  llm  #%-2d                                   %4dms  (tools_before=%d)", llm_call_counter, duration_ms, tool_calls_seen)
                if settings.show_llm_trace_steps and step_id:
                    yield sse(
                        "thinking-step-finish",
                        stepId=step_id,
                        durationMs=duration_ms,
                        durationText=_format_elapsed_ms(duration_ms),
                        ts=timer.elapsed_ms(),
                    )

            elif kind == "on_chat_model_stream":
                if defer_final_answer:
                    continue
                chunk = event["data"].get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    if not (hasattr(chunk, "tool_calls") and chunk.tool_calls):
                        final_text += chunk.content
                        yield sse("text-delta", delta=chunk.content)

    except Exception as exc:
        error_type = type(exc).__name__
        error_msg = str(exc)
        short_msg = error_msg[:300] if len(error_msg) > 300 else error_msg
        log.error("Agent loop failed at %dms: %s: %s", timer.elapsed_ms(), error_type, short_msg)

        is_connection_error = "connection" in error_msg.lower() or "reset by peer" in error_msg.lower()
        if is_connection_error:
            log.warning("Connection error detected — will rebuild agent on next request")
            global _langgraph_agent
            _langgraph_agent = None

        # Flush any in-flight tool calls so their traces don't stall on "Running".
        for pending_run_id, pending in list(pending_tools.items()):
            pending_name = str(pending.get("name", ""))
            yield sse(
                "tool-result",
                toolName=pending_name,
                toolKind=_tool_kind(pending_name),
                payload={"error": short_msg, "type": error_type},
                durationMs=_tool_duration_ms(pending.get("start")),
                ts=timer.elapsed_ms(),
            )
        pending_tools.clear()

        yield sse("error", errorType=error_type, message=short_msg, ts=timer.elapsed_ms())
        yield sse("text-delta", delta=f"\n\n⚠️ {error_type}: {short_msg}")
        yield sse("done", totalElapsedMs=timer.elapsed_ms())
        reset_thread_id(thread_token)
        reset_member_id(member_token)
        return

    agent_ms = round((perf_counter() - agent_start) * 1000)
    overhead_ms = agent_ms - llm_total_ms - tool_total_ms
    phases.append(("agent_loop", agent_ms))
    log.info("  %-40s %6dms  (llm=%dms tools=%dms overhead=%dms)", "Agent loop total", agent_ms, llm_total_ms, tool_total_ms, overhead_ms)

    # ── Phase 6: Post-model verifier (if enabled) ──
    if defer_final_answer and settings.show_final_verifier_trace_step:
        yield sse("thinking-step", step="Validate the final answer against recent context and tool results.", ts=timer.elapsed_ms())
        yield sse("status", text="Verifying final answer…", ts=timer.elapsed_ms())

    if defer_final_answer:
        if hasattr(agent, "aget_state"):
            snapshot = await agent.aget_state(config)
            messages = snapshot.values.get("messages", []) if snapshot and snapshot.values else []
            for msg in reversed(messages):
                if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
                    final_text = msg.content if isinstance(msg.content, str) else str(msg.content)
                    break
        if final_text:
            yield sse("text-delta", delta=final_text)

    # ── Phase 7: Save assistant response to memory ──
    # Some domains keep assistant replies out of Agent Memory so background extraction only sees what
    # the member said (replies that restate claims would otherwise be extracted as new events).
    if (
        memory_service.is_configured()
        and final_text.strip()
        and getattr(domain, "record_assistant_events", True)
    ):
        try:
            await memory_service.add_session_event(
                owner_id=current_user_id,
                session_id=thread_id,
                actor_id="assistant",
                role="ASSISTANT",
                text=final_text.strip(),
                metadata={"source": "iris-memory-demo", "mode": request.mode},
            )
        except Exception as exc:
            log.warning("Assistant memory write failed: %s", exc)
            yield sse("status", text=f"Assistant memory logging unavailable: {exc}", ts=timer.elapsed_ms())
    phases.append(("memory_save", timer.phase("Assistant memory save")))

    yield sse("done", totalElapsedMs=timer.elapsed_ms())
    reset_thread_id(thread_token)
    reset_member_id(member_token)

    # ── Request summary ──
    total = timer.elapsed_ms()
    log.info("━━━ DONE [thread=%s] %dms total | llm=%dms (%d calls) tools=%dms (%d calls) overhead=%dms",
             thread_id[:8], total, llm_total_ms, llm_call_counter, tool_total_ms, tool_calls_seen, overhead_ms)


async def rag_event_stream(question: str) -> AsyncIterator[str]:
    timer = Timer()

    if guardrail_service.is_configured() and question.strip():
        guard_vector = await guardrail_service.embed(question.strip())
        yield sse(
            "tool-call",
            toolName="guardrail_check",
            toolKind="guardrail",
            payload={"query": question.strip()},
            ts=timer.elapsed_ms(),
        )
        guard_start = perf_counter()
        guard_result = await guardrail_service.check(guard_vector)
        guard_ms = max(round((perf_counter() - guard_start) * 1000), 1)
        yield sse(
            "tool-result",
            toolName="guardrail_check",
            toolKind="guardrail",
            payload={
                "allowed": guard_result.get("allowed", True),
                "route": guard_result.get("route"),
                "distance": guard_result.get("distance"),
            },
            durationMs=guard_ms,
            ts=timer.elapsed_ms(),
        )
        if not guard_result.get("allowed", True):
            app_name = domain.manifest.branding.app_name
            subtitle = domain.manifest.branding.subtitle.lower()
            blocked_message = guard_result.get("block_message") or (
                f"I'm your {app_name} {subtitle} assistant — "
                "I can only help with topics related to this service. "
                "What can I help you with today?"
            )
            yield sse("text-delta", delta=blocked_message, ts=timer.elapsed_ms())
            yield sse("done", totalElapsedMs=timer.elapsed_ms(), guardrailBlocked=True)
            return

    async for chunk in rag_service.stream_answer(question, timer):
        yield chunk
    yield sse("done", totalElapsedMs=timer.elapsed_ms())


@app.get("/api/domain-events/stream")
async def domain_events_stream(cursor: str = "$") -> StreamingResponse:
    from backend.app.domain_events import stream_domain_events

    return StreamingResponse(
        stream_domain_events(settings, domain, cursor=cursor),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _missing_openai_key_stream() -> AsyncIterator[str]:
    yield sse(
        "text-delta",
        delta=(
            "\u26a0\ufe0f OPENAI_API_KEY is not set. Add it to `.env` "
            "(the backend restarts automatically when `.env` changes), then ask again."
        ),
    )
    yield sse("done", totalElapsedMs=0)


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    question = request.messages[-1].content if request.messages else ""

    if not settings.openai_api_key:
        return StreamingResponse(_missing_openai_key_stream(), media_type="text/event-stream")

    if request.mode == "simple_rag":
        return StreamingResponse(rag_event_stream(question), media_type="text/event-stream")

    return StreamingResponse(
        cs_event_stream(request),
        media_type="text/event-stream",
    )
